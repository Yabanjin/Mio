"""Mio desktop entry point: configure first, start services on demand."""
import os
import ctypes
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import uuid
import json
from ui_interaction import install, attach
from settings_store import ROOT, APPLICATION, read

os.environ['MIO_BACKGROUND_START'] = '1'
sys.path.insert(0, str(ROOT / 'src/MainApp'))
from chat_base import ChatWindow, BG, FG
from customization import Customization
from runtime import Runtime
from typed_chat import registered_authors


class MioApp(ChatWindow):
    def __init__(self):
        self.manager = None
        self.busy = False
        self.stopping = False
        self.reload_requested = False
        self.closing = False
        self.editor = None
        self.reloading_main = False
        super().__init__(auto_start=False)
        self.session_tokens = {self.token}
        install(self.root)
        composer = tk.LabelFrame(self.root, text=' Type your message ', bg=BG, fg='#aaa3c4',
                                 font=('Segoe UI', 9, 'bold'), padx=4, pady=2,
                                 borderwidth=0, relief='flat', highlightbackground='#68627f', highlightcolor='#68627f', highlightthickness=1)
        author_bar = tk.Frame(composer, bg=BG)
        tk.Label(author_bar, text='Type your message', bg=BG, fg='#aaa3c4',
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 8))
        self.author_options = tk.Frame(author_bar, bg=BG)
        self.author_options.pack(side='left', anchor='s')
        composer.configure(text='', labelwidget=author_bar)
        self.selected_author = tk.StringVar(master=self.root)
        self.author_buttons = {}
        self.refresh_authors()
        composer.pack(side='bottom', fill='x', before=self.command_frame, padx=8, pady=4)
        self.command_frame.pack_forget()
        composer.pack_forget()
        # Reserve both bottom panels before the expanding chat receives space.
        self.command_frame.pack(side='bottom', fill='x', before=self.chat, padx=8, pady=(0, 3))
        composer.pack(side='bottom', fill='x', before=self.chat, padx=8, pady=4)
        input_frame = tk.Frame(composer, bg='#182233')
        input_frame.pack(side='left', fill='both', expand=True)
        scrollbar = tk.Scrollbar(input_frame, orient='vertical')
        scrollbar.pack(side='right', fill='y')
        self.draft = tk.Text(input_frame, height=3, wrap='word', font=('Segoe UI', 11),
                             undo=True, bg='#182233', fg=FG, insertbackground=FG,
                             selectbackground='#335b85', selectforeground='#ffffff',
                             relief='flat', padx=8, pady=5, yscrollcommand=scrollbar.set)
        self.draft.pack(side='left', fill='both', expand=True)
        scrollbar.configure(command=self.draft.yview)
        # A slim upward arrowhead, with a muted blue rather than white.
        self.send_arrow = tk.PhotoImage(master=self.root, width=28, height=28)
        for row in range(4, 23):
            half_width = int((row - 4) * 0.52)
            self.send_arrow.put('#819cbd', to=(14-half_width, row, 15+half_width, row+1))
        for row in range(16, 23):
            half_width = int((row - 16) * 0.52)
            self.send_arrow.put('#223954', to=(14-half_width, row, 15+half_width, row+1))
        send_button = tk.Button(input_frame, text='Send', image=self.send_arrow,
                                compound='top', command=self.send_text,
                                bg='#223954', fg='#819cbd', activebackground='#2c4360', activeforeground='#9aaec9',
                                relief='flat', font=('Segoe UI', 9, 'bold'), cursor='hand2', padx=6, pady=0, borderwidth=0, highlightthickness=0)
        def position_send(event=None):
            send_button.place(relx=1.0, rely=1.0, anchor='se',
                              x=-scrollbar.winfo_reqwidth()-6, y=-1)
            self.draft.tag_configure('send_clearance', rmargin=send_button.winfo_reqwidth()+16)
        input_frame.bind('<Configure>', position_send)
        def reserve_send_space(event=None):
            if self.draft.edit_modified():
                self.draft.tag_add('send_clearance', '1.0', 'end')
                self.draft.edit_modified(False)
        self.draft.bind('<<Modified>>', reserve_send_space)
        position_send()

        self.draft.bind('<Control-Return>', lambda event: self.send_text())
        attach(self.root)
        self.root.title('Mio — Customize Mio and start the chat')
        self.root.attributes('-topmost', False)
        self.status.master.destroy()
        header = tk.Frame(self.root, bg=BG, highlightbackground='#68627f',
                          highlightcolor='#68627f', highlightthickness=0, padx=4, pady=1)
        header.pack(fill='x', before=self.chat, padx=10, pady=2)
        header.columnconfigure(0, weight=1)
        status_group = tk.Frame(header, bg=BG)
        status_group.grid(row=0, column=0, sticky='nw')
        self.status = tk.Label(status_group, bg=BG, fg='#a5b4fc', anchor='w', pady=0, borderwidth=0, highlightthickness=0, font=('Segoe UI', 13, 'bold'))
        self.status.grid(row=0, column=0, sticky='w')
        self.child_status = tk.Label(status_group, bg=BG, fg='#fcd34d', anchor='w', pady=0, borderwidth=0, highlightthickness=0, font=('Segoe UI', 9, 'bold'))
        self.child_status.grid(row=1, column=0, sticky='w')
        self.detail = tk.Label(header, bg=BG, fg='#cbd5e1', anchor='w',
                               font=('Segoe UI', 8), width=28, height=1, wraplength=0)
        self.detail.grid(row=0, column=0, sticky='sw', padx=(88, 0))
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
        self.command_frame.configure(text=' Controls ', fg='#aaa3c4', borderwidth=0, relief='flat', padx=4, pady=2, highlightbackground='#68627f', highlightcolor='#68627f', highlightthickness=1)
        self.chat.frame.configure(bg=BG, padx=4, pady=2, highlightbackground='#68627f',
                                  highlightcolor='#68627f', highlightthickness=1)
        # One continuous outer frame surrounds history and composer.
        self.chat.frame.configure(highlightthickness=0)
        composer.configure(highlightthickness=0)
        for bar in (self.chat.vbar, self.command_help.vbar, scrollbar):
            bar.configure(width=16, borderwidth=0, highlightthickness=0)
        self.command_help.configure(state='normal')
        self.command_help.delete('1.0', 'end')
        self.command_help.insert('end', 'Customization: prompts, replies, commands and installation.\n'
                                 'Start: load services after saving your settings.')
        self.command_help.configure(state='disabled')
        self.status.configure(text='READY TO CONFIGURE', font=('Segoe UI', 13, 'bold'))
        self.child_status.configure(text='[NORMAL]')
        # Only the message row receives additional vertical space.
        self.detail.configure(height=1)
        self.root.update_idletasks()
        header_height = header.winfo_reqheight()
        # Match the fixed height of the Controls panel below.
        controls_height = self.command_frame.winfo_reqheight()
        composer_height = controls_height
        minimum_width = max(580, header.winfo_reqwidth() + 20)
        for panel in (header, self.chat, composer, self.command_frame):
            panel.pack_forget()
        header.configure(height=header_height)
        header.grid_propagate(False)
        composer.configure(height=composer_height)
        composer.pack_propagate(False)
        self.command_frame.configure(height=controls_height)
        self.command_frame.pack_propagate(False)
        self.root.columnconfigure(0, weight=1)
        for row in (0, 2, 3):
            self.root.rowconfigure(row, weight=0)
        self.root.rowconfigure(1, weight=1, minsize=80)
        header.grid(row=0, column=0, sticky='ew', padx=8, pady=(2, 2))
        conversation_outline = tk.Frame(
            self.root, bg=BG, highlightbackground='#68627f',
            highlightcolor='#68627f', highlightthickness=1, borderwidth=0)
        conversation_outline.grid(row=1, column=0, rowspan=2,
                                  sticky='nsew', padx=8, pady=(0, 2))
        conversation_outline.lower()
        self.chat.grid(row=1, column=0, sticky='nsew', padx=9, pady=(1, 0))
        composer.grid(row=2, column=0, sticky='ew', padx=9, pady=(0, 3))
        self.command_frame.grid(row=3, column=0, sticky='ew', padx=8, pady=(0, 3))
        self.root.minsize(minimum_width, header_height + composer_height + controls_height + 97)

    def customize(self):
        if self.busy and (self.stopping or self.process is None):
            return
        if self.editor and self.editor.winfo_exists():
            self.editor.lift()
            return
        self.editor = Customization(self.root, self.settings_saved, self.reload_services)

    def settings_saved(self):
        self.detail.configure(text='Settings saved — apply with Reload')
        self.refresh_authors()

    def refresh_authors(self):
        for button in self.author_options.winfo_children():
            button.destroy()
        self.author_buttons.clear()
        try:
            authors = registered_authors()
        except (OSError, ValueError, TypeError) as error:
            self.selected_author.set('')
            self.error('Could not load registered authors: ' + str(error))
            return
        names = [author['name'] for author in authors]
        if self.selected_author.get() not in names:
            self.selected_author.set(names[0] if names else '')
        for name in names:
            button = tk.Button(self.author_options, text=name,
                               command=lambda value=name: self.select_author(value),
                               font=('Segoe UI', 6, 'bold'), relief='flat',
                               borderwidth=0, highlightthickness=0, padx=6, pady=0,
                               cursor='hand2')
            button.pack(side='left', anchor='s', padx=(0, 4))
            self.author_buttons[name] = button
        self.select_author(self.selected_author.get())

    def select_author(self, name):
        self.selected_author.set(name)
        for value, button in self.author_buttons.items():
            selected = value == name
            button.configure(bg='#315f50' if selected else '#263449',
                             fg='#b5f4cf' if selected else '#a9b7ca',
                             activebackground='#315f50' if selected else '#33465e',
                             activeforeground='#b5f4cf' if selected else '#dbe7f5')

    def send_text(self):
        text = self.draft.get('1.0', 'end-1c').strip()
        if not text:
            return 'break'
        if self.reloading_main or not self.process or self.process.poll() is not None:
            self.error('Start Mio before sending a message.')
            return 'break'
        author = self.selected_author.get()
        if author not in self.author_buttons:
            self.error('Choose a registered author before sending a message.')
            return 'break'
        message_id = 'typed-' + uuid.uuid4().hex
        try:
            self.process.stdin.write(json.dumps({'action': 'text', 'text': text,
                                                'author': author, 'id': message_id,
                                                'token': self.token}) + '\n')
            self.process.stdin.flush()
            # Show the user's message immediately; the engine uses this same key.
            super().receive({'kind': 'message', 'key': 'user-' + message_id,
                             'text': text, 'names': [author], 'stage': 'FULL TEXT',
                             'generation': self.generation, 'mio': False})
            self.draft.delete('1.0', 'end')
        except (OSError, ValueError) as error:
            self.error(str(error))
        return 'break'

    def reload_services(self):
        if self.stopping or self.reloading_main:
            return
        if not self.process or self.process.poll() is not None:
            self.detail.configure(text='Settings saved. Press Start when ready.')
            return
        self.reloading_main = True
        self.shutdown_requested = True
        self.customize_button.configure(state='disabled')
        if self.editor and self.editor.winfo_exists():
            self.editor.destroy()
        self.detail.configure(text='Reloading Mio only — external services stay running…')
        process = self.process
        def restart():
            try:
                process.stdin.write(json.dumps({'action': 'reload', 'token': self.token}) + '\n')
                process.stdin.flush()
                process.wait(timeout=45)
                self.events.put({'kind': 'main_stopped_for_reload'})
            except Exception as error:
                self.events.put({'kind': 'main_reload_failed', 'text': str(error)})
        threading.Thread(target=restart, daemon=True, name='Mio-Reload').start()

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
        self.render()
        self.token = uuid.uuid4().hex
        self.session_tokens.add(self.token)
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
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
        if self.process is not None or self.manager.finished.is_set():
            def stop():
                try:
                    self.manager.stop()
                    self.events.put({'kind': 'stopped'})
                except Exception as error:
                    self.events.put({'kind': 'stop_failed', 'text': str(error)})
            threading.Thread(target=stop, daemon=True, name='Mio-Stop').start()

    def receive(self, event):
        kind = event.get('kind')
        if kind == 'retain_service':
            if event.get('token') in self.session_tokens:
                self.manager.retain_service(event['pid'])
            return
        if kind == 'main_stopped_for_reload':
            self.reloading_main = False
            if self.closing or self.stopping:
                return
            self.generation = -1
            self.token = uuid.uuid4().hex
            self.session_tokens.add(self.token)
            self.shutdown_requested = False
            try:
                self.start()
            except Exception as error:
                self.error(str(error))
                self.customize_button.configure(state='normal')
            return
        if kind == 'main_reload_failed':
            self.reloading_main = False
            self.shutdown_requested = False
            self.customize_button.configure(state='normal')
            self.error('Mio reload failed; external services were left running. ' + event['text'])
            return
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
            if event.get('token') and event['token'] != self.token:
                return
            super().receive(event)
            if kind == 'state' and event.get('ready') and self.busy:
                self.customize_button.configure(state='normal')
                try:
                    self.manager.minimize_component_windows()
                except OSError as error:
                    self.log_lines.put_nowait('Could not minimize component windows: ' + str(error) + '\n')

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
