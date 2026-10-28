param([switch]$CheckOnly, [switch]$InternalOnly)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogFolder = Join-Path $ProjectRoot 'data\logs'
New-Item -ItemType Directory -Force -Path $LogFolder | Out-Null
Start-Transcript -Path (Join-Path $LogFolder 'installation.log') -Append | Out-Null
try {
    $Python = Join-Path $ProjectRoot 'env\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        if ($CheckOnly) { throw 'Run Install Mio.cmd to create the Python environment first.' }
        $Candidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
            (Join-Path $env:ProgramFiles 'Python311\python.exe')
        )
        $BasePython = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $BasePython) {
            $PyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($PyLauncher) {
                $Found = & $PyLauncher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0) { $BasePython = $Found | Select-Object -Last 1 }
            }
        }
        if (-not $BasePython) {
            $Winget = Get-Command winget.exe -ErrorAction SilentlyContinue
            if (-not $Winget) { throw 'Install Python 3.11 x64 with Tkinter, then run this installer again.' }
            Write-Host 'Installing Python 3.11 for the current user...'
            & $Winget.Source install --id Python.Python.3.11 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. Install Python 3.11 x64 and retry.' }
            $BasePython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
        }
        & $BasePython -c 'import sys,struct,tkinter; assert sys.version_info[:2] == (3,11) and struct.calcsize(chr(80)) == 8'
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 x64 with Tkinter is required.' }
        & $BasePython -m venv (Join-Path $ProjectRoot 'env')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Mio environment.' }
    }
    & $Python -c 'import sys,struct,tkinter; assert sys.version_info[:2] == (3,11) and struct.calcsize(chr(80)) == 8'
    if ($LASTEXITCODE -ne 0) { throw 'The environment must use Python 3.11 x64 with Tkinter.' }
    if (-not $CheckOnly) {
        & (Join-Path $PSScriptRoot 'installer_env_unique.ps1')
    }
    $CheckArguments = @((Join-Path $PSScriptRoot 'check_installation.py'))
    if ($InternalOnly) { $CheckArguments += '--internal-only' }
    & $Python @CheckArguments
    if ($LASTEXITCODE -ne 0) { throw 'Installation checks found missing or incompatible components. Read data\logs\installation-check.json.' }
    Write-Host ''
    Write-Host 'Mio is installed. Open Launch Mio.vbs and connect external services in Customize before pressing Start.' -ForegroundColor Green
    Write-Host 'External programs and local models are checked, not downloaded or reinstalled.'
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
