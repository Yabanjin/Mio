param(
    [Parameter(Mandatory=$true)][ValidateSet('Start','Stop')][string]$Action,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Name,
    [Parameter(Mandatory=$true)][string]$Result
)
$ErrorActionPreference='Stop'
try {
    # Deliberately require elevation for every operation. No service rights are saved.
    $Identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal=New-Object Security.Principal.WindowsPrincipal($Identity)
    if(-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator confirmation is required to start or stop this Windows service.'
    }
    $Service=Get-Service -Name $Name -ErrorAction Stop
    $Changed=$false
    if($Action -eq 'Start' -and $Service.Status -ne 'Running') {
        Start-Service -Name $Name -ErrorAction Stop
        $Service.WaitForStatus('Running',[TimeSpan]::FromSeconds(45))
        $Changed=$true
    }
    if($Action -eq 'Stop' -and $Service.Status -ne 'Stopped') {
        Stop-Service -Name $Name -ErrorAction Stop
        $Service.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(45))
        $Changed=$true
    }
    @{ok=$true;changed=$Changed} | ConvertTo-Json | Set-Content -LiteralPath $Result -Encoding UTF8
} catch {
    @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $Result -Encoding UTF8
    exit 1
}
