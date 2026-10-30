"""A form editor for the actual settings consumed by Mio."""
import copy
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from settings_store import catalog, read, validate, write, display_label
from field_help import field_help, page_help
from settings_pages import SECTIONS
from ui_interaction import attach


class Customization(tk.Toplevel):
    def __init__(self, parent, on_saved, on_reload=None, on_restart=None):
        super().__init__(parent)
        self.title('Mio — Customization')
        self.geometry('980x700')
        self.minsize(760, 500)
        self.on_saved = on_saved
        self.on_reload = on_reload
        self.on_restart = on_restart
        self.active_section = 'Mio — Main settings'
        self.path = None
        self.original = None
        self.fields = []
        self.microphone_panel = None
        self.section = tk.StringVar(value='Mio — Main settings')
        self.entries = catalog()
        self.protocol('WM_DELETE_WINDOW', self.close)
        ttk.Label(self, text='Select a section, edit its fields, then save. '
                  'Settings will apply when the chat next starts.', wraplength=940,
                  padding=12).pack(fill='x')
        navigation = ttk.Frame(self, padding=(12, 0, 12, 8))
        navigation.pack(fill='x')
        ttk.Label(navigation, text='Menu').pack(side='left', padx=(0, 8))
        menu = ttk.Combobox(navigation, textvariable=self.section, state='readonly', width=28,
                            values=SECTIONS)
        menu.pack(side='left')
        menu.bind('<<ComboboxSelected>>', self.change_section)
        self.section_hint = ttk.Label(navigation, text='', wraplength=550)
        self.section_hint.pack(side='left', padx=12)
        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.pack(fill='both', expand=True, padx=10)
        left = ttk.Frame(panes)
        self.list = tk.Listbox(left, width=35, exportselection=False)
        scrollbar = ttk.Scrollbar(left, command=self.list.yview)
        self.list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.list.pack(fill='both', expand=True)
        for label, _ in self.entries:
            self.list.insert('end', label)
        panes.add(left, weight=1)
        self.right = ttk.Frame(panes)
        panes.add(self.right, weight=3)
        self.title_label = ttk.Label(self.right, font=('Segoe UI', 12, 'bold'), wraplength=580)
        self.title_label.pack(fill='x', pady=5)
        self.raw = tk.BooleanVar(value=False)
        self.toggle = ttk.Checkbutton(self.right, text='Advanced JSON editor (lists and new fields)',
                                      variable=self.raw, command=self.switch)
        self.toggle.pack(anchor='w')
        self.area = ttk.Frame(self.right)
        self.area.pack(fill='both', expand=True)
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill='x')
        self.status = ttk.Label(bottom, text='')
        self.status.pack(side='left')
        ttk.Button(bottom, text='Save', command=self.save).pack(side='right', padx=5)
        if on_reload:
            self.reload_button = ttk.Button(bottom, text='Reload Mio', command=self.reload)
            self.reload_button.pack(side='right', padx=5)
        ttk.Button(bottom, text='Close', command=self.close).pack(side='right')
        self.list.bind('<<ListboxSelect>>', self.select)
        self.list.selection_set(0)
        self.load(0)
        attach(self)

    def change_section(self, _event=None):
        if not self.leave():
            self.section.set(self.active_section)
            return
        self.active_section = self.section.get()
        self.entries = catalog(self.active_section)
        self.list.delete(0, 'end')
        for label, _ in self.entries:
            self.list.insert('end', label)
        self.list.selection_set(0)
        self.load(0)
        is_main = self.active_section.startswith(('Mio —', 'Online —')) or self.active_section == 'Microphone'
        if self.on_reload:
            if is_main:
                self.reload_button.pack(side='right', padx=5)
            else:
                self.reload_button.pack_forget()
        self.section_hint.configure(text=('Save, then Reload Mio. External servers stay running.' if is_main else
            'Save this module separately. Reload Mio does not restart this server. Server settings need its own restart.'))
        if self.active_section == 'Mio — Modules':
            self.reload_button.configure(text='Restart with selected modules')
            self.section_hint.configure(text='Save, then restart Mio to apply the selected base configuration.')
        elif self.on_reload:
            self.reload_button.configure(text='Reload Mio')
        attach(self)

    def changed(self):
        try:
            return self.value() != self.original
        except (ValueError, TypeError):
            return True

    def leave(self):
        if self.path and self.changed():
            answer = messagebox.askyesnocancel('Changes', 'Save changes to this section?', parent=self)
            if answer is None:
                return False
            if answer and not self.save():
                return False
        return True

    def select(self, _event):
        chosen = self.list.curselection()
        if not chosen or chosen[0] == self.index:
            return
        if self.leave():
            self.load(chosen[0])
        else:
            self.list.selection_clear(0, 'end')
            self.list.selection_set(self.index)

    def load(self, index):
        self.index = index
        if not self.entries:
            self.path = None
            self.original = None
            self.title_label.configure(text=self.active_section)
            for widget in self.area.winfo_children():
                widget.destroy()
            ttk.Label(self.area, text='This module has no editable configuration file yet. '
                      'Configure it in its own application.', wraplength=500).pack(padx=12, pady=12)
            return
        label, self.path = self.entries[index]
        self.original = read(self.path)
        self.title_label.configure(text=label)
        self.status.configure(text='')
        self.raw.set(False)
        self.toggle.configure(state='normal' if self.path.suffix == '.json' else 'disabled')
        self.render(copy.deepcopy(self.original))

    def render(self, value):
        for widget in self.area.winfo_children():
            widget.destroy()
        self.microphone_panel = None
        self.fields = []
        self.template = value
        ttk.Label(self.area, text=page_help(self.path, self.raw.get()), wraplength=530,
                  foreground='#475569', justify='left').pack(fill='x', padx=8, pady=(4, 8))
        if self.path.suffix != '.json' or self.raw.get():
            self.text = ScrolledText(self.area, wrap='word', font=('Segoe UI', 11), undo=True)
            self.text.pack(fill='both', expand=True)
            self.text.insert('1.0', json.dumps(value, ensure_ascii=False, indent=2) if self.path.suffix == '.json' else value)
            attach(self.area)
            return
        canvas = tk.Canvas(self.area, highlightthickness=0)
        bar = ttk.Scrollbar(self.area, command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        form = ttk.Frame(canvas, padding=8)
        item = canvas.create_window((0, 0), window=form, anchor='nw')
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        if self.path.parent.name == 'online' and self.path.stem in ('gpt', 'gemini'):
            from online_key_panel import add_key_panel
            from api_connection_panel import ApiConnectionPanel
            add_key_panel(form, self.path.stem)
            ApiConnectionPanel(form, self.path.stem, self.value).pack(fill='x', pady=8)
        if self.path.name == 'microphone-setup.json':
            from microphone_settings import MicrophoneSettings
            self.microphone_panel = MicrophoneSettings(form, value)
            self.microphone_panel.pack(fill='both', expand=True)
            attach(self.area)
            return
        def add(data, keys=()):
            if isinstance(data, dict) and data:
                for key, part in data.items():
                    add(part, keys + (key,))
                return
            if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
                for index, part in enumerate(data):
                    add(part, keys + (index,))
                return
            # Lists of text are natural multiline fields; object lists use structured JSON.
            if (self.path.parent.name == 'online' and keys and keys[-1] in ('tts_model', 'tts_voice')
                    and value.get('tts_source', 'local') == 'local'):
                return
            label = ' / '.join(display_label(k) for k in keys) or 'Value'
            ttk.Label(form, text=label, wraplength=520).pack(anchor='w', pady=(10, 2))
            if self.path.parent.name == 'online' and keys and keys[-1] == 'tts_source':
                choices = {'Local Mio voice': 'local',
                           'Provider API voice': 'provider'}
                control = tk.StringVar(value=next((label for label, key in choices.items() if key == data),
                                                 'Local Mio voice'))
                box = ttk.Combobox(form, textvariable=control, values=tuple(choices), state='readonly')
                box.pack(fill='x')
                get = lambda control=control: choices[control.get()]
                box.bind('<<ComboboxSelected>>', lambda event: self.render(self.value()))
            elif isinstance(data, bool):
                control = tk.BooleanVar(value=data)
                ttk.Checkbutton(form, text='Enabled', variable=control).pack(anchor='w')
                get = control.get
            else:
                is_lines = isinstance(data, list) and all(isinstance(x, str) for x in data)
                structured = isinstance(data, (dict, list)) and not is_lines
                content = '\n'.join(data) if is_lines else (json.dumps(data, ensure_ascii=False, indent=2) if structured else str(data) if data is not None else 'null')
                control = tk.Text(form, height=min(10, max(4 if self.path.parent.name == 'online' else 2,
                                                        content.count('\n') + 2)),
                                  wrap='word', font=('Segoe UI', 10), undo=True)
                control.pack(fill='x')
                control.insert('1.0', content)
                read_content = lambda control=control: control.get('1.0', 'end-1c')
                if self.path.parent.name == 'online' and keys:
                    from model_field import install_hint, model_hint
                    hint = model_hint(self.path.stem, keys[-1])
                    if hint:
                        read_content = install_hint(control, hint)
                if keys and (keys[-1] in ('python', 'executable', 'working_directory') or str(keys[-1]).startswith('MIO_')):
                    def browse(control=control, key=str(keys[-1])):
                        directory = key == 'working_directory' or key in ('MIO_WHISPER_MODELS', 'MIO_PIPER_MODELS', 'MIO_MELO_CACHE', 'MIO_MEMORY_MODELS', 'MIO_VOSK_MODEL', 'MIO_SPEAKER_MODEL')
                        selected = filedialog.askdirectory(parent=self) if directory else filedialog.askopenfilename(parent=self)
                        if selected:
                            control.delete('1.0', 'end')
                            control.insert('1.0', selected)
                    ttk.Button(form, text='Browse…', command=browse).pack(anchor='e')
                def get(control=control, old=data, lines=is_lines, structured=structured, read_content=read_content):
                    text = read_content()
                    if lines:
                        return [line.strip() for line in text.splitlines() if line.strip()]
                    if structured or old is None:
                        return json.loads(text)
                    if type(old) in (int, float):
                        return type(old)(text.strip())
                    return text
            help_label = ttk.Label(form, text=field_help(self.path, keys, data),
                                   wraplength=510, foreground='#475569', justify='left')
            help_label.pack(fill='x', pady=(3, 8))
            help_label.bind('<Configure>', lambda event: event.widget.configure(
                wraplength=max(200, event.width - 12)))
            self.fields.append((keys, get))
        add(value)
        attach(self.area)

    def value(self):
        if self.microphone_panel is not None:
            return self.microphone_panel.value()
        if self.path.suffix != '.json':
            return self.text.get('1.0', 'end-1c')
        if self.raw.get():
            return json.loads(self.text.get('1.0', 'end-1c'))
        result = copy.deepcopy(self.template)
        for keys, get in self.fields:
            if not keys:
                result = get()
                continue
            target = result
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = get()
        return result

    def switch(self):
        requested = self.raw.get()
        self.raw.set(not requested)
        try:
            value = self.value()
        except (ValueError, TypeError) as error:
            messagebox.showerror('Invalid value', str(error), parent=self)
            return
        self.raw.set(requested)
        self.render(value)

    def save(self):
        if self.path is None:
            return True
        try:
            if self.microphone_panel is not None and not self.microphone_panel.stop_test():
                self.status.configure(text='Input is still closing. Wait a moment, then save again.')
                return False
            value = self.value()
            if self.path.suffix == '.json':
                validate(value, self.original)
                if self.path.name == 'microphone-setup.json':
                    from audio_devices import validate_audio
                    validate_audio(value['Audio'])
                if self.path.parent.name == 'online':
                    from online_routing import validate_routing, validate_provider
                    if self.path.stem == 'routing':
                        from settings_store import ROOT
                        protected = [line.split('#', 1)[0].strip()
                                     for path in (ROOT / 'src/MainApp/trigger').rglob('phrases.txt')
                                     for line in path.read_text(encoding='utf-8-sig').splitlines()
                                     if line.split('#', 1)[0].strip()]
                        validate_routing(value, protected)
                    else:
                        validate_provider(value)
                if self.path.name == 'modules.json':
                    from module_settings import validate_modules
                    validate_modules(value)
            elif not value.strip() and self.path.parent.name == 'prompt':
                raise ValueError('A prompt cannot be empty.')
            if self.path.parent.name == 'components':
                from urllib.parse import urlsplit
                for key, item in value.items():
                    if key == 'url' or key.endswith('_url'):
                        parsed = urlsplit(item)
                        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                            raise ValueError(f'{key}: enter an HTTP(S) URL without credentials')
            write(self.path, value)
            if self.microphone_panel is not None:
                self.microphone_panel.stop_test()
            self.original = copy.deepcopy(value)
            self.status.configure(text='Saved — applies on startup')
            self.on_saved()
            return True
        except (ValueError, TypeError, OSError) as error:
            messagebox.showerror('Unable to save', str(error), parent=self)
            return False

    def close(self):
        if self.leave():
            self.destroy()

    def reload(self):
        if self.active_section == 'Mio — Modules' and self.on_restart:
            if self.save():
                self.on_restart()
            return
        if self.save() and self.on_reload:
            self.on_reload()
