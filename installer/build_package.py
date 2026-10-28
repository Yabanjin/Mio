"""Assemble an anonymous development installer from the canonical source."""
from pathlib import Path
import json
import shutil
import subprocess
import hashlib

ROOT=Path(__file__).resolve().parent.parent
OUTPUT=ROOT/'dist/Mio Installer'
PAYLOAD=OUTPUT/'payload'
if OUTPUT.exists():
    raise SystemExit('Output already exists. Archive it or choose a new output folder before rebuilding.')
OUTPUT.mkdir(parents=True)
skip={'__pycache__','env','cache','logs','data','.git','.locks','.cache','echantillons'}
count=0
size=0

# Refuse to package enrolled people or accumulated identity facts.
for name in ('famille_connue.json','identite_mio.json'):
    if json.loads((ROOT/'src/MemoireVectorielle'/name).read_text(encoding='utf-8-sig')).get('facts'):
        raise RuntimeError('Clear initial memory reference facts before building an anonymous package.')
profiles=json.loads((ROOT/'src/Speechbrain/profiles.json').read_text(encoding='utf-8-sig'))['profiles']
if [p['name'] for p in profiles] != ['User','Child','Adult','Mio'] or any(p.get('reference_files') for p in profiles):
    raise RuntimeError('Use generic profiles without voice samples for an anonymous package.')
def copy(source, relative):
    global count,size
    if source.is_symlink():
        # Cache links are materialized so the package is self-contained.
        if not source.resolve().is_file(): raise RuntimeError('Broken resource link: '+str(source))
    target=PAYLOAD/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
    count+=1;size+=target.stat().st_size
for directory in ('src','interface','vendor','settings'):
    for source in (ROOT/directory).rglob('*'):
        if not source.is_file():continue
        rel=source.relative_to(ROOT)
        if any(part in skip for part in rel.parts):continue
        if source.suffix.lower() in {'.log','.pyc','.bak','.sqlite','.sqlite3','.db','.wav','.mp3','.flac'}:continue
        if source.name.endswith(('-wal','-shm')):continue
        if source.name in {'interface.local.json','mio-gpu-ready.json','ready.json'}:continue
        copy(source,rel)
for name in ('Launch Mio.vbs','requirements-unified.txt'):
    copy(ROOT/name,Path(name))
for name in ('Install-Mio.ps1','installer_env_unique.ps1','check_installation.py','Manage-WindowsService.ps1'):
    copy(ROOT/'scripts'/name,Path('scripts')/name)
copy(ROOT/'installer/Uninstall-Mio.ps1',Path('Uninstall-Mio.ps1'))
copy(ROOT/'installer/Remove-Mio.ps1',Path('scripts/Remove-Mio.ps1'))
copy(ROOT/'images/branding/mio.ico',Path('images/mio.ico'))
copy(ROOT/'images/branding/mio.png',Path('images/mio.png'))
config_path=PAYLOAD/'settings/interface.json'
config=json.loads(config_path.read_text(encoding='utf-8-sig'))
config['python']='env/Scripts/python.exe'
# Keep the canonical generic source settings. External servers and LLM weights
# are installed and connected separately by the user.
config_path.write_text(json.dumps(config,indent=2),encoding='utf-8')
(PAYLOAD/'Install Mio.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\Install-Mio.ps1" -InternalOnly\r\npause\r\n',encoding='ascii')
shutil.copyfile(ROOT/'images/branding/mio.png',OUTPUT/'mio.png')
(OUTPUT/'READ ME.txt').write_text('Mio — development installer\n\nDouble-click Mio Setup.exe. This development output needs payload and mio.png beside it.\nThe standalone FR/EN test EXEs are provided separately with their manuals.\nChoose an empty destination folder. Python dependencies require internet.\n\nIncluded: Mio interface/engine, internal speech and recognition components and available local model resources.\nExternal applications and LLM weights are not installed by Mio. Connect them in Customize.\nInitial memory is empty and profiles are generic, without voice references.\n',encoding='utf-8')
compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Core.dll','/reference:System.Web.Extensions.dll','/reference:Microsoft.CSharp.dll','/win32icon:'+str(ROOT/'images/branding/mio.ico'),'/out:'+str(OUTPUT/'Mio Setup.exe'),str(ROOT/'installer/MioSetup.cs')],check=True)
manifest={'files':count,'payload_bytes':size,'external_applications_included':False,'anonymous_defaults':True}
(OUTPUT/'package-info.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest));print(OUTPUT/'Mio Setup.exe')
