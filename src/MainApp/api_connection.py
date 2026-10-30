"""Read-only provider/model connection checks. Never generate text or audio."""
import os
import re

import requests
from online_credentials import read_key


def check_connection(provider, config, cancelled=None):
    """Return safe per-model results; never expose credentials or response bodies.

    Model metadata access does not establish generation quota, billing eligibility,
    speech/voice compatibility, web search access or the local RVC audio route.
    Disabled providers can be checked without enabling them.
    """
    if provider not in ('gpt', 'gemini'):
        raise ValueError('Unknown online provider.')
    if config.get('tts_source') not in ('local', 'provider'):
        raise ValueError('Choose local Mio voice or provider API voice first.')
    selected = [('Reply model', config.get('llm_model', ''))]
    if config['tts_source'] == 'provider':
        selected.append(('Speech model', config.get('tts_model', '')))
    models = []
    for role, value in selected:
        model = value.strip() if isinstance(value, str) else ''
        if provider == 'gemini' and model.startswith('models/'):
            model = model[7:]
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,199}', model):
            raise ValueError(f'{role}: enter a valid model API ID, not a URL.')
        models.append((role, model))
    env = config.get('api_key_environment', '')
    if not isinstance(env, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,63}', env):
        raise ValueError('Enter a valid API key environment variable name.')
    try:
        key = read_key(provider) or os.environ.get(env, '').strip()
    except (OSError, UnicodeError):
        raise ValueError('Windows could not read the saved API key.') from None
    if not key:
        raise ValueError('No API key found. Save your key locally before testing.')
    headers = ({'Authorization': 'Bearer ' + key} if provider == 'gpt'
               else {'x-goog-api-key': key})
    base = ('https://api.openai.com/v1/models/' if provider == 'gpt'
            else 'https://generativelanguage.googleapis.com/v1beta/models/')
    errors = {
        400: 'Request rejected. Check the API key and model API ID.',
        401: 'Authentication failed. Check or replace the saved API key.',
        403: 'Access denied. Check key restrictions and model permissions.',
        404: 'Model not found or unavailable to this API key. Check its API ID.',
        429: 'Rate limit or quota reached. Check the provider dashboard before retrying.',
    }
    checks = []
    for role, model in models:
        if cancelled is not None and cancelled.is_set():
            return {'ok': False, 'checks': checks, 'cancelled': True}
        try:
            with requests.get(base + model, headers=headers, timeout=(5, 15),
                              allow_redirects=False) as response:
                code = response.status_code
                if code != 200:
                    ok = False
                    message = f'HTTP {code}: ' + errors.get(
                        code, 'Provider request failed. Check its status and try again later.')
                else:
                    data = response.json()
                    field = 'id' if provider == 'gpt' else 'name'
                    ok = isinstance(data, dict) and isinstance(data.get(field), str) and bool(data[field])
                    message = ('Accessible (model metadata).' if ok
                               else 'Unexpected provider response; connection not confirmed.')
        except requests.RequestException:
            ok, message = False, 'Connection failed or timed out. Check your network and provider status.'
        except ValueError:
            ok, message = False, 'Invalid provider response; connection not confirmed.'
        checks.append({'role': role, 'model': model, 'ok': ok, 'message': message})
    return {'ok': all(check['ok'] for check in checks), 'checks': checks, 'cancelled': False}
