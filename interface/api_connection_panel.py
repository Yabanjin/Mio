"""Nonblocking, explicit API connection test for a provider settings page."""
import copy
import queue
import threading
from tkinter import ttk

from api_connection import check_connection


class ApiConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent, provider, get_config):
        super().__init__(parent, text='API connection', padding=8)
        self.provider = provider
        self.get_config = get_config
        self.results = queue.Queue()
        self.cancelled = threading.Event()
        self.after_id = None
        self.busy = False
        self.button = ttk.Button(self, text='Test API connection', command=self.start)
        self.button.pack(anchor='w')
        self.status = ttk.Label(self, text='Not tested.', wraplength=500, justify='left')
        self.status.pack(fill='x', pady=(6, 0))
        self.status.bind('<Configure>', lambda event: self.status.configure(
            wraplength=max(200, event.width - 12)))
        ttk.Label(self, text='Uses the saved key (or its environment variable) and the model IDs '
                  'currently shown below. Save a new key before testing. Only reads model metadata; '
                  'does not generate text or audio, enable a service, or save settings. '
                  'Generation quota, voice support and audio playback require a separate chat test.',
                  wraplength=500, justify='left').pack(fill='x', pady=(6, 0))
        self.bind('<Destroy>', self.destroyed, add='+')

    def start(self):
        if self.busy:
            return
        try:
            config = copy.deepcopy(self.get_config())
        except (ValueError, TypeError):
            self.status.configure(text='Check the fields on this page before testing.', foreground='#a02020')
            return
        self.busy = True
        self.button.configure(state='disabled')
        self.status.configure(text='Checking saved key and selected models…', foreground='#475569')
        # The worker never reads or modifies Tk widgets. Each page owns its queue.
        threading.Thread(target=self.run, args=(config,), daemon=True).start()
        self.after_id = self.after(100, self.poll)

    def run(self, config):
        try:
            result = check_connection(self.provider, config, self.cancelled)
        except ValueError as error:
            result = {'ok': False, 'error': str(error)}
        except Exception:
            # Exceptions may contain a request/header; never display their repr.
            result = {'ok': False, 'error': 'Connection check failed. Check the local configuration and try again.'}
        self.results.put(result)

    def poll(self):
        self.after_id = None
        if self.cancelled.is_set():
            return
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self.after_id = self.after(100, self.poll)
            return
        self.busy = False
        self.button.configure(state='normal')
        text = result.get('error')
        if not text:
            text = '\n'.join(f"{check['role']} ({check['model']}): {check['message']}"
                             for check in result['checks'])
            if result['ok']:
                text += '\nConnection confirmed for these model IDs. Text and voice generation not tested.'
        self.status.configure(text=text, foreground='#166534' if result['ok'] else '#a02020')

    def destroyed(self, event):
        if event.widget is self:
            self.cancelled.set()
            if self.after_id is not None:
                self.after_cancel(self.after_id)
                self.after_id = None
