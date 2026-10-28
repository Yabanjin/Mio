"""Two desktop windows around the unchanged service entry point."""
import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import uuid
from collections import OrderedDict

from chat_events import PREFIX

ROOT = Path(__file__).resolve().parent.parent / 'src/MainApp'
LOG = ROOT.parent.parent / "data/logs/mainapp.log"
BG, FG = "#111827", "#eef2ff"
DISPLAY_CONFIG = ROOT / "config" / "interface_chat.json"


class ChatWindow:
    def __init__(self, auto_start=True):
        self.root = tk.Tk()
        self.display_settings = {"transparency_percent": 0, "message_font_size": 13,
                                 "message_color": "#86efac", "window_width": 626, "window_height": 390}
        try:
            self.display_settings.update(json.loads(DISPLAY_CONFIG.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError, TypeError):
            pass
        self.opacity_save = None
        self.root.title("Mio MainApp — Chat")
        self.root.geometry(f"{int(self.display_settings['window_width'])}x{int(self.display_settings['window_height'])}")
        self.root.minsize(580, 260)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.token = uuid.uuid4().hex
        self.events = queue.Queue()
        self.log_lines = queue.Queue(maxsize=3000)
        self.messages = OrderedDict()
        self.generation = -1
        self.mode = "SLEEP MODE"
        self.process = None
        self.close_dispatching = False
        self.shutdown_requested = False
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=10, pady=(3, 2))
        self.status = tk.Label(bar, text=self.mode, font=("Segoe UI", 18, "bold"),
                               bg=BG, fg="#a5b4fc", anchor="w")
        self.status.pack(side="left")
        self.child_status = tk.Label(bar, text="[NORMAL]", font=("Segoe UI", 10, "bold"),
                                     bg=BG, fg="#fcd34d")
        self.child_status.pack(side="left", padx=6)
        self.detail = tk.Label(bar, text="Initialisation…", bg=BG, fg="#9ca3af",
                               font=("Segoe UI", 9))
        self.detail.pack(side="left", padx=8)
        tk.Button(bar, text="Logs", command=self.show_logs, bg="#263449", fg=FG,
                  relief="flat", padx=12).pack(side="right")
        transparency = tk.Scale(bar, from_=0, to=60, orient="horizontal", length=95,
                                label="Transparence %", bg=BG, fg=FG,
                                troughcolor="#263449", highlightthickness=0,
                                font=("Segoe UI", 8), command=self.set_transparency)
        transparency.pack(side="right", padx=6)
        value = max(0, min(60, int(self.display_settings["transparency_percent"])))
        transparency.set(value)
        self.root.attributes("-alpha", 1 - value / 100)
        self.command_frame = tk.LabelFrame(
            self.root, text=" Commandes vocales ", bg=BG, fg="#c7d2fe",
            font=("Segoe UI", 9, "bold"), padx=4, pady=2)
        self.command_frame.pack(side="bottom", fill="x", padx=8, pady=(0, 3))
        self.command_help = ScrolledText(
            self.command_frame, height=3, wrap="word", bg="#182233", fg="#dbeafe",
            font=("Segoe UI", 9), relief="flat", padx=5, pady=2, state="disabled")
        self.command_help.pack(fill="x")
        self.command_help.tag_configure("label", font=("Segoe UI", 9, "bold"),
                                        foreground="#f8fafc")
        self.command_help.configure(state="normal")
        self.command_help.insert("end", "Loading configured commands…")
        self.command_help.configure(state="disabled")
        self.chat = ScrolledText(self.root, wrap="word", bg=BG, fg=FG,
                                 font=("Yu Gothic UI", int(self.display_settings["message_font_size"]), "bold"), relief="flat",
                                 padx=8, pady=2, insertbackground=FG, state="disabled")
        self.chat.pack(fill="both", expand=True, padx=6, pady=(0, 2))
        self.chat.tag_configure("state", font=("Segoe UI", 10, "bold"), foreground="#c7d2fe")
        self.chat.tag_configure("stage", font=("Segoe UI", 10, "bold"), foreground="#93c5fd")
        self.chat.tag_configure("error", font=("Segoe UI", 10, "bold"),
                                foreground="#fecaca", background="#7f1d1d")
        self.chat.tag_configure("command", font=("Segoe UI", 10, "bold"),
                                foreground="#ffedd5", background="#9a3412")
        self.chat.tag_configure("user", background="#1f2937", lmargin1=8, lmargin2=8, rmargin=60,
                                spacing1=0, spacing3=0)
        self.chat.tag_configure("mio", background="#223954", lmargin1=60, lmargin2=60, rmargin=8,
                                spacing1=0, spacing3=0)
        self.chat.tag_configure("gap", font=("Segoe UI", 2), spacing1=0, spacing3=0)
        self.chat.tag_configure("message_text", foreground=self.display_settings["message_color"])
        self.logs = tk.Toplevel(self.root)
        if os.environ.get("MIO_BACKGROUND_START") == "1":
            self.logs.withdraw()
        self.logs.title("Mio — Logs")
        self.logs.geometry("1050x650")
        self.logs.configure(bg=BG)
        self.logs.protocol("WM_DELETE_WINDOW", self.logs.withdraw)
        tk.Label(self.logs, text="JOURNAL TECHNIQUE", bg=BG, fg=FG,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=14, pady=10)
        self.log_view = ScrolledText(self.logs, wrap="word", bg="#090e18", fg="#d1d5db",
                                     font=("Consolas", 10), state="disabled")
        self.log_view.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        if auto_start:
            self.root.after(100, self.start)
        self.root.after(75, self.pump)

    def set_transparency(self, value):
        percent = max(0, min(60, int(float(value))))
        self.root.attributes("-alpha", 1 - percent / 100)
        self.display_settings["transparency_percent"] = percent
        if self.opacity_save is not None:
            self.root.after_cancel(self.opacity_save)
        self.opacity_save = self.root.after(500, self.save_display_settings)

    def save_display_settings(self):
        self.opacity_save = None
        try:
            DISPLAY_CONFIG.write_text(json.dumps(self.display_settings, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
        except OSError as error:
            print(f"Chat settings could not be saved : {error}", file=sys.stderr)

    def show_logs(self):
        self.logs.deiconify()
        self.logs.attributes('-topmost', True)
        self.logs.lift()
        self.logs.after(250, lambda: self.logs.attributes('-topmost', False))

    def start(self):
        if self.shutdown_requested:
            return
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, MIO_UI_TOKEN=self.token, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "main_mistral.py")], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            threading.Thread(target=self.read_output, daemon=True, name="Mio-Chat-Logs").start()
            # Hide only the launcher console after the graphical windows exist.
            if os.name == "nt":
                kernel = ctypes.windll.kernel32
                kernel.GetConsoleWindow.restype = ctypes.c_void_p
                handle = kernel.GetConsoleWindow()
                if handle:
                    ctypes.windll.user32.ShowWindow(ctypes.c_void_p(handle), 0)
            self.root.lift()
        except Exception as exc:
            self.receive(dict(kind="error", key=uuid.uuid4().hex, text=f"Could not start : {exc}"))

    def read_output(self):
        process = self.process
        reader_token = self.token
        log = None
        try:
            try:
                log = LOG.open("a", encoding="utf-8", buffering=1)
            except OSError as exc:
                self.events.put(dict(kind='error', key=uuid.uuid4().hex,
                                     text=f'Écriture du journal indisponible : {exc}'))
            for line in process.stdout:
                if log is not None:
                    try:
                        log.write(line)
                    except OSError as exc:
                        log.close()
                        log = None
                        self.events.put(dict(kind='error', key=uuid.uuid4().hex,
                                             text=f'Écriture du journal interrompue : {exc}'))
                if line.startswith(PREFIX):
                    try:
                        event = json.loads(line[len(PREFIX):])
                        if isinstance(event, dict) and event.get("token") == reader_token:
                            self.events.put(event)
                            continue
                    except (ValueError, TypeError):
                        pass
                try:
                    self.log_lines.put_nowait(line)
                except queue.Full:
                    # Full diagnostics stay on disk; only the window is bounded.
                    pass
        except Exception as exc:
            self.events.put(dict(kind="error", key=uuid.uuid4().hex, text=f"Lecture du journal : {exc}"))
        finally:
            if log is not None:
                log.close()
            code = process.wait()
            self.events.put(dict(kind="exit", code=code, pid=process.pid))

    def receive(self, event):
        kind = event.get("kind")
        generation = event.get("generation", self.generation)
        if generation < self.generation:
            return
        if kind == "commands":
            self.command_help.configure(state="normal")
            self.command_help.delete("1.0", "end")
            for i, group in enumerate(event.get("groups", [])):
                if i:
                    self.command_help.insert("end", "\n")
                self.command_help.insert("end", group['label'] + " : ", "label")
                self.command_help.insert("end", " / ".join(group['phrases']) + " → " + group['action'])
            self.command_help.configure(state="disabled")
        elif kind == "state":
            if generation > self.generation:
                self.messages = OrderedDict((k, v) for k, v in self.messages.items()
                                            if v.get("stage") != "PRE TRAITEMENT")
                self.render()
            self.generation = generation
            self.mode = event["mode"]
            self.status.configure(text=self.mode, fg="#86efac" if self.mode == "ACTIVE MODE" else "#a5b4fc")
            label = {"Child": "[CHILD]", "Adult": "[ADULT]", "Normal": "[NORMAL]"}
            self.child_status.configure(text=label.get(event.get("family_mode"),
                                                       "[CHILD]" if event.get("child_mode") else "[NORMAL]"))
            if not self.shutdown_requested:
                self.detail.configure(text="" if event.get("ready") else "Initialisation…")
        elif kind == 'close_result':
            self.close_dispatching = False
            if event.get('error'):
                self.shutdown_requested = False
                self.receive(dict(kind='error', key=uuid.uuid4().hex, text=event['error']))
            else:
                self.detail.configure(text='Shutdown requested…')
        elif kind == 'remove':
            self.messages.pop(event['key'], None)
            self.render()
        elif kind in {"message", "error", "command"}:
            entry = dict(event)
            entry.setdefault("mode", self.mode)
            if kind == "error":
                entry['stage'] = 'ERROR'
                entry.setdefault('names', ['Mio'])
                entry.setdefault('mio', True)
            self.messages[event["key"]] = entry
            while len(self.messages) > 120:
                self.messages.popitem(last=False)
            self.render()
        elif kind == "exit":
            self.child_status.configure(text="")
            self.mode = "SLEEP MODE"
            self.status.configure(text=self.mode, fg="#a5b4fc")
            self.detail.configure(text="Mio stopped")
            if event["code"]:
                self.receive(dict(kind="error", key=uuid.uuid4().hex,
                                  text="Mio stopped. See Logs for details."))

    def render(self):
        selection = self.chat.tag_ranges('sel')
        selection = tuple(str(index) for index in selection)
        bottom = self.chat.yview()[1] >= .98
        position = self.chat.yview()[0]
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        for item in self.messages.values():
            side = "mio" if item.get("mio") else "user"
            self.chat.insert("end", f"[{item['mode']}]\n", (side, "state"))
            tag = ("error" if item["stage"] == "ERROR" else
                   "command" if item.get("kind") == "command" else "stage")
            self.chat.insert("end", f"[{item['stage']}]\n", (side, tag))
            # UI label only: never rewrite response text, speech or identities.
            names = " / ".join(item.get("names", [])) or "Speaker"
            self.chat.insert("end", f"{names} : ", (side,))
            self.chat.insert("end", f"{item.get('text', '')}\n", (side, "message_text"))
            self.chat.insert("end", "\n\n", "gap")  # Two short empty lines between blocks.
        if selection:
            self.chat.tag_add("sel", *selection)
        self.chat.tag_raise("sel")
        self.chat.configure(state="disabled")
        if bottom and not selection:
            self.chat.see("end")
        else:
            self.chat.yview_moveto(position)

    def pump(self):
        for _ in range(100):
            try:
                self.receive(self.events.get_nowait())
            except queue.Empty:
                break
            if not self.root.winfo_exists():
                return
        batch = []
        for _ in range(200):
            try:
                batch.append(self.log_lines.get_nowait())
            except queue.Empty:
                break
        if batch:
            bottom = self.log_view.yview()[1] >= .98
            self.log_view.configure(state="normal")
            self.log_view.insert("end", "".join(batch))
            excess = int(self.log_view.index("end-1c").split(".")[0]) - 2000
            if excess > 0:
                self.log_view.delete("1.0", f"{excess + 1}.0")
            self.log_view.configure(state="disabled")
            if bottom:
                self.log_view.see("end")
        self.root.after(75, self.pump)

    def close(self):
        if self.close_dispatching:
            return
        self.close_dispatching = True
        self.shutdown_requested = True
        self.detail.configure(text='Ouverture du lanceur de fermeture…')
        threading.Thread(target=self.launch_shutdown, daemon=True,
                         name='Mio-Chat-Fermeture').start()

    def launch_shutdown(self):
        try:
            script = ROOT.parent / 'Close_All_AI_Waifu.bat'
            if not script.is_file():
                raise FileNotFoundError(str(script))
            # Ask for elevation from the interactive chat window. WMI starts the
            # BAT without an interactive desktop, so its own UAC prompt fails.
            result = ctypes.windll.shell32.ShellExecuteW(
                None, 'runas', 'cmd.exe', f'/d /c ""{script}""', str(ROOT.parent), 1)
            if result <= 32:
                raise RuntimeError(f'Administrator launch failed (code {result}) ; '
                                   'utilise le raccourci Fermer Mio.')
            self.events.put(dict(kind='close_result'))
        except Exception as exc:
            self.events.put(dict(kind='close_result', error=f'Shutdown could not start : {exc}'))


if __name__ == "__main__":
    ChatWindow().root.mainloop()
