"""Launch and own one Mio session. Nothing starts at import or UI creation."""
import ctypes
from ctypes import wintypes
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import threading
import time
import uuid
from urllib.request import Request, urlopen
from urllib.error import URLError
from settings_store import ROOT, APPLICATION, read


class Cancelled(Exception):
    pass


class WindowsJob:
    """The OS closes this session and its descendants if the UI exits/crashes."""
    def __init__(self):
        self.handle = None
        if os.name != 'nt':
            return
        class BASIC(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read', 'write', 'other')]
        class EXTENDED(ctypes.Structure):
            _fields_ = [('basic', BASIC), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        settings = EXTENDED()
        settings.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(settings), ctypes.sizeof(settings)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, process):
        if self.handle and not self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            process.terminate()
            process.wait(timeout=5)
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.4):
            return True
    except OSError:
        return False


def health(url):
    try:
        with urlopen(url, timeout=2) as response:
            return json.load(response)
    except (URLError, TimeoutError, OSError, ValueError):
        return None


def endpoint_available(url):
    """Check the configured remote or local HTTP endpoint, including image APIs."""
    try:
        with urlopen(url, timeout=3) as response:
            return 200 <= response.status < 300
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def external_service_available(name, url):
    if not url:
        return False
    if name == 'CodeProject.AI':
        # Face Processing's list endpoint accepts POST, not GET (HTTP 405).
        try:
            with urlopen(Request(url, data=b'', method='POST'), timeout=3) as response:
                data = json.load(response)
                return (response.status == 200 and data.get('success') is True
                        and data.get('moduleName') == 'Face Processing')
        except (URLError, TimeoutError, OSError, ValueError):
            return False
    return endpoint_available(url)


class Runtime:
    def __init__(self, events):
        self.events = events
        self.cancel = threading.Event()
        self.processes = []
        self.log_handles = []
        self.job = None
        self.config = None
        self.finished = threading.Event()
        self.owned_windows_services = []
        self.component_windows_minimized = False

    def manage_windows_service(self, name, action):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('Invalid Windows service name.')
        result = ROOT / 'data/state' / ('service-' + uuid.uuid4().hex + '.json')
        result.parent.mkdir(parents=True, exist_ok=True)
        helper = ROOT / 'scripts/Manage-WindowsService.ps1'
        arguments = subprocess.list2cmdline(['-NoProfile', '-ExecutionPolicy', 'Bypass',
                    '-File', str(helper), '-Action', action, '-Name', name, '-Result', str(result)])
        # Only the service helper is elevated; the Mio interface keeps normal rights.
        command = ("try { $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs "
                   "-WindowStyle Hidden -Wait -PassThru -ErrorAction Stop -ArgumentList '"
                   + arguments.replace("'", "''") + "'; exit $p.ExitCode } catch { exit 1 }")
        self.message(f'{action} Windows service {name} — accept the Windows administrator prompt.')
        try:
            completed = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                      capture_output=True)
            data = json.loads(result.read_text(encoding='utf-8-sig')) if result.exists() else {}
            if completed.returncode or not data.get('ok'):
                raise RuntimeError(f'{name}: ' + data.get('error', 'Windows administrator permission was cancelled or unavailable.'))
            return bool(data.get('changed'))
        finally:
            result.unlink(missing_ok=True)

    def message(self, text):
        log = ROOT / 'data/logs/startup.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as output:
            output.write(time.strftime('%Y-%m-%d %H:%M:%S ') + text + '\n')
        self.events.put({'kind': 'loading', 'text': text})

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    def resolve(self, value):
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        return path if path.is_absolute() else ROOT / path

    def environment(self):
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                   MIO_BACKGROUND_START='1', MIO_PYTHON=str(self.resolve(self.config['python'])),
                   CUDA_VISIBLE_DEVICES=str(self.config['services_gpu']),
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        # Resolve the selected resource paths without moving runtime databases.
        for name, path in self.config['resources'].items():
            env[name] = str(self.resolve(path))
        env['PYTHONPATH'] = str(ROOT / 'vendor/MeloTTS') + os.pathsep + env.get('PYTHONPATH', '')
        env['HF_HOME'] = env['MIO_MELO_CACHE']
        env['HUGGINGFACE_HUB_CACHE'] = str(Path(env['MIO_MELO_CACHE']) / 'hub')
        env['TRANSFORMERS_CACHE'] = env['HUGGINGFACE_HUB_CACHE']
        return env

    def spawn(self, name, args, cwd=None, external=False):
        self.check_cancel()
        log_name = re.sub(r'[^\w.-]', '_', name)
        log = (ROOT / 'data/logs' / f'{log_name}.log').open('a', encoding='utf-8')
        self.log_handles.append(log)
        process = subprocess.Popen(args, cwd=cwd or ROOT, env=dict(os.environ) if external else self.environment(),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.processes.append((name, process))
        self.job.add(process)
        return process

    def minimize_component_windows(self):
        """Reduce configured technical windows once, keeping their services active."""
        if os.name != 'nt' or self.component_windows_minimized:
            return
        self.component_windows_minimized = True
        targets = set()
        for tool in self.config.get('startup_tools', []):
            if tool.get('enabled') and tool.get('name') in ('MicroBoost', 'Insta360 Link Controller'):
                targets.add(os.path.normcase(str(self.resolve(tool['executable']).resolve())))
        for service in self.config.get('external_services', []):
            if service.get('name') == 'VoiceChanger' and service.get('executable'):
                directory = self.resolve(service['executable']).resolve().parent
                targets.add(os.path.normcase(str(directory / 'main.exe')))
                targets.add(os.path.normcase(str(directory / '_internal/native_client/voice-changer-native-client.exe')))
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]

        @callback_type
        def reduce_window(window, unused):
            if not user.IsWindowVisible(window):
                return True
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            handle = kernel.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                size = wintypes.DWORD(32768)
                path = ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                    if os.path.normcase(os.path.normpath(path.value)) in targets:
                        user.ShowWindowAsync(window, 6)  # SW_MINIMIZE; audio/camera stay active.
            finally:
                kernel.CloseHandle(handle)
            return True

        user.EnumWindows(reduce_window, 0)

    def wait_for(self, label, predicate, process=None):
        self.message(label)
        deadline = time.monotonic() + self.config['startup_timeout_seconds']
        while True:
            self.check_cancel()
            if predicate():
                return
            if process is not None and process.poll() is not None:
                raise RuntimeError(f'{label} : process stopped (code {process.returncode}). See data/logs.')
            if time.monotonic() >= deadline:
                raise TimeoutError(f'{label} : timed out. Check paths and logs.')
            if self.cancel.wait(0.5):
                raise Cancelled()

    def preflight(self):
        self.config = read(APPLICATION)
        if not self.resolve(self.config['python']).is_file():
            raise ValueError('Choose python.exe in Customization > Installation and startup.')
        timeout = self.config['startup_timeout_seconds']
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 5 <= timeout <= 1800:
            raise ValueError('Startup timeout must be between 5 and 1800 seconds.')
        for name, path in self.config['resources'].items():
            if not path or not self.resolve(path).exists():
                raise FileNotFoundError(f'Missing resource: {name} — {path}')
        from component_connections import load_connections
        connections = load_connections()
        self.connections = connections
        for key, port in (('transcription', 9000), ('french_voice', 9881), ('multilingual_voice', 9882)):
            from urllib.parse import urlsplit
            url = urlsplit(connections[key]['url'])
            if url.hostname != '127.0.0.1' or url.port != port:
                raise ValueError(f'{key}: this installer starts the bundled service at 127.0.0.1:{port}.')
        model_file = ROOT / 'src/LM Studio/mio-load.json'
        model_settings = read(model_file)
        if self.config['load_llm'] and connections['llm']['model'] != (model_settings.get('api_identifier') or model_settings['model']):
            raise ValueError('Set the same model identifier in Language model / Connection and Local model loading.')
        for port in (9000, 9881, 9882, 9890, 9891, 9893, 9010):
            self.check_cancel()
            if listening(port):
                raise RuntimeError(f'Port {port} already in use. Stop the other Mio session before starting this one.')
        # Service ports remain coordinated with the audio IPC protocol.
        for relative, expected in [('src/Whisper Turbo/config.json', 9000), ('src/MemoireVectorielle/config.json', 9893)]:
            if read(ROOT / relative)['port'] != expected:
                raise ValueError(f'{relative}: the port must remain {expected} for this interface.')

    def start(self):
        try:
            self.preflight()
            for folder in ('logs', 'memory', 'state'):
                (ROOT / 'data' / folder).mkdir(parents=True, exist_ok=True)
            self.job = WindowsJob()
            # Desktop utilities are started once; already running tools are not owned.
            for utility in self.config.get('startup_tools', []):
                if not utility.get('enabled', False):
                    continue
                path = self.resolve(utility['executable'])
                if not path.is_file():
                    raise FileNotFoundError(str(path))
                running = subprocess.run(
                    ['tasklist.exe', '/FI', 'IMAGENAME eq ' + path.name, '/FO', 'CSV', '/NH'],
                    capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if ('"' + path.name + '"').casefold() in running.stdout.casefold():
                    continue
                self.spawn(utility['name'], [str(path), *utility.get('arguments', [])],
                           str(path.parent), external=True)
            for service in self.config['external_services']:
                self.check_cancel()
                endpoints = {
                    'LM Studio': self.connections['llm']['health_url'],
                    'Agent DVR': self.connections['camera']['snapshot_url'],
                    'CodeProject.AI': self.connections['camera']['recognition_url'].rsplit('/', 1)[0] + '/list',
                    'VoiceChanger': self.connections['voice_changer']['configuration_url'],
                }
                endpoint = endpoints.get(service['name'])
                ready = lambda name=service['name'], url=endpoint: external_service_available(name, url)
                if ready():
                    self.message(service['name'] + ' already available')
                    continue
                windows_service = service.get('windows_service')
                if windows_service:
                    if self.manage_windows_service(windows_service, 'Start'):
                        self.owned_windows_services.append(windows_service)
                    self.wait_for(service['name'], ready)
                    continue
                if not service['executable']:
                    raise RuntimeError(service['name'] + ' unavailable. Connect its URL in Customize and start the external service before the chat.')
                path = self.resolve(service['executable'])
                if not path.is_file():
                    raise FileNotFoundError(str(path))
                arguments = service['arguments']
                if not isinstance(arguments, list) or any(not isinstance(x, str) for x in arguments):
                    raise ValueError('Arguments must be a list of strings.')
                working = self.resolve(service['working_directory']) if service.get('working_directory') else path.parent
                process = self.spawn(service['name'], [str(path), *arguments], str(working), external=True)
                self.wait_for(service['name'], ready,
                              process if service['name'] in ('CodeProject.AI', 'VoiceChanger') else None)
            python = str(self.resolve(self.config['python']))
            if self.config['load_llm']:
                loader = self.spawn('llm-load', [python, '-u', str(ROOT / 'src/LM Studio/load_mio.py')])
                self.wait_for('Loading the LLM model', lambda: loader.poll() is not None)
                if loader.returncode:
                    raise RuntimeError('LLM loading failed: see data/logs/llm-load.log.')
            services = [('whisper', 'Whisper Turbo/whisper_turbo_server.py', 9000, 'WhisperTurbo'),
                        ('piper', 'PiperTTS/piper_server.py', 9881, 'PiperTTS'),
                        ('melo', 'MeloTTS/melo_server.py', 9882, 'MeloTTS'),
                        ('memory', 'MemoireVectorielle/server.py', 9893, None)]
            pending = []
            for name, relative, port, signature in services:
                script = ROOT / 'src' / relative
                pending.append((name, port, signature, self.spawn(name, [python, '-u', str(script)], str(script.parent))))
            for name, port, signature, process in pending:
                def ready(port=port, signature=signature):
                    data = health(f'http://127.0.0.1:{port}/health')
                    return isinstance(data, dict) and (signature is None or data.get('service') == signature)
                self.wait_for('Loading: ' + name, ready, process)
            self.check_cancel()
            self.events.put({'kind': 'services_ready'})
        except Exception as error:
            self.message('Startup failed: ' + str(error))
            try:
                self.stop()
            except Exception as stop_error:
                error = RuntimeError(f'{error}\nCleanup: {stop_error}')
            self.events.put({'kind': 'stopped' if isinstance(error, Cancelled) else 'startup_failed', 'text': '' if isinstance(error, Cancelled) else str(error)})
        finally:
            self.finished.set()

    def adopt(self, process):
        self.processes.append(('main', process))
        self.job.add(process)

    def stop(self):
        self.cancel.set()
        if self.job:
            self.job.close()
            self.job = None
        for _, process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.processes.clear()
        for handle in self.log_handles:
            handle.close()
        self.log_handles.clear()
        for service in list(reversed(self.owned_windows_services)):
            self.manage_windows_service(service, 'Stop')
            self.owned_windows_services.remove(service)
