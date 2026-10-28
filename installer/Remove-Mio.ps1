$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $InstallRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
    $MarkerPath = Join-Path $InstallRoot '.mio-install.json'
    if (-not (Test-Path -LiteralPath $MarkerPath)) { throw 'Installation marker not found. No files were removed.' }
    $Marker = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json
    if ($Marker.Product -ne 'Mio.LocalInstaller.v1' -or
        [IO.Path]::GetFullPath($Marker.InstallRoot).TrimEnd('\') -ne $InstallRoot -or
        $InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot).TrimEnd('\')) {
        throw 'Installation location could not be verified. No files were removed.'
    }
    $Protected = @($env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:ProgramFiles, $env:WINDIR)
    if ($Protected -contains $InstallRoot) { throw 'Protected location. No files were removed.' }
    $Prefix = $InstallRoot + '\'
    $Running = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)
    }
    if ($Running) { throw 'Close Mio and its internal services, then run Uninstall Mio again.' }
    # Never recurse through a linked directory or junction into another application.
    $Pending = New-Object 'System.Collections.Generic.Queue[string]'
    $Pending.Enqueue($InstallRoot)
    while ($Pending.Count -gt 0) {
        $Folder = $Pending.Dequeue()
        $Info = Get-Item -LiteralPath $Folder -Force
        if ($Info.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked directory found: $Folder. No files were removed." }
        foreach ($Item in Get-ChildItem -LiteralPath $Folder -Force -Directory) {
            $Pending.Enqueue($Item.FullName)
        }
    }
    $Shell = New-Object -ComObject WScript.Shell
    $OwnedShortcuts = @()
    foreach ($Path in $Marker.Shortcuts) {
        if (Test-Path -LiteralPath $Path) {
            $Shortcut = $Shell.CreateShortcut($Path)
            if ($Shortcut.Arguments.Contains($Prefix)) { $OwnedShortcuts += $Path }
        }
    }
    # The verified absolute path is the directory containing this uninstaller.
    Set-Location -LiteralPath $env:TEMP
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force
    foreach ($Path in $OwnedShortcuts) { Remove-Item -LiteralPath $Path -Force }
    if ($Marker.RegistryKey -match '^Mio-[a-f0-9]{16}$') {
        $Key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $Marker.RegistryKey
        if (Test-Path -LiteralPath $Key) {
            $Entry = Get-ItemProperty -LiteralPath $Key
            if ($Entry.InstallLocation -eq $InstallRoot) { Remove-Item -LiteralPath $Key -Recurse -Force }
        }
    }
    $Menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mio'
    $MenuPrefix = [IO.Path]::GetFullPath($Menu).TrimEnd('\') + '\'
    foreach ($ShortcutFolder in ($OwnedShortcuts | ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique)) {
        $ResolvedFolder = [IO.Path]::GetFullPath($ShortcutFolder).TrimEnd('\')
        if ($ResolvedFolder.StartsWith($MenuPrefix, [StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $ResolvedFolder) -and -not (Get-ChildItem -LiteralPath $ResolvedFolder -Force)) {
            Remove-Item -LiteralPath $ResolvedFolder
        }
    }
    if ((Test-Path -LiteralPath $Menu) -and -not (Get-ChildItem -LiteralPath $Menu -Force)) {
        Remove-Item -LiteralPath $Menu
    }
    Write-Output 'Mio and its local data have been removed.'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
