"""Useful settings and Windows process-lifecycle checks; no Mio service startup."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'interface'))
import settings_store
from runtime import WindowsJob


class SettingsTests(unittest.TestCase):
    def test_invalid_values_rejected(self):
        for value in ({}, {'timeout': True}, {'timeout': '10'}):
            with self.assertRaises(ValueError):
                settings_store.validate(value, {'timeout': 10})

    def test_atomic_unicode_write(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(settings_store, 'ROOT', Path(folder)):
            path = Path(folder) / 'config.json'
            settings_store.write(path, {'message': 'Hello! ミオ'})
            self.assertEqual(settings_store.read(path), {'message': 'Hello! ミオ'})
            with self.assertRaises(ValueError):
                settings_store.write(path, {'invalid': float('nan')})
            self.assertEqual(settings_store.read(path), {'message': 'Hello! ミオ'})


class RuntimeTests(unittest.TestCase):

    @unittest.skipUnless(os.name == 'nt', 'Windows job lifecycle')
    def test_job_closes_child_tree(self):
        job = WindowsJob()
        child_code = 'import time; time.sleep(30)'
        code = 'import sys,subprocess,time; sys.stdin.readline(); p=subprocess.Popen([sys.executable,"-c",' + repr(child_code) + ']); print(p.pid,flush=True); time.sleep(30)'
        process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        child_handle = None
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        api.OpenProcess.restype = ctypes.c_void_p
        api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        try:
            job.add(process)
            process.stdin.write('\n')
            process.stdin.flush()
            child_pid = int(process.stdout.readline())
            child_handle = api.OpenProcess(0x100000, False, child_pid)
            self.assertTrue(child_handle)
            job.close()
            process.wait(timeout=5)
            self.assertEqual(api.WaitForSingleObject(child_handle, 5000), 0)
        finally:
            job.close()
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()
            if child_handle:
                api.CloseHandle(child_handle)


if __name__ == '__main__':
    unittest.main()
