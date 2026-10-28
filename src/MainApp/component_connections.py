"""Service endpoints shared by the desktop editor and dialogue engine."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent.parent

def load_connections():
    result = {}
    for path in (ROOT / 'settings/components').glob('*.json'):
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        for key, item in value.items():
            if key == 'url' or key.endswith('_url'):
                parsed = urlsplit(item)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError(f'{path.stem}: {key} must be an HTTP(S) URL without embedded credentials')
        result[path.stem] = value
    return result
