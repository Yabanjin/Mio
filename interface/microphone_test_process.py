"""Own only the MicroBoost process opened for a microphone test."""
import atexit
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import threading

from settings_store import ROOT


def _windows(pid, action):
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    @callback_type
    def visit(window, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == pid:
            if action == 'close':
                user.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE: allow settings to be saved.
            elif user.IsWindowVisible(window):
                user.ShowWindowAsync(window, 9)  # SW_RESTORE
        return True

    user.EnumWindows(visit, 0)


class TestMicroBoost:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.lock = threading.Lock()
        self.status = ''

    def start(self, cancelled):
        path = Path(os.path.expandvars(self.config['executable'].strip()))
        executable = (path if path.is_absolute() else ROOT / path).resolve()
        if not executable.is_file() or executable.suffix.lower() != '.exe':
            raise ValueError('Choose an existing MicroBoost executable in Customize > MicroBoost.')
        arguments = self.config.get('arguments', [])
        if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
            raise ValueError('MicroBoost arguments must be a list of text values.')
        folder = self.config.get('working_directory', '').strip()
        cwd = Path(os.path.expandvars(folder)) if folder else executable.parent
        if not cwd.is_absolute(): cwd = ROOT / cwd
        if not cwd.is_dir():
            raise ValueError('MicroBoost working directory does not exist.')
        # Compare executable paths, never kill or reuse a process by name alone.
        command = (
            "$ErrorActionPreference='Stop'; "
            "$ids=@(Get-CimInstance Win32_Process | Where-Object { "
            "$_.ExecutablePath -and $_.ExecutablePath -eq $env:MIO_TEST_EXECUTABLE "
            "} | ForEach-Object { $_.ProcessId }); ConvertTo-Json -InputObject $ids -Compress"
        )
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                env=dict(os.environ, MIO_TEST_EXECUTABLE=str(executable)),
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Unable to check whether MicroBoost is already running. No new instance was opened.')
        existing = json.loads(result.stdout.strip() or '[]')
        if cancelled.is_set(): return
        if existing:
            for pid in existing:
                _windows(int(pid), 'show')
            self.status = 'Using existing MicroBoost — it will stay open after the test.'
            return
        self.process = subprocess.Popen([str(executable), *arguments], cwd=cwd,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
        atexit.register(self.close)
        self.status = 'MicroBoost opened for this test — Stop test will close it.'

    def close(self):
        with self.lock:
            process = self.process
            if process is None: return
            if process.poll() is None:
                try:
                    _windows(process.pid, 'close')
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    # This Popen handle identifies only the instance started by this test.
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=3)
            self.process = None
            atexit.unregister(self.close)
