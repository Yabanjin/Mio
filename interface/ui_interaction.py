"""Clipboard menus and pointer-targeted scrolling for Tk widgets."""
import tkinter as tk
import ctypes
import logging
import os


def _windows_copy(text, owner):
    """Transfer real Unicode storage to Windows, without delayed Tk rendering."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.OpenClipboard.argtypes = [ctypes.c_void_p]
    user.OpenClipboard.restype = ctypes.c_int
    user.EmptyClipboard.restype = ctypes.c_int
    user.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user.SetClipboardData.restype = ctypes.c_void_p
    user.CloseClipboard.restype = ctypes.c_int
    kernel.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = ctypes.c_void_p
    kernel.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel.GlobalFree.restype = ctypes.c_void_p
    data = (text.replace('\r\n', '\n').replace('\n', '\r\n') + '\0').encode('utf-16-le')
    handle = kernel.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    opened = False
    try:
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel.GlobalUnlock(handle)
        if not user.OpenClipboard(owner):
            raise ctypes.WinError(ctypes.get_last_error())
        opened = True
        if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):  # CF_UNICODETEXT
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None  # Windows now owns this storage, including after Mio exits.
    finally:
        if opened:
            user.CloseClipboard()
        if handle:
            kernel.GlobalFree(handle)


def copy_text(widget, text, attempt=0):
    try:
        if os.name == 'nt':
            _windows_copy(text, widget.winfo_id())
        else:
            widget.clipboard_clear()
            widget.clipboard_append(text)
            widget.update_idletasks()
    except OSError as error:
        # Another program can briefly lock the clipboard. Retry only this copy.
        if attempt < 5:
            widget.after(60, lambda: copy_text(widget, text, attempt + 1))
        else:
            widget.bell()
            logging.warning('Could not copy to the Windows clipboard: %s', error)

def install(root):
    def wheel(event):
        widget = root.winfo_containing(event.x_root, event.y_root)
        step = (-1 if event.delta > 0 else 1) if event.delta else (-1 if event.num == 4 else 1)
        amount = max(1, abs(int(event.delta / 120))) if event.delta else 1
        while widget:
            if isinstance(widget, (tk.Text, tk.Listbox, tk.Canvas)):
                first, last = widget.yview()
                if last - first < .999:
                    widget.yview_scroll(step * amount * 3, 'units')
                    return 'break'
            widget = getattr(widget, 'master', None)
        return 'break'
    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
        root.bind_class('MioWheel', sequence, wheel)

def attach(widget):
    if 'MioWheel' not in widget.bindtags():
        widget.bindtags(('MioWheel',) + widget.bindtags())
    if isinstance(widget, (tk.Text, tk.Entry)) and not getattr(widget, '_mio_clipboard', False):
        widget._mio_clipboard = True
        if isinstance(widget, tk.Text):
            widget.configure(exportselection=False, takefocus=True,
                             selectbackground='#655781', selectforeground='#ffffff',
                             inactiveselectbackground='#655781')
            widget.tag_raise('sel')
        # Disabled Text widgets otherwise leave keyboard focus in the input box.
        widget.bind('<Button-1>', lambda event: widget.focus_set(), add='+')
        def select_all(event=None):
            widget.focus_set()
            if isinstance(widget, tk.Text):
                widget.tag_add('sel', '1.0', 'end-1c')
            else:
                widget.selection_range(0, 'end')
            return 'break'
        def copy(event=None):
            try:
                text = (widget.get('sel.first', 'sel.last') if isinstance(widget, tk.Text)
                        else widget.get()[widget.index('sel.first'):widget.index('sel.last')])
                copy_text(widget, text)
            except tk.TclError:
                pass
            return 'break'
        widget.bind('<Control-a>', select_all)
        widget.bind('<Control-c>', copy)
        widget.bind('<<Copy>>', copy)
        widget.bind('<<SelectAll>>', select_all)
        popup = tk.Menu(widget, tearoff=False)
        def menu(event):
            widget.focus_set()
            popup.delete(0, 'end')
            popup.add_command(label='Copy', command=copy)
            if str(widget.cget('state')) != 'disabled':
                popup.add_command(label='Paste', command=lambda: widget.event_generate('<<Paste>>'))
                popup.add_command(label='Cut', command=lambda: widget.event_generate('<<Cut>>'))
            popup.add_command(label='Select all', command=select_all)
            try:
                popup.tk_popup(event.x_root, event.y_root)
            finally:
                popup.grab_release()
            return 'break'
        widget.bind('<Button-3>', menu)
    for child in widget.winfo_children():
        attach(child)
