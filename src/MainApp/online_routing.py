"""Provider commands and state for the live dialogue engine.

No network calls or service lifecycle operations. The engine integration must
use its existing generation cancellation before switching and on every Stop.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import re
import threading
import unicodedata

LABELS = {'local': 'MIO LOCAL', 'gpt': 'GPT MODE', 'gemini': 'GEMINI MODE'}


def normalize(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^\w\s]', ' ', text).split())


def validate_routing(config, local_wake_phrases=()):
    """Reject ambiguous commands; the local list belongs to existing Mio settings."""
    seen = {normalize(p) for p in local_wake_phrases}
    local_switches = config.get('local_switch_phrases', [])
    if not isinstance(local_switches, list) or any(not isinstance(p, str) or not normalize(p) for p in local_switches):
        raise ValueError('local_switch_phrases: enter nonempty commands')
    seen.update(normalize(p) for p in local_switches)
    for key in ('gpt_wake_phrases', 'gemini_wake_phrases'):
        phrases = config.get(key)
        if not isinstance(phrases, list) or not phrases:
            raise ValueError(f'{key}: enter at least one command')
        for phrase in phrases:
            if not isinstance(phrase, str) or not normalize(phrase):
                raise ValueError(f'{key}: commands must be nonempty text')
            word = normalize(phrase)
            if word in seen:
                raise ValueError('Wake commands must be distinct across providers')
            seen.add(word)


def validate_provider(config):
    if type(config.get('enabled')) is not bool:
        raise ValueError('Enabled must be on or off')
    if config.get('tts_source') not in ('local', 'provider'):
        raise ValueError('Choose local Mio speech or provider API speech')
    for key in ('llm_model', 'tts_model', 'tts_voice', 'api_key_environment', 'provider_instruction'):
        if not isinstance(config.get(key), str):
            raise ValueError(f'{key}: text expected')
    if not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,63}', config['api_key_environment']):
        raise ValueError('Enter an environment variable name, never an API key')
    if type(config.get('web_search')) is not bool:
        raise ValueError('Web search must be enabled or disabled')
    if not config['provider_instruction'].strip():
        raise ValueError('Provider instruction cannot be empty')


@dataclass(frozen=True)
class Turn:
    provider: str
    revision: int


class ProviderRouting:
    def __init__(self, root, local_wake_phrases, reserved_phrases=()):
        path = Path(root) / 'settings/online/routing.json'
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        local = tuple(local_wake_phrases)
        validate_routing(config, (*local, *reserved_phrases))
        self.commands = {normalize(p): 'local' for p in local}
        self.switch_commands = {normalize(p) for p in config.get('local_switch_phrases', [])}
        self.commands.update({p: 'local' for p in self.switch_commands})
        for provider in ('gpt', 'gemini'):
            self.commands.update({normalize(p): provider
                                  for p in config[provider + '_wake_phrases']})
        self._provider = 'local'
        self._revision = 0
        self._lock = threading.Lock()

    def command(self, text):
        # Exact utterance matching avoids switching when discussing a command.
        return self.commands.get(normalize(text))

    def switch(self, provider):
        if provider not in LABELS:
            raise ValueError('Unknown provider')
        with self._lock:
            self._revision += 1
            self._provider = provider
            return Turn(provider, self._revision)

    def stop(self):
        """Invalidate pending output without changing the selected provider.

        Caller must also stop playback and purge queues through the existing
        engine cancellation path. This token alone does not abort HTTP or audio.
        """
        with self._lock:
            self._revision += 1

    def begin_turn(self):
        with self._lock:
            return Turn(self._provider, self._revision)

    def current(self, turn):
        with self._lock:
            return turn == Turn(self._provider, self._revision)

    def status(self):
        with self._lock:
            return LABELS[self._provider]
