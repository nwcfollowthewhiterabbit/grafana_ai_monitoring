param(
    [ValidateSet('Prepare', 'Start')][string]$Mode = 'Prepare',
    [Parameter(Mandatory=$true)][string]$RelayHost,
    [Parameter(Mandatory=$true)][string]$PinnedHostPublicKey,
    [string]$ListenAddress = '172.23.0.1',
    [ValidateRange(1024,65535)][int]$ListenPort = 19132,
    [string]$Root = 'C:\ProgramData\RabbitMonitoring'
)
$ErrorActionPreference = 'Stop'
if ($RelayHost -notmatch '^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$' -or $ListenAddress -ne '172.23.0.1') { throw 'Relay destination must be the reviewed IPv4 and private monitoring bridge' }
if ($PinnedHostPublicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/]{68}$') { throw 'A pinned Ed25519 public host key without comment is required' }
if (-not [IO.Path]::IsPathRooted($Root) -or $Root -match '["\r\n]') { throw 'Invalid private root' }
if (-not (Test-Path $Root -PathType Container) -or (Get-Item $Root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Install exporter/private root first' }
# Inherit only the exporter root's SYSTEM/Administrators DACL.
$dir = Join-Path $Root 'relay'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
if ((Get-Item $dir).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Relay directory is a reparse point' }
$key = Join-Path $dir 'id_ed25519'
$known = Join-Path $dir 'known_hosts'
$settings = Join-Path $dir 'relay.json'
$runner = Join-Path $dir 'run-relay.ps1'
$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$keygen = Join-Path $env:WINDIR 'System32\OpenSSH\ssh-keygen.exe'
if (-not (Test-Path $ssh) -or -not (Test-Path $keygen)) { throw 'Microsoft OpenSSH client required' }
if (-not (Test-Path $key)) {
    $process = Start-Process -FilePath $keygen -ArgumentList ('-q -t ed25519 -N "" -C rabbit-fpc-monitoring -f "' + $key + '"') -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw 'Relay key generation failed' }
}
$hostLine = $RelayHost + ' ' + $PinnedHostPublicKey
if (Test-Path $known) {
    if ((Get-Content -Raw $known).Trim() -ne $hostLine) { throw 'Existing pinned host key differs' }
} else { $hostLine | Set-Content -Encoding ASCII $known }
$configuration = [ordered]@{ Host=$RelayHost; User='monitoring-fpc'; ListenAddress=$ListenAddress; ListenPort=$ListenPort; LocalAddress='127.0.0.1'; LocalPort=9182 }
$json = $configuration | ConvertTo-Json -Compress
if (Test-Path $settings) {
    if ((Get-Content -Raw $settings).Trim() -ne $json) { throw 'Existing relay configuration differs' }
} else { $json | Set-Content -Encoding ASCII $settings }
$body = @'
$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw (Join-Path $PSScriptRoot 'relay.json') | ConvertFrom-Json
$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$key = Join-Path $PSScriptRoot 'id_ed25519'
$known = Join-Path $PSScriptRoot 'known_hosts'
$forward = '{0}:{1}:{2}:{3}' -f $config.ListenAddress,$config.ListenPort,$config.LocalAddress,$config.LocalPort
while ($true) {
    & $ssh -NT -F NUL -i $key -o ('UserKnownHostsFile=' + $known) -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o LogLevel=ERROR -R $forward ($config.User + '@' + $config.Host)
    Start-Sleep -Seconds 15
}
'@
if (Test-Path $runner) {
    if ((Get-Content -Raw $runner).Trim() -ne $body.Trim()) { throw 'Existing relay runner differs' }
} else { $body | Set-Content -Encoding ASCII $runner }
if ($Mode -eq 'Start') {
    $taskName = 'Rabbit-Home-Metrics-Relay'
    $exe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '"'
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $exe -or $task.Actions[0].Arguments -ne $arguments -or $task.Principal.UserId -notin @('SYSTEM','S-1-5-18')) { throw 'Existing relay task differs' }
    } else {
        $action = New-ScheduledTaskAction -Execute $exe -Argument $arguments
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = 'PT30S'
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        $options = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval ([TimeSpan]::FromMinutes(1))
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $options | Out-Null
    }
    Start-ScheduledTask -TaskName $taskName
}
[ordered]@{ Mode=$Mode; RelayHost=$RelayHost; RemoteListener=($ListenAddress+':'+$ListenPort); PublicKey=(Get-Content -Raw ($key+'.pub')).Trim(); FirewallChanged=$false } | ConvertTo-Json
