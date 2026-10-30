"""Feature choices shared by the engine, settings and launchers."""
import json
from pathlib import Path
import sys

DEFAULTS = dict(voice_input=True, speaker_recognition=False, face_recognition=False,
                speech_output=True, voice_changer=False, vector_memory=True)


def validate_modules(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Module settings must contain the six supported feature switches')
    if any(type(v) is not bool for v in value.values()):
        raise ValueError('Module switches must be on or off')


def load_modules(root):
    path = Path(root) / 'settings/modules.json'
    value = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else dict(DEFAULTS)
    validate_modules(value)
    return value


def needs_component(modules, name):
    if name in ('transcription', 'microphone_utility'):
        return modules['voice_input']
    if name in ('camera', 'face_recognition'):
        return modules['face_recognition']
    if name in ('french_voice', 'multilingual_voice'):
        return modules['speech_output']
    if name == 'voice_changer':
        return modules['speech_output'] and modules['voice_changer']
    if name == 'vector_memory':
        return modules['vector_memory']
    return True  # The local LLM remains the base dialogue provider.


class NoSpeakerRecognition:
    process = None

    def identify(self, audio):
        return {'speakers': []}

    def warm_up(self):
        pass

    def close(self):
        pass


if __name__ == '__main__' and sys.argv[1:] == ['--batch']:
    values = load_modules(Path(__file__).resolve().parent.parent)
    for key, value in values.items():
        print('MIO_FEATURE_' + key.upper() + '=' + str(int(value)))
    print('MIO_FEATURE_READY=1')
