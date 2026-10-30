"""Settings pages and editable projections of existing files; no duplicate settings."""
from pathlib import Path

SECTIONS = ('Mio — Main settings', 'Mio — Modules', 'Microphone', 'Online — Commands', 'Online — GPT', 'Online — Gemini', 'Mio — Texts', 'Mio — Timings',
            'Language model', 'Whisper transcription', 'Piper voice', 'Melo voices',
            'Voice changer', 'Agent DVR camera', 'CodeProject.AI faces',
            'SpeechBrain recognition', 'Vosk keywords', 'Silero VAD', 'WebRTC echo cancellation',
            'Vector memory', 'MicroBoost', 'Startup')
VIEWS = {}

def catalog(root, section, application):
    source_root = root / 'src'
    main = source_root / 'MainApp'
    entries = []
    def file(label, relative):
        path = (root if relative.startswith('settings/') else source_root) / relative
        if path.is_file():
            entries.append((label, path))
    def view(label, slug, sources):
        path = root / 'settings/.views' / (slug + '.json')
        VIEWS[path.resolve()] = [(label, (root if source.startswith('settings/') else source_root) / source, predicate) for label, source, predicate in sources]
        entries.append((label, path))
    def launch(name):
        index = {'llm': 0, 'camera': 1, 'face_recognition': 2, 'voice_changer': 3}.get(name)
        if index is not None:
            view('Program launch', 'launch-' + name,
                 [('Program', 'settings/interface.json', ('external_services', index))])
    def configs(folder):
        base = source_root / folder
        for path in sorted(base.glob('*.json')) + sorted((base / 'config').glob('*.json')):
            if any(word in path.name.lower() for word in ('ready', 'status', 'cache')):
                continue
            entries.append((path.stem.replace('_', ' ').capitalize(), path))
    timing = lambda key: key.endswith(('_seconds', '_ms')) or key == 'face_context_confirm_seconds'
    def microphone():
        view('Microphone connection and level', 'microphone-setup', [
            ('Audio', 'MainApp/config/peripheriques_audio.json', lambda k: True),
            ('MicroBoost', 'settings/interface.json', ('startup_tools', 0))])
    if section == SECTIONS[0]:
        file('Chat appearance', 'MainApp/config/interface_chat.json')
        microphone()
        file('Audio output and recognition', 'MainApp/config/connexion.json')
        file('Pronunciation', 'MainApp/config/prononciation.json')
        view('Language controls', 'language-controls', [('Languages', 'MainApp/config/langues_reponse.json', lambda k: k in ('temperature', 'min_detection_letters', 'min_rejection_confidence', 'short_detection_letters'))])
        view('Clock enabled', 'clock-enabled', [('Clock', 'MainApp/config/horloge.json', lambda k: k != 'instruction')])
        view('Detection and buffers', 'main-runtime', [('Runtime', 'MainApp/config/fonctionnement.json', lambda k: not timing(k))])
        view('Mode selection', 'main-modes', [('Modes', 'MainApp/config/conditions_prompt.json', lambda k: not timing(k))])
    elif section == 'Microphone':
        microphone()
    elif section == 'Mio — Modules':
        file('Enabled modules', 'settings/modules.json')
    elif section.startswith('Online —'):
        provider = {'Online — Commands': 'routing', 'Online — GPT': 'gpt', 'Online — Gemini': 'gemini'}[section]
        file('Provider settings', 'settings/online/' + provider + '.json')
    elif section == 'Mio — Texts':
        for path in sorted((main / 'prompt').glob('*.txt')):
            entries.append(('Prompt / ' + path.stem, path))
        for path in sorted((main / 'reponse_auto').rglob('*.json')):
            entries.append(('Automatic reply / ' + path.parent.name, path))
        view('Response language text', 'language-text', [('Languages', 'MainApp/config/langues_reponse.json', lambda k: k not in ('temperature', 'min_detection_letters', 'min_rejection_confidence', 'short_detection_letters'))])
        view('Clock wording', 'clock-text', [('Clock', 'MainApp/config/horloge.json', lambda k: k == 'instruction')])
        view('Recognition wording', 'main-recognition', [('Context', 'MainApp/config/contexte_reconnaissance.json', lambda k: not timing(k))])
        file('Japanese units', 'MainApp/config/unites_japonaises.json')
    elif section == 'Mio — Timings':
        view('Mio timing settings', 'main-timings', [(name, 'MainApp/config/' + name + '.json', timing)
             for name in ('fonctionnement', 'conditions_prompt', 'contexte_reconnaissance')])
    elif section == 'Startup':
        entries.append(('Interface runtime', application))

    elif section == 'Language model':
        file('Connection and model', 'settings/components/llm.json')
        file('Generation', 'MainApp/config/llm_generation.json')
        file('Local model loading', 'LM Studio/mio-load.json')
        launch('llm')
    elif section in ('Whisper transcription', 'Piper voice', 'Melo voices'):
        folder, component = {'Whisper transcription': ('Whisper Turbo', 'transcription'),
            'Piper voice': ('PiperTTS', 'french_voice'), 'Melo voices': ('MeloTTS', 'multilingual_voice')}[section]
        file('Connection', f'settings/components/{component}.json')
        configs(folder)
        launch(component)
    elif section in ('Agent DVR camera', 'CodeProject.AI faces'):
        camera = section == 'Agent DVR camera'
        key = 'snapshot_url' if camera else 'recognition_url'
        view('Connection', 'camera' if camera else 'face', [('Endpoint', 'settings/components/camera.json', lambda k: k == key)])
        launch('camera' if camera else 'face_recognition')
    elif section == 'Voice changer':
        file('Connection', 'settings/components/voice_changer.json')
        launch('voice_changer')
    elif section == 'MicroBoost':
        view('Microphone utility', 'microphone-utility',
             [('Program', 'settings/interface.json', ('startup_tools', 0))])
    elif section == 'Vector memory':
        file('Mio memory client', 'MainApp/config/memoire_vectorielle.json')
        configs('MemoireVectorielle')
        file('Extraction instructions', 'MemoireVectorielle/extraction_prompt.txt')
        launch('vector_memory')
    else:
        folder = {'SpeechBrain recognition': 'Speechbrain', 'Vosk keywords': 'VoskServer',
                  'Silero VAD': 'SileroVAD', 'WebRTC echo cancellation': 'WebRTC'}[section]
        configs(folder)
        if folder == 'VoskServer':
            for path in sorted((main / 'trigger').rglob('*.txt')):
                entries.append(('Command / ' + str(path.relative_to(main / 'trigger')), path))
    return entries

def projected_read(path, read):
    result = {}
    for label, source, selector in VIEWS[path.resolve()]:
        data = read(source)
        if isinstance(selector, tuple):
            for key in selector:
                data = data[key]
            result[label] = data
        else:
            result[label] = {key: value for key, value in data.items() if selector(key)}
    return result

def projected_write(path, value, read, write):
    for label, source, selector in VIEWS[path.resolve()]:
        data = read(source)
        if isinstance(selector, tuple):
            target = data
            for key in selector[:-1]:
                target = target[key]
            target[selector[-1]] = value[label]
        else:
            allowed = {key for key in data if selector(key)}
            if set(value[label]) != allowed:
                raise ValueError('Keep the existing fields in this settings page.')
            data.update(value[label])
        write(source, data)
