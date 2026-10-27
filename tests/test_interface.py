import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'interface'))
import settings_store
from runtime import Runtime, WindowsJob


class SettingsTests(unittest.TestCase):
    def test_all_settings_exist_and_parse(self):
        for _, path in settings_store.catalog():
            self.assertTrue(path.is_file(), str(path))
            settings_store.read(path)

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
    def test_preflight_failure_never_launches(self):
        events = queue.Queue()
        manager = Runtime(events)
        with patch.object(manager, 'preflight', side_effect=ValueError('Missing model')), patch.object(manager, 'spawn') as spawn:
            manager.start()
            spawn.assert_not_called()
        self.assertEqual(events.get()['kind'], 'startup_failed')
        self.assertEqual(manager.processes, [])

    def test_cancellation_cleans_up(self):
        events = queue.Queue()
        manager = Runtime(events)
        manager.cancel.set()
        manager.config = {'external_services': [{'name': 'test', 'port': 1}]}
        with patch.object(manager, 'preflight'), patch.object(manager, 'spawn') as spawn:
            manager.start()
            spawn.assert_not_called()
        event = events.get()
        self.assertEqual(event['kind'], 'startup_failed')
        self.assertEqual(event['text'], '')
        self.assertIsNone(manager.job)

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


class GuiTests(unittest.TestCase):
    def test_open_and_edit_without_starting_services(self):
        from app import MioApp
        with patch('subprocess.Popen', side_effect=AssertionError('Unexpected service launch')):
            app = MioApp()
            try:
                app.root.withdraw()
                app.logs.withdraw()
                app.root.update()
                self.assertIsNone(app.process)
                self.assertIsNone(app.manager)
                self.assertFalse(app.busy)
                self.assertFalse(hasattr(app, 'stop_button'))
                self.assertEqual(app.status.grid_info()['row'], 0)
                self.assertEqual(app.child_status.grid_info()['row'], 1)
                self.assertEqual(app.customize_button.grid_info()['row'], 0)
                # Finishing/cancelling a session restores the configuration controls.
                app.controls(True)
                app.stopping = True
                app.receive({'kind': 'stopped'})
                self.assertFalse(app.busy)
                self.assertFalse(app.stopping)
                self.assertEqual(str(app.customize_button['state']), 'normal')
                # A delayed exit from the old session cannot stop a newly opened UI.
                app.receive({'kind': 'exit', 'pid': -1, 'code': 1})
                self.assertFalse(app.busy)
                app.customize()
                editor = app.editor
                editor.withdraw()
                for index, (_, path) in enumerate(editor.entries):
                    editor.load(index)
                    self.assertEqual(editor.value(), settings_store.read(path), str(path))
                index = next(i for i, (_, p) in enumerate(editor.entries) if p.name == 'Common.txt')
                editor.load(index)
                editor.text.delete('1.0', 'end')
                editor.text.insert('1.0', 'A personality chosen by the user. ミオ')
                with patch('customization.write') as write:
                    self.assertTrue(editor.save())
                    self.assertIn('personality', write.call_args.args[1])
                editor.destroy()
                # Reload sequences shutdown before a new start, without opening ML services.
                app.controls(True)
                with patch.object(app, 'stop_services') as stop:
                    app.reload_services()
                    stop.assert_called_once()
                    self.assertTrue(app.reload_requested)
                with patch.object(app, 'start_services') as start:
                    app.receive({'kind': 'stopped'})
                    start.assert_called_once()
                    self.assertFalse(app.reload_requested)
            finally:
                if app.opacity_save:
                    app.root.after_cancel(app.opacity_save)
                app.root.destroy()


if __name__ == '__main__':
    unittest.main()
