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
from urllib.request import urlopen
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


class Runtime:
    def __init__(self, events):
        self.events = events
        self.cancel = threading.Event()
        self.processes = []
        self.log_handles = []
        self.job = None
        self.config = None

    def message(self, text):
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

    def spawn(self, name, args, cwd=None):
        self.check_cancel()
        log_name = re.sub(r'[^\w.-]', '_', name)
        log = (ROOT / 'data/logs' / f'{log_name}.log').open('a', encoding='utf-8')
        self.log_handles.append(log)
        process = subprocess.Popen(args, cwd=cwd or ROOT, env=self.environment(),
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.processes.append((name, process))
        self.job.add(process)
        return process

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
            for service in self.config['external_services']:
                self.check_cancel()
                port = int(service['port'])
                if listening(port):
                    self.message(service['name'] + ' already available')
                    continue
                if not service['executable']:
                    raise RuntimeError(service['name'] + ' unavailable. Set its executable in Customization or start it before the chat.')
                path = self.resolve(service['executable'])
                if not path.is_file():
                    raise FileNotFoundError(str(path))
                arguments = service['arguments']
                if not isinstance(arguments, list) or any(not isinstance(x, str) for x in arguments):
                    raise ValueError('Arguments must be a list of strings.')
                working = self.resolve(service['working_directory']) if service.get('working_directory') else path.parent
                self.spawn(service['name'], [str(path), *arguments], str(working))
                self.wait_for(service['name'], lambda port=port: listening(port))
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
            self.stop()
            self.events.put({'kind': 'startup_failed', 'text': '' if isinstance(error, Cancelled) else str(error)})

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
