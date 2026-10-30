"""Input selection and an explicit, temporary raw-input level test."""
import copy
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from audio_devices import SAMPLE_RATE, dbfs, resolve_input_device, validate_audio


class InputMonitor:
    """Audio stays in memory; only scalar measurements reach the interface."""
    def __init__(self, config, boost_config=None):
        self.config = config
        self.boost_config = boost_config
        self.utility_status = ''
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.error = ''
        self.device = ''
        self.finished = False
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='Mio-Input-Test')
        self.thread.start()

    def run(self):
        utility = None
        try:
            import numpy as np
            import sounddevice as sd
            index = resolve_input_device(self.config, sd)
            device = sd.query_devices(index)
            self.device = f"{device['name']} — {sd.query_hostapis(device['hostapi'])['name']}"
            sd.check_input_settings(device=index, channels=1, dtype='float32', samplerate=SAMPLE_RATE)
            if self.stop_event.is_set():
                return
            if self.boost_config is not None:
                from microphone_test_process import TestMicroBoost
                utility = TestMicroBoost(self.boost_config)
                self.utility_status = 'Opening MicroBoost…'
                utility.start(self.stop_event)
                self.utility_status = utility.status
            if self.stop_event.is_set():
                return
            def callback(data, frames, timing, status):
                # Accumulate peaks between UI updates so short overloads are not lost.
                square = float(np.sum(np.square(data, dtype=np.float64)))
                peak = float(np.max(np.abs(data)))
                with self.lock:
                    old = self.latest or (0.0, 0, 0.0, False)
                    self.latest = (old[0] + square, old[1] + data.size,
                                   max(old[2], peak), old[3] or bool(status))
            with sd.InputStream(device=index, channels=1, samplerate=SAMPLE_RATE,
                                blocksize=320, dtype='float32', callback=callback):
                deadline = time.monotonic() + 30
                while not self.stop_event.wait(0.1) and time.monotonic() < deadline:
                    if utility and utility.process and utility.process.poll() is not None:
                        raise RuntimeError('MicroBoost closed before the test finished.')
        except Exception as error:
            self.error = str(error)
        finally:
            if utility is not None:
                try:
                    utility.close()
                except Exception as error:
                    self.error = (self.error + ' ' if self.error else '') + f'Unable to close test MicroBoost: {error}'
            self.finished = True
            self.done.set()

    def snapshot(self):
        with self.lock:
            latest, self.latest = self.latest, None
        return latest

    def stop(self):
        self.stop_event.set()


class MicrophoneSettings(ttk.Frame):
    def __init__(self, parent, value):
        super().__init__(parent, padding=8)
        self.template = copy.deepcopy(value)
        audio = value['Audio']
        self.monitor = None
        self.after_id = None
        self.clip_until = 0
        self.rms_db = self.peak_db = -80.0
        self.source = tk.StringVar(value=('Windows default input' if audio.get('microphone_source') == 'default'
                                         else 'Specific input device'))
        self.selected = tk.StringVar()
        self.device_map = {}
        self.initial_selection = None
        self.boost = tk.BooleanVar(value=value['MicroBoost']['enabled'])
        ttk.Label(self, text='Microphone connection', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        self.help('Choose a direct microphone, sound-card input or virtual cable. Test uses the selection '
                  'below, even before saving. Save, then Reload Mio to apply it to the chat.')
        self.source_box = ttk.Combobox(self, textvariable=self.source, state='readonly',
                                      values=('Windows default input', 'Specific input device'))
        self.source_box.pack(fill='x', pady=(6, 4))
        self.source_box.bind('<<ComboboxSelected>>', self.source_changed)
        row = ttk.Frame(self)
        row.pack(fill='x')
        self.device_box = ttk.Combobox(row, textvariable=self.selected, state='readonly', width=54)
        self.device_box.pack(side='left', fill='x', expand=True)
        self.device_box.bind('<<ComboboxSelected>>', lambda e: self.stop_test())
        ttk.Button(row, text='Refresh inputs', command=self.refresh).pack(side='right', padx=(6, 0))
        self.resolved = ttk.Label(self, text='', wraplength=550)
        self.resolved.pack(fill='x', pady=5)
        ttk.Checkbutton(self, text='Launch MicroBoost with Mio (optional)', variable=self.boost).pack(anchor='w', pady=5)
        self.help('A well-amplified microphone or audio interface can feed Mio directly. MicroBoost is '
                  'optional. Tip: use MicroBoost with VB-Cable to increase gain when needed; choose '
                  'CABLE Output here to hear its processed signal. For direct input, choose your microphone '
                  'or Windows default input. When checked, Test microphone also opens MicroBoost; '
                  'Stop test closes the instance opened for the test. An already running MicroBoost '
                  'stays open. Save applies automatic launch on the next full Start. '
                  'Windows audio routing is not changed.')
        self.low_db = dbfs(max(audio['vb_cable_gate_rms'], audio['whisper_gate_rms']))
        ttk.Label(self, text='Raw input level — before Mio noise gates and echo processing',
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(14, 3))
        self.meter = tk.Canvas(self, height=86, bg='#172335', highlightthickness=0)
        self.meter.pack(fill='x')
        self.meter.bind('<Configure>', lambda e: self.draw())
        self.level = ttk.Label(self, text='RMS: —    Peak: —')
        self.level.pack(anchor='w', pady=4)
        self.feedback = ttk.Label(self, text='Not listening. Click Test microphone and speak normally.', wraplength=550)
        self.feedback.pack(fill='x')
        self.utility_label = ttk.Label(self, text='', wraplength=550, foreground='#475569')
        self.utility_label.pack(fill='x', pady=3)
        self.test_button = ttk.Button(self, text='Test microphone', command=self.toggle_test)
        self.test_button.pack(anchor='w', pady=6)
        self.help('Low marker: the higher of the two current noise gates, shown in dBFS RMS. '
                  'Speech should be clearly above this marker; quiet pauses may be below it. '
                  'High marker: −6 dBFS peak, a headroom guide, not a limiter. '
                  'Keep peaks below it; 0 dBFS is the digital ceiling. A green meter alone does not '
                  'guarantee recognition: background noise and distance also matter. '
                  'The test stops after 30 seconds. No recording is saved or sent to a service.')
        ttk.Label(self, text='Existing noise gates', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(12, 2))
        self.gates = {}
        for key, label in (('vb_cable_gate_rms', 'Vosk gate (RMS, 0–1)'),
                           ('whisper_gate_rms', 'Whisper gate (RMS, 0–1)'),
                           ('vb_cable_gate_hold_ms', 'Gate hold (milliseconds)')):
            line = ttk.Frame(self)
            line.pack(fill='x', pady=2)
            ttk.Label(line, text=label).pack(side='left')
            var = tk.StringVar(value=str(audio[key]))
            self.gates[key] = var
            ttk.Entry(line, textvariable=var, width=12).pack(side='right')
            var.trace_add('write', self.gates_changed)
        self.help('These thresholds apply to direct inputs as well as VB-Cable. Zero disables a gate. '
                  'Keep the current values unless quiet speech is being cut off; increasing a gate '
                  'rejects more low-level sound. Changing a gate does not amplify the microphone.')
        self.bind('<Destroy>', self.destroyed, add='+')
        self.refresh()

    def help(self, text):
        label = ttk.Label(self, text=text, wraplength=550, foreground='#475569', justify='left')
        label.pack(fill='x', pady=(3, 5))
        label.bind('<Configure>', lambda e: e.widget.configure(wraplength=max(200, e.width - 8)))

    def refresh(self):
        self.stop_test()
        try:
            import sounddevice as sd
            config = self.template['Audio']
            previous = self.selected.get()
            self.device_map = {}
            preferred = ''
            for i, d in enumerate(sd.query_devices()):
                if d['max_input_channels'] < 1:
                    continue
                api = sd.query_hostapis(d['hostapi'])['name']
                label = f"{d['name']} — {api} [{i}]"
                self.device_map[label] = (d['name'], api)
                if d['name'].startswith(config['microphone_name_prefix']) and api == config['microphone_hostapi']:
                    preferred = label
            self.device_box.configure(values=list(self.device_map))
            self.selected.set(previous if previous in self.device_map else preferred)
            if self.initial_selection is None:
                self.initial_selection = self.selected.get()
            if not self.selected.get():
                self.resolved.configure(text='Saved input is unavailable. Select an input or use Windows default.')
            else:
                self.resolved.configure(text='Device list refreshed. Use Test microphone to check the signal.')
        except Exception as error:
            self.resolved.configure(text=f'Unable to list inputs: {error}')
        self.source_changed()

    def source_changed(self, _event=None):
        self.stop_test()
        self.device_box.configure(state='readonly' if self.source.get() == 'Specific input device' else 'disabled')
        if self.source.get() == 'Windows default input':
            self.resolved.configure(text='Uses the Windows default input when Test or Mio starts. '
                                   'Changing the Windows default requires restarting the stream.')

    def value(self):
        result = copy.deepcopy(self.template)
        audio = result['Audio']
        audio['microphone_source'] = 'default' if self.source.get() == 'Windows default input' else 'device'
        if audio['microphone_source'] == 'device':
            selected = self.device_map.get(self.selected.get())
            if selected and self.selected.get() != self.initial_selection:
                audio['microphone_name_prefix'], audio['microphone_hostapi'] = selected
            # Preserve an unplugged saved input; Test reports it instead of silently falling back.
        for key, variable in self.gates.items():
            old = audio[key]
            audio[key] = type(old)(variable.get().strip())
        validate_audio(audio)
        result['MicroBoost']['enabled'] = self.boost.get()
        return result

    def gates_changed(self, *_args):
        try:
            settings = self.value()
            audio = settings['Audio']
            self.low_db = dbfs(max(audio['vb_cable_gate_rms'], audio['whisper_gate_rms']))
            self.draw()
        except (ValueError, TypeError):
            pass

    def draw(self):
        canvas = self.meter
        canvas.delete('all')
        width = max(100, canvas.winfo_width())
        x = lambda db: 12 + (width - 24) * (max(-80, min(0, db)) + 80) / 80
        canvas.create_rectangle(12, 27, width-12, 51, fill='#27364b', outline='')
        color = '#d09b57' if self.rms_db < self.low_db else '#70b99b'
        if self.peak_db > -6: color = '#ce7682'
        canvas.create_rectangle(12, 27, x(self.rms_db), 51, fill=color, outline='')
        for value, label, col in ((self.low_db, f'Low {self.low_db:.1f}', '#e4ba7a'),
                                  (-6, 'High −6', '#d999ad')):
            canvas.create_line(x(value), 22, x(value), 56, fill=col, width=2)
            canvas.create_text(x(value), 12, text=label, fill=col, anchor='e' if value == -6 else 'center')
        for value in (-80, -60, -40, -20, 0):
            canvas.create_text(x(value), 69, text=str(value), fill='#c5cbd6',
                               anchor='w' if value == -80 else 'e' if value == 0 else 'center')

    def toggle_test(self):
        if self.monitor:
            self.stop_test()
            return
        try:
            settings = self.value()
            audio = settings['Audio']
        except (ValueError, TypeError) as error:
            messagebox.showerror('Invalid microphone settings', str(error), parent=self)
            return
        self.clip_until = 0
        self.rms_db = self.peak_db = -80
        self.monitor = InputMonitor(audio, settings['MicroBoost'] if self.boost.get() else None)
        self.utility_label.configure(text='Opening MicroBoost…' if self.boost.get() else 'MicroBoost is not used by this test.')
        self.test_button.configure(text='Stop test')
        self.feedback.configure(text='Opening the selected input…')
        self.poll()

    def poll(self):
        self.after_id = None
        monitor = self.monitor
        if monitor is None: return
        if monitor.utility_status:
            self.utility_label.configure(text=monitor.utility_status)
        if monitor.device: self.resolved.configure(text='Listening to: ' + monitor.device)
        sample = monitor.snapshot()
        if sample:
            power, count, peak, overflow = sample
            self.rms_db = dbfs((power / count) ** 0.5)
            self.peak_db = dbfs(peak)
            if peak >= 0.999: self.clip_until = time.monotonic() + 2
            if time.monotonic() < self.clip_until:
                status = 'Clipping detected — reduce microphone or MicroBoost gain.'
            elif overflow:
                status = 'Audio overflow — close other microphone tests or try another audio backend.'
            elif self.peak_db > -6:
                status = 'Peaks are too high — lower gain to leave headroom.'
            elif self.rms_db < self.low_db:
                status = 'Below the current gates — speak normally; raise gain if speech stays here.'
            else:
                status = 'Level above the gates, with peak headroom. Check background noise during pauses.'
            self.level.configure(text=f'RMS: {self.rms_db:.1f} dBFS    Peak: {self.peak_db:.1f} dBFS')
            self.feedback.configure(text=status)
            self.draw()
        if monitor.finished:
            error = monitor.error
            self.stop_test()
            self.feedback.configure(text=('Unable to test input: ' + error if error else
                                          'Test finished. No recording was saved.'))
            return
        self.after_id = self.after(100, self.poll)

    def stop_test(self):
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        if self.monitor is not None:
            self.monitor.stop()
            if not self.monitor.done.wait(1.0):
                self.feedback.configure(text='Closing the microphone test and its MicroBoost window…')
                self.test_button.configure(state='disabled')
                self.after_id = self.after(100, self.poll)
                return False
            error = self.monitor.error
            self.monitor = None
            self.utility_label.configure(text='')
            self.feedback.configure(text=error or 'Test stopped. Microphone released; test MicroBoost closed if opened here.')
        self.test_button.configure(text='Test microphone', state='normal')
        return True

    def destroyed(self, event):
        if event.widget is self:
            if self.after_id is not None:
                self.after_cancel(self.after_id)
                self.after_id = None
            if self.monitor is not None:
                self.monitor.stop()
                self.monitor = None
