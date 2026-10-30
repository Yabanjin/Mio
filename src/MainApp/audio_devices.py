"""Resolve the same raw audio input for Mio and its settings meter."""
import math

SAMPLE_RATE = 16000


def resolve_input_device(config, audio):
    source = config.get('microphone_source', 'device')
    if source == 'default':
        index = int(audio.default.device[0])
        if index < 0 or audio.query_devices(index)['max_input_channels'] < 1:
            raise ValueError('No default Windows input is available. Choose one in Windows Sound settings.')
        return index
    if source != 'device':
        raise ValueError('Microphone source must be default or device.')
    prefix = config['microphone_name_prefix'].strip()
    backend = config['microphone_hostapi'].strip()
    if not prefix or not backend:
        raise ValueError('Choose a microphone and its audio backend.')
    matches = [i for i, device in enumerate(audio.query_devices())
               if device['max_input_channels'] > 0 and device['name'].startswith(prefix)
               and audio.query_hostapis(device['hostapi'])['name'] == backend]
    if len(matches) != 1:
        raise ValueError(f'Input not found or ambiguous: {prefix!r} ({backend}); '
                         f'{len(matches)} matches. Refresh devices and select a unique input.')
    return matches[0]


def dbfs(level):
    return max(-80.0, 20.0 * math.log10(max(float(level), 1e-8)))


def validate_audio(config):
    if config.get('microphone_source', 'device') not in ('device', 'default'):
        raise ValueError('Choose Windows default input or a specific device.')
    if config.get('microphone_source', 'device') == 'device':
        if not config.get('microphone_name_prefix', '').strip() or not config.get('microphone_hostapi', '').strip():
            raise ValueError('Select a specific input device, or use Windows default input.')
    for key in ('vb_cable_gate_rms', 'whisper_gate_rms'):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
            raise ValueError(f'{key}: expected a finite RMS threshold from 0 (disabled) to less than 1.')
    hold = config['vb_cable_gate_hold_ms']
    if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not math.isfinite(hold) or hold < 0:
        raise ValueError('Gate hold time must be a non-negative number of milliseconds.')
