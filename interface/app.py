"""Mio desktop entry point: configure first, start services on demand."""
import os
import ctypes
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import uuid
from settings_store import ROOT, APPLICATION, read

os.environ['MIO_BACKGROUND_START'] = '1'
sys.path.insert(0, str(ROOT / 'src/MainApp'))
from chat_window import ChatWindow, BG, FG
from customization import Customization
from runtime import Runtime


class MioApp(ChatWindow):
    def __init__(self):
        self.manager = None
        self.busy = False
        self.stopping = False
        self.reload_requested = False
        self.closing = False
        self.editor = None
        super().__init__(auto_start=False)
        self.root.title('Mio — Customize Mio and start the chat')
        self.root.attributes('-topmost', False)
        self.status.master.destroy()
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill='x', before=self.chat, padx=10, pady=2)
        header.columnconfigure(0, weight=1)
        status_group = tk.Frame(header, bg=BG)
        status_group.grid(row=0, column=0, sticky='nw')
        self.status = tk.Label(status_group, bg=BG, fg='#a5b4fc', anchor='w', pady=0, font=('Segoe UI', 14, 'bold'))
        self.status.grid(row=0, column=0, sticky='w')
        self.child_status = tk.Label(status_group, bg=BG, fg='#fcd34d', anchor='w', pady=0, font=('Segoe UI', 10, 'bold'))
        self.child_status.grid(row=1, column=0, sticky='w')
        self.detail = tk.Label(header, bg=BG, fg='#cbd5e1', anchor='w',
                               font=('Segoe UI', 9), wraplength=580)
        self.detail.grid(row=1, column=0, columnspan=5, sticky='ew')
        self.detail.configure(text='')
        self.customize_button = tk.Button(header, text='Customize', command=self.customize,
                                         bg='#334155', fg=FG, relief='flat', padx=5, font=('Segoe UI', 9))
        self.customize_button.grid(row=0, column=2, padx=3, sticky='n')
        self.start_button = tk.Button(header, text='Start', command=self.start_services,
                                     bg='#166534', fg=FG, relief='flat', padx=5, font=('Segoe UI', 9))
        self.start_button.grid(row=0, column=3, padx=3, sticky='n')
        tk.Button(header, text='Logs', command=self.show_logs, bg='#263449', fg=FG,
                  relief='flat', padx=5, font=('Segoe UI', 9)).grid(row=0, column=4, padx=(3, 0), sticky='n')
        opacity = tk.Frame(header, bg=BG)
        opacity.grid(row=0, column=1, padx=(4, 3), sticky='n')
        self.transparency_label = tk.Label(opacity, bg=BG, fg=FG, pady=0, font=('Segoe UI', 8))
        self.transparency_label.pack()
        def update_transparency(value):
            self.transparency_label.configure(text=f'Transparency {int(float(value))}%')
            self.set_transparency(value)
        scale = tk.Scale(opacity, from_=0, to=60, orient='horizontal', length=90, showvalue=False, width=10,
                         bg=BG, fg=FG, highlightthickness=0, troughcolor='#263449',
                         font=('Segoe UI', 8), command=update_transparency)
        scale.pack()
        self.transparency_label.configure(text=f"Transparency {int(self.display_settings['transparency_percent'])}%")
        scale.set(self.display_settings['transparency_percent'])
        self.command_help.configure(state='normal')
        self.command_help.delete('1.0', 'end')
        self.command_help.insert('end', 'Customization: prompts, replies, commands and installation.\n'
                                 'Start: load services after saving your settings.')
        self.command_help.configure(state='disabled')
        self.status.configure(text='READY TO CONFIGURE', font=('Segoe UI', 14, 'bold'))
        self.child_status.configure(text='[NORMAL]')

    def customize(self):
        if self.busy and (self.stopping or self.process is None):
            return
        if self.editor and self.editor.winfo_exists():
            self.editor.lift()
            return
        self.editor = Customization(self.root, lambda: self.detail.configure(text='Settings saved — apply with Reload'), self.reload_services)

    def reload_services(self):
        if self.stopping:
            return
        if self.editor and self.editor.winfo_exists():
            self.editor.destroy()
        if self.busy:
            self.reload_requested = True
            self.stop_services()
        else:
            self.start_services()

    def controls(self, busy):
        self.busy = busy
        self.start_button.configure(state='disabled' if busy else 'normal')
        self.customize_button.configure(state='disabled' if busy else 'normal')

    def start_services(self):
        if self.busy:
            return
        if self.editor and self.editor.winfo_exists():
            if not self.editor.leave():
                return
            self.editor.destroy()
        self.controls(True)
        self.shutdown_requested = False
        self.generation = -1
        self.messages.clear()
        try:
            self.display_names = read(ROOT / 'src/MainApp/config/prononciation.json')['display_names']
        except (OSError, ValueError, KeyError) as error:
            self.controls(False)
            self.error(str(error))
            return
        self.render()
        self.token = uuid.uuid4().hex
        self.manager = Runtime(self.events)
        self.status.configure(text='LOADING…')
        threading.Thread(target=self.manager.start, daemon=True, name='Mio-Start').start()

    def start(self):
        # Called only after the service loader reports success on the UI queue.
        env = self.manager.environment()
        # The inherited reader uses the same event protocol; choose the configured Python.
        import subprocess
        config = read(APPLICATION)
        self.process = subprocess.Popen(
            [str(self.manager.resolve(config['python'])), '-u', str(ROOT / 'src/MainApp/main_mistral.py')],
            cwd=ROOT / 'src/MainApp', env=dict(env, MIO_UI_TOKEN=self.token),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.manager.adopt(self.process)
        threading.Thread(target=self.read_output, daemon=True, name='Mio-Chat-Logs').start()
        self.detail.configure(text='Initializing audio and recognition…')

    def stop_services(self):
        if self.stopping:
            return
        if not self.manager or not self.busy:
            if self.closing:
                self.root.destroy()
            return
        self.customize_button.configure(state='disabled')
        self.stopping = True
        self.shutdown_requested = True
        self.manager.cancel.set()
        self.detail.configure(text='Stopping services…')
        # During loading its worker performs cleanup, avoiding concurrent spawn/stop.
        if self.process is not None:
            def stop():
                try:
                    self.manager.stop()
                    self.events.put({'kind': 'stopped'})
                except Exception as error:
                    self.events.put({'kind': 'stop_failed', 'text': str(error)})
            threading.Thread(target=stop, daemon=True, name='Mio-Stop').start()

    def receive(self, event):
        kind = event.get('kind')
        if kind == 'loading':
            self.detail.configure(text=event['text'])
            self.log_lines.put_nowait(event['text'] + '\n')
        elif kind == 'services_ready':
            if self.manager.cancel.is_set():
                def cancel_ready():
                    self.manager.stop()
                    self.events.put({'kind': 'stopped'})
                threading.Thread(target=cancel_ready, daemon=True).start()
                return
            try:
                self.start()
            except Exception as error:
                self.error(str(error))
                # A failed Popen may not have assigned self.process.
                def cleanup():
                    self.manager.stop()
                    self.events.put({'kind': 'stopped'})
                threading.Thread(target=cleanup, daemon=True).start()
        elif kind in ('startup_failed', 'stopped'):
            self.stopping = False
            self.process = None
            self.controls(False)
            self.shutdown_requested = False
            self.status.configure(text='READY TO CONFIGURE')
            self.child_status.configure(text='[NORMAL]')
            self.detail.configure(text='Services stopped')
            if event.get('text'):
                self.error(event['text'])
            if self.closing:
                self.root.destroy()
            elif kind == 'stopped' and self.reload_requested:
                self.reload_requested = False
                self.start_services()
            else:
                self.reload_requested = False
        elif kind == 'stop_failed':
            self.stopping = False
            self.error(event['text'])
            self.reload_requested = False
            self.customize_button.configure(state='normal')
        elif kind == 'exit':
            if self.process is not None and event.get('pid') == self.process.pid and not self.shutdown_requested:
                if event.get('code'):
                    self.error('The Mio engine stopped. Check the logs.')
                self.stop_services()
        elif not self.shutdown_requested:
            super().receive(event)
            if kind == 'state' and event.get('ready') and self.busy:
                self.customize_button.configure(state='normal')

    def error(self, text):
        super().receive({'kind': 'error', 'key': uuid.uuid4().hex, 'text': text})

    def show_logs(self):
        # Include the startup/service logs when the dialogue engine could not start.
        from tkinter import ttk
        if not getattr(self, 'log_folder_button', None):
            self.log_folder_button = ttk.Button(self.logs, text='Open service logs',
                command=lambda: os.startfile(str(ROOT / 'data/logs')))
            self.log_folder_button.pack(fill='x')
        (ROOT / 'data/logs').mkdir(parents=True, exist_ok=True)
        super().show_logs()

    def close(self):
        if self.editor and self.editor.winfo_exists():
            if not self.editor.leave():
                return
            self.editor.destroy()
        self.closing = True
        self.reload_requested = False
        if self.busy:
            self.stop_services()
        else:
            self.root.destroy()


if __name__ == '__main__':
    # Only one controller per installation can own this project's settings/session.
    import hashlib
    mutex = None
    if os.name == 'nt':
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        api.CreateMutexW.restype = ctypes.c_void_p
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        name = 'Local\\MioInterface-' + hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:20]
        mutex = api.CreateMutexW(None, False, name)
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo('Mio', 'This Mio interface is already open.', parent=root)
            root.destroy()
            api.CloseHandle(mutex)
            sys.exit(0)
    try:
        MioApp().root.mainloop()
    finally:
        if mutex:
            api.CloseHandle(mutex)
