"""Offline installation checks: no model generation or service startup."""
import ast
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
results = []
def record(name, ok, detail=''):
    results.append(dict(name=name, ok=bool(ok), detail=str(detail)))
    print(('OK   ' if ok else 'FAIL ') + name + (': ' + str(detail) if detail else ''), flush=True)
def resolve(value):
    path = Path(os.path.expandvars(value))
    return path if path.is_absolute() else ROOT / path
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))

settings_path=ROOT/'settings/interface.local.json'
if not settings_path.exists(): settings_path=ROOT/'settings/interface.json'
settings=load(settings_path)

record('Python 3.11 x64', sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32, sys.version.split()[0])
for folder in ('interface', 'src'):
    for path in (ROOT / folder).rglob('*.py'):
        if any(part in ('__pycache__', 'models', 'hf_cache', 'huggingface', 'env') for part in path.relative_to(ROOT).parts): continue
        try: ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        except Exception as error: record(str(path.relative_to(ROOT)), False, error)
for module in ('tkinter','numpy','scipy','torch','torchaudio','onnxruntime','faster_whisper','piper','sounddevice','vosk','speechbrain','transformers','fastembed','pywebrtc_audio','melo.api'):
    env = dict(os.environ, PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    env['PYTHONPATH'] = str(ROOT/'vendor/MeloTTS')
    env['HF_HOME'] = str(resolve(settings['resources']['MIO_MELO_CACHE']))
    env['HUGGINGFACE_HUB_CACHE'] = str(Path(env['HF_HOME'])/'hub')
    env['TRANSFORMERS_CACHE'] = env['HUGGINGFACE_HUB_CACHE']
    try:
        output = subprocess.run([sys.executable,'-c',f'import {module}'], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        record('Import '+module, output.returncode == 0, output.stderr[-1500:] if output.returncode else '')
    except Exception as error: record('Import '+module,False,error)
try:
    metadata.distribution('onnxruntime')
except metadata.PackageNotFoundError: record('No competing CPU ONNX package',True)
else: record('No competing CPU ONNX package',False,'Use onnxruntime-gpu only.')
settings_path=ROOT/'settings/interface.local.json'
if not settings_path.exists(): settings_path=ROOT/'settings/interface.json'
settings=load(settings_path)
for name,value in settings['resources'].items():
    path=resolve(value)
    record(name, path.is_file() or (path.is_dir() and any(path.iterdir())), path)
for service in ([] if '--internal-only' in sys.argv else settings['external_services']):
    path=resolve(service['executable']) if service['executable'] else None
    record('External program '+service['name'], path is not None and path.is_file(),path or 'Configure executable in Startup')
for utility in ([] if '--internal-only' in sys.argv else settings.get('startup_tools', [])):
    if utility.get('enabled', False):
        path=resolve(utility['executable'])
        record('Startup utility '+utility['name'],path.is_file(),path)
for profile in load(ROOT/'src/Speechbrain/profiles.json')['profiles']:
    for filename in profile.get('reference_files',[]):
        path=ROOT/'src/Speechbrain'/filename
        record('Voice reference '+profile['name'],path.is_file(),path)
for folder in ('settings', 'src/MainApp/config'):
    for path in (ROOT/folder).rglob('*.json'):
        try: load(path)
        except Exception as error: record(str(path.relative_to(ROOT)),False,error)
report=ROOT/'data/logs/installation-check.json'
report.parent.mkdir(parents=True,exist_ok=True)
report.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
print('Report: '+str(report),flush=True)
sys.exit(0 if all(item['ok'] for item in results) else 1)
