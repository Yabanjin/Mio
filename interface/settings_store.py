"""Configuration files used by the application, edited in place and atomically."""
import json
import math
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent.parent
APPLICATION = ROOT / 'settings' / 'interface.json'
LOCAL_APPLICATION = ROOT / 'settings' / 'interface.local.json'


def read(path):
    path = Path(path)
    if path.resolve() == APPLICATION.resolve() and LOCAL_APPLICATION.is_file():
        path = LOCAL_APPLICATION
    text = path.read_text(encoding='utf-8-sig')
    return json.loads(text) if Path(path).suffix == '.json' else text


def validate(value, template, location=''):
    """Preserve required keys and scalar types; allow optional keys and list edits."""
    if isinstance(template, dict):
        if not isinstance(value, dict):
            raise ValueError(f'{location}: object expected')
        for key, old in template.items():
            if key not in value:
                raise ValueError(f'{location}.{key}: required field')
            validate(value[key], old, f'{location}.{key}')
    elif isinstance(template, list):
        if not isinstance(value, list):
            raise ValueError(f'{location}: list expected')
        if template:
            for i, item in enumerate(value):
                validate(item, template[0], f'{location}[{i}]')
    elif template is not None:
        expected = type(template)
        valid = type(value) is expected
        if expected is float:
            valid = type(value) in (float, int)
        if not valid or (type(value) is float and not math.isfinite(value)):
            raise ValueError(f'{location}: expected a value of type {expected.__name__}')


def write(path, value):
    path = Path(path).resolve()
    if path == APPLICATION.resolve():
        path = LOCAL_APPLICATION.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('File outside the project')
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) if path.suffix == '.json' else value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False, suffix='.tmp') as handle:
            temporary = handle.name
            handle.write(content.rstrip() + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


LABELS = {
    'MemoireVectorielle': 'Vector memory', 'Rewrite': 'Reply rewriting',
    'Common': 'Common', 'Normal': 'Normal', 'Child': 'Child', 'Adult': 'Adult',
    'annulation_mode': 'Mode cancellation', 'arrivee_enfant': 'Child greeting',
    'arrivee_femme': 'Adult greeting', 'bienvenue': 'Welcome', 'erreur': 'Error',
    'phrases': 'Phrases', 'reponse': 'Reply', 'pause': 'Sleep', 'stop': 'Stop',
    'couper_la_parole': 'Interrupt speech', 'fin_mode_enfant': 'Exit Child mode',
    'interrompre_mode_femme': 'Exit Adult mode', 'mise_en_sommeil': 'Sleep',
    'mots_a_retirer': 'Words to remove', 'wake_up': 'Wake up',
    'conditions_prompt': 'Mode selection', 'contexte_reconnaissance': 'Recognition context',
    'fonctionnement': 'Runtime', 'horloge': 'Clock', 'interface_chat': 'Chat appearance',
    'langues_reponse': 'Response languages', 'llm_generation': 'LLM generation',
    'memoire_vectorielle': 'Vector memory', 'peripheriques_audio': 'Audio devices',
    'unites_japonaises': 'Japanese units', 'connexion': 'Connections',
    'prononciation': 'Pronunciation', 'famille_connue': 'Known people',
    'identite_mio': 'Mio identity', 'vitesse': 'Speed', 'voix': 'Voice',
    'seuils': 'Thresholds', 'femme_block_seconds': 'Adult mode block seconds',
}


def display_label(value):
    """English presentation labels; existing file and protocol IDs stay stable."""
    text = str(value)
    return LABELS.get(text, text.replace('_', ' ').capitalize())


def catalog():
    main = ROOT / 'src' / 'MainApp'
    entries = [('Installation and startup', APPLICATION)]
    entries.append(('LLM model and GPU', ROOT / 'src/LM Studio/mio-load.json'))
    prompts = {'Common': 'Identity and personality', 'Normal': 'Normal mode',
               'Child': 'Child mode', 'Adult': 'Adult mode', 'Rewrite': 'Reply rewriting'}
    for name, title in prompts.items():
        entries.append((f'Prompts / {title}', main / 'prompt' / f'{name}.txt'))
    groups = [('Automatic replies', main / 'reponse_auto', '*.json'),
              ('Voice commands', main / 'trigger', '*.txt'),
              ('Chat settings', main / 'config', '*.json')]
    for label, folder, pattern in groups:
        for path in sorted(folder.rglob(pattern)):
            title = ' / '.join(display_label(part) for part in path.relative_to(folder).with_suffix('').parts)
            entries.append((f'{label} / {title}', path))
    for folder in ('MemoireVectorielle', 'Speechbrain', 'SileroVAD', 'VoskServer',
                   'PiperTTS', 'MeloTTS', 'Whisper Turbo'):
        base = ROOT / 'src' / folder
        for path in sorted(base.glob('*.json')) + sorted((base / 'config').glob('*.json')):
            entries.append((f'{display_label(folder)} / {display_label(path.stem)}', path))
    entries.append(('Memory / Extraction prompt', ROOT / 'src/MemoireVectorielle/extraction_prompt.txt'))
    return entries
