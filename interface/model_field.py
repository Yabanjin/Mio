"""Visible model-ID hints which never become saved configuration values."""


def model_hint(provider, key):
    examples = {
        'gpt': {'llm_model': 'gpt-6-astra', 'tts_model': 'gpt-4o-mini-tts', 'tts_voice': 'coral'},
        'gemini': {'llm_model': 'gemini-3.1-flash-lite', 'tts_model': 'gemini-3.8-flash-tts', 'tts_voice': 'Kore'},
    }
    example = examples.get(provider, {}).get(key)
    if not example:
        return ''
    purpose = {'llm_model': 'reply model API ID', 'tts_model': 'speech model API ID',
               'tts_voice': 'API voice name'}[key]
    return f'Enter the {purpose}. Example: {example}\nUse an ID available to your API account.'


def install_hint(widget, hint):
    showing = False
    foreground = widget.cget('foreground')
    def show(_event=None):
        nonlocal showing
        if not widget.get('1.0', 'end-1c'):
            widget.insert('1.0', hint)
            widget.configure(foreground='#64748b')
            showing = True
    def hide(_event=None):
        nonlocal showing
        if showing:
            widget.delete('1.0', 'end')
            widget.configure(foreground=foreground)
            showing = False
    def value():
        return '' if showing else widget.get('1.0', 'end-1c')
    widget.bind('<FocusIn>', hide, add='+')
    widget.bind('<FocusOut>', show, add='+')
    show()
    return value
