"""Registered authors for explicitly attributed chat input."""
import json
from pathlib import Path

PROFILE_FILE = Path(__file__).resolve().parent.parent / 'Speechbrain/profiles.json'


def registered_authors():
    data = json.loads(PROFILE_FILE.read_text(encoding='utf-8-sig'))
    authors = []
    seen = set()
    for profile in data.get('profiles', []):
        name = str(profile.get('name') or '').strip()
        role = str(profile.get('role') or '').casefold()
        if not name or name.casefold() in seen or role == 'assistant' or not profile.get('authorized', True):
            continue
        seen.add(name.casefold())
        authors.append({'name': name, 'role': profile.get('role'), 'prompt': profile.get('prompt')})
    return authors


def author_identity(name):
    for author in registered_authors():
        if author['name'] == name:
            return {'names': [author['name']], 'role': author['role'],
                    'prompt': author['prompt'], 'source': 'text'}
    raise ValueError('Choose a registered author before sending a message.')
