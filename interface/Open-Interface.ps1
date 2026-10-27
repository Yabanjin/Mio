$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
try {
    $SettingsPath = Join-Path $Root 'settings\interface.local.json'
    if (-not (Test-Path -LiteralPath $SettingsPath)) {
        $SettingsPath = Join-Path $Root 'settings\interface.json'
    }
    $Settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    $Python = [Environment]::ExpandEnvironmentVariables($Settings.python)
    if (-not [IO.Path]::IsPathRooted($Python)) { $Python = Join-Path $Root $Python }
    $Pythonw = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $Pythonw)) {
        # A lightweight UI can still open to correct a missing service interpreter.
        $Pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $Pythonw -or -not (Test-Path -LiteralPath $Pythonw)) {
        throw 'Python with Tkinter was not found. Set python in settings/interface.json.'
    }
    $Script = Join-Path $Root 'interface\app.py'
    Start-Process -FilePath $Pythonw -ArgumentList ('"' + $Script + '"') -WorkingDirectory $Root
}
catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Mio') | Out-Null
}
