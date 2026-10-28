param([switch]$SkipTorch)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root 'env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment not found: $Python"
}
$env:PIP_CACHE_DIR = Join-Path $Root 'cache\pip'
$env:TEMP = Join-Path $Root 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:PIP_CACHE_DIR,$env:TEMP -Force | Out-Null

function Invoke-Pip([string[]]$Arguments) {
    & $Python -m pip @Arguments
    if ($LASTEXITCODE -ne 0) { throw "pip failed (exit code $LASTEXITCODE): $($Arguments -join ' ')" }
}

# Librosa 0.9 / Melo still import pkg_resources, removed in newer setuptools.
Invoke-Pip -Arguments @('install','--upgrade','pip','setuptools==80.9.0','wheel')
if (-not $SkipTorch) {
    Invoke-Pip -Arguments @('install','--index-url','https://download.pytorch.org/whl/cu126',
                 'torch==2.8.0+cu126','torchaudio==2.8.0+cu126')
}
Invoke-Pip -Arguments @('install','-r',(Join-Path $Root 'requirements-unified.txt'))
# These two packages declare a dependency on the CPU distribution of onnxruntime.
# Their modules use onnxruntime-gpu here. Do not install the CPU distribution
# in the same Python environment.
Invoke-Pip -Arguments @('install','--no-deps','faster-whisper==1.2.1','piper-tts==1.8.0')

$Vendor = Join-Path $Root 'vendor\MeloTTS'
if (-not (Test-Path -LiteralPath (Join-Path $Vendor 'melo\api.py'))) {
    throw "MeloTTS source not found: $Vendor"
}
$SitePackages = Join-Path $Root 'env\Lib\site-packages'
Set-Content -LiteralPath (Join-Path $SitePackages 'mio_melotts_vendor.pth') -Value $Vendor -Encoding ASCII
Write-Output "Shared environment installed: $Python"
Write-Output 'External services and models must be configured before starting Mio.'
