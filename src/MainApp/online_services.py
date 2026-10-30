"""Explicit online text/search and WAV speech requests with bounded timeouts.

The caller supplies only the dedicated provider prompt and response language.
Only supplied conversation text is sent. No local memories, camera data or
microphone recordings are read by this module. No automatic paid retries.
"""
import base64
import io
import json
import os
import re
import wave
from pathlib import Path
from urllib.parse import urlsplit
import requests
from online_credentials import read_key
from online_routing import validate_provider

GOOGLE = 'https://generativelanguage.googleapis.com/v1beta/interactions'
OPENAI = 'https://api.openai.com/v1/'


class ProviderRequestError(ValueError):
    """Sanitized request failure for diagnostics; the chat uses a generic reply."""


def spoken_text(text):
    """Citation markers/URLs stay in the chat, not in the spoken narration."""
    text = re.sub(r'\ue200.*?\ue201', '', text, flags=re.DOTALL)
    text = re.sub(r'\[([^\]]+)\]\(https?://[^\s)]+\)', r'\1', text)
    text = re.sub(r'\[\d+\]', '', text)
    return re.sub(r'https?://\S+', '', text).strip()


def configuration(root, provider, speech_output=True):
    if provider not in ('gpt', 'gemini'):
        raise ValueError('Unknown online provider')
    value = json.loads((Path(root) / 'settings/online' / (provider + '.json')).read_text(encoding='utf-8-sig'))
    validate_provider(value)
    if not value['enabled']:
        raise ValueError('This online provider is disabled. Enable it in Customize or Services first.')
    remote_speech = speech_output and value['tts_source'] == 'provider'
    required = ('llm_model', 'tts_model', 'tts_voice') if remote_speech else ('llm_model',)
    if not all(value[k].strip() for k in required):
        raise ValueError('Enter the reply model API ID in Customize. API speech also needs its speech model ID and voice name.')
    if not credential(provider, value):
        raise ValueError('Save an API key in Customize or set its environment variable first.')
    return value


def credential(provider, config):
    return read_key(provider) or os.environ.get(config['api_key_environment'], '').strip()


def post(provider, config, url, payload, audio=False):
    key = credential(provider, config)
    if not key:
        raise ValueError('Missing API key. Configure this provider in Customize.')
    headers = {'Authorization': 'Bearer ' + key} if provider == 'gpt' else {'x-goog-api-key': key}
    try:
        with requests.post(url, json=payload, headers=headers, timeout=(10, 90),
                           allow_redirects=False) as response:
            if response.status_code != 200:
                # Never expose response bodies, request headers or credentials in logs.
                advice = {401: 'Check the saved API key.', 403: 'Check API access permissions.',
                          404: 'Check the model ID and its availability.',
                          429: 'Provider quota or rate limit reached. Try later.'}.get(
                              response.status_code, 'Provider request failed. Try later or check model access.')
                raise ProviderRequestError(f'{provider.upper()} request failed (HTTP {response.status_code}). ' + advice)
            if audio:
                return response.content
            try:
                return response.json()
            except ValueError:
                raise ProviderRequestError(f'{provider.upper()} returned an invalid JSON response.') from None
    except requests.Timeout:
        raise ProviderRequestError(f'{provider.upper()} request timed out (connection limit 10s, response limit 90s). '
                         'Try again or select another available model.') from None
    except requests.RequestException:
        raise ProviderRequestError(f'{provider.upper()} network connection failed. Check connectivity.') from None


def sources_for(parts):
    sources = []
    seen = set()
    for part in parts:
        for annotation in part.get('annotations', []):
            url = annotation.get('url', '')
            if not isinstance(url, str):
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if (annotation.get('type') == 'url_citation' and parsed.scheme in ('https', 'http')
                    and parsed.hostname and not parsed.username and not parsed.password and url not in seen):
                seen.add(url)
                sources.append({'url': url, 'title': annotation.get('title') or parsed.hostname})
    return sources


def model_parts(result):
    return [part for step in result.get('steps', []) if step.get('type') == 'model_output'
            for part in step.get('content', [])]


def cited_text(parts, sources, provider):
    """Attach stable source numbers before name normalization changes indices."""
    numbers = {source['url']: index + 1 for index, source in enumerate(sources)}
    texts = []
    for part in parts:
        text = part.get('text', '')
        inserts = {}
        for annotation in part.get('annotations', []):
            number = numbers.get(annotation.get('url'))
            end = annotation.get('end_index')
            if not number or type(end) is not int or end < 0:
                continue
            if provider == 'gemini':
                end = len(text.encode('utf-8')[:end].decode('utf-8', errors='ignore'))
            if end <= len(text):
                inserts.setdefault(end, set()).add(number)
        for end in sorted(inserts, reverse=True):
            marker = ''.join(f'[{n}]' for n in sorted(inserts[end]))
            text = text[:end] + marker + text[end:]
        # OpenAI's private citation glyphs are replaced by the source numbers.
        texts.append(re.sub(r'\ue200.*?\ue201', '', text, flags=re.DOTALL))
    return '\n'.join(texts).strip()


def reply(provider, config, instruction, messages):
    if provider == 'gpt':
        payload = {'model': config['llm_model'], 'instructions': instruction,
                   'input': messages, 'store': False, 'max_output_tokens': 2048}
        if config['web_search']:
            payload['tools'] = [{'type': 'web_search'}]
        result = post(provider, config, OPENAI + 'responses', payload)
        parts = [p for item in result.get('output', []) if item.get('type') == 'message'
                 for p in item.get('content', []) if p.get('type') == 'output_text']
    else:
        payload = {'model': config['llm_model'], 'system_instruction': instruction,
                   'input': [{'type': 'user_input' if m['role'] == 'user' else 'model_output',
                              'content': [{'type': 'text', 'text': m['content']}]} for m in messages],
                   'store': False}
        if config['web_search']:
            payload['tools'] = [{'type': 'google_search'}]
        result = post(provider, config, GOOGLE, payload)
        parts = [p for p in model_parts(result) if p.get('type') == 'text']
    if result.get('status') != 'completed':
        raise ValueError('The online provider did not complete its response.')
    sources = sources_for(parts)
    text = cited_text(parts, sources, provider)
    if not text:
        raise ValueError('The online provider returned no reply text.')
    return text, sources


def speech(provider, config, text):
    if provider == 'gpt':
        return post(provider, config, OPENAI + 'audio/speech',
                    {'model': config['tts_model'], 'voice': config['tts_voice'],
                     'input': text, 'response_format': 'wav'}, audio=True)
    result = post(provider, config, GOOGLE, {
        'model': config['tts_model'], 'input': text, 'store': False,
        'response_format': {'type': 'audio'},
        'generation_config': {'speech_config': [{'voice': config['tts_voice']}]}})
    parts = [p for p in model_parts(result) if p.get('type') == 'audio']
    if result.get('status') != 'completed' or not parts:
        raise ValueError('Gemini returned no complete speech audio.')
    # Unary Interactions TTS returns a complete WAV (not raw streaming PCM).
    buffers = [base64.b64decode(part['data'], validate=True) for part in parts]
    if any(not audio.startswith(b'RIFF') for audio in buffers):
        raise ValueError('Gemini speech must return WAV audio. Select a compatible TTS model.')
    if len(buffers) == 1:
        return buffers[0]
    output = io.BytesIO()
    with wave.open(output, 'wb') as writer:
        params = None
        for audio in buffers:
            with wave.open(io.BytesIO(audio), 'rb') as reader:
                shape = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
                if params is None:
                    params = shape
                    writer.setnchannels(shape[0])
                    writer.setsampwidth(shape[1])
                    writer.setframerate(shape[2])
                elif shape != params:
                    raise ValueError('Gemini returned incompatible audio segments.')
                writer.writeframes(reader.readframes(reader.getnframes()))
    return output.getvalue()
