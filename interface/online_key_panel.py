"""Explicit local credential editing; no network calls."""
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox
from online_credentials import save_key, read_key, delete_key


def add_key_panel(parent, provider):
    frame = ttk.LabelFrame(parent, text='API key — Windows Credential Manager', padding=8)
    frame.pack(fill='x', pady=8)
    secret = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=secret, show='•')
    entry.pack(fill='x')
    saved = False
    showing_saved = False
    mask = '************'
    status = ttk.Label(frame, wraplength=500)
    status.pack(fill='x')
    def refresh():
        nonlocal saved, showing_saved
        try:
            saved = bool(read_key(provider))
            showing_saved = saved
            secret.set(mask if saved else '')
            status.configure(text='Saved key available. Type to replace it.' if saved else
                             'No saved key. An environment variable may also supply the key.')
        except OSError as error:
            status.configure(text=str(error))
    def change(remove=False):
        try:
            if remove:
                delete_key(provider)
            else:
                if saved and (showing_saved or not secret.get().strip()):
                    status.configure(text='Saved key unchanged.')
                    return
                if secret.get() == mask:
                    raise ValueError('Enter the actual new key to replace the saved key.')
                save_key(provider, secret.get())
            secret.set('')
            refresh()
        except (ValueError, OSError) as error:
            messagebox.showerror('API key', str(error), parent=parent)
    def start_edit(_event=None):
        nonlocal showing_saved
        if showing_saved:
            secret.set('')
            showing_saved = False
    def finish_edit(_event=None):
        nonlocal showing_saved
        if saved and not secret.get():
            secret.set(mask)
            showing_saved = True
    entry.bind('<FocusIn>', start_edit)
    entry.bind('<FocusOut>', finish_edit)
    buttons = ttk.Frame(frame)
    buttons.pack(fill='x')
    ttk.Button(buttons, text='Save key locally', command=change).pack(side='left')
    ttk.Button(buttons, text='Remove saved key', command=lambda: change(True)).pack(side='left', padx=8)
    url = ('https://aistudio.google.com/api-keys' if provider == 'gemini'
           else 'https://platform.openai.com/api-keys')
    ttk.Button(frame, text='Open provider API key page', command=lambda: webbrowser.open(url)).pack(anchor='w', pady=4)
    ttk.Label(frame, text='Key buttons apply immediately, separately from page Save. '
              'Dots indicate a saved key; leave them unchanged to keep it. '
              'Keys are never displayed again or saved in project files. '
              'Online requests may incur provider charges.', wraplength=500).pack(fill='x', pady=4)
    refresh()
