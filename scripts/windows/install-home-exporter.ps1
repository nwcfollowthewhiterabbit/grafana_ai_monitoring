param(
    [string]$Root = 'C:\ProgramData\RabbitMonitoring',
    [string]$ArtifactPath = ''
)
# Explicitly scoped home-host installer: no MSI, firewall rule, WinRM or logs.
$ErrorActionPreference = 'Stop'
$version = '0.31.8'
$sha256 = '03bb0fe80b8ad0b4e39606b96c4c5cc56b1f766760011ea2b00111157c6ef077'
$url = 'https://github.com/prometheus-community/windows_exporter/releases/download/v0.31.8/windows_exporter-0.31.8-amd64.exe'
if (-not [IO.Path]::IsPathRooted($Root) -or $Root.Contains('"')) { throw 'Invalid installation root' }
if (-not (Test-Path 'M:\rs' -PathType Container)) { throw 'Expected home workspace is unavailable' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator transport required' }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
if ((Get-Item $Root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installation root is a reparse point' }
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
    $rule = New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier($sid)), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -Path $Root -AclObject $acl
$binary = Join-Path $Root ('windows_exporter-' + $version + '-amd64.exe')
$binPath = '"' + $binary + '" --collectors.enabled=cpu,memory,logical_disk,system --collector.logical_disk.volume-include="^(C:|M:)$" --web.listen-address=127.0.0.1:9182 --log.file=eventlog'
$existing = Get-CimInstance Win32_Service -Filter "Name='windows_exporter'"
if ($existing -and $existing.PathName -ne $binPath) { throw 'Existing exporter service differs; review it before changing' }
if (-not (Test-Path $binary)) {
    $download = Join-Path $Root 'windows-exporter-download.exe'
    if ($ArtifactPath) { Copy-Item -LiteralPath $ArtifactPath -Destination $download }
    else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $download -TimeoutSec 120
    }
    if ((Get-FileHash $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha256) { throw 'Exporter SHA256 mismatch' }
    Move-Item -LiteralPath $download -Destination $binary
}
if ((Get-FileHash $binary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha256) { throw 'Installed exporter SHA256 mismatch' }
if (-not [Diagnostics.EventLog]::SourceExists('windows_exporter')) { New-EventLog -LogName Application -Source windows_exporter }
if (-not $existing) {
    New-Service -Name windows_exporter -DisplayName 'Rabbit home Windows metrics' -BinaryPathName $binPath -StartupType Automatic | Out-Null
    & sc.exe failure windows_exporter reset= 86400 actions= restart/5000/restart/30000/restart/60000 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to configure exporter recovery' }
}
Start-Service windows_exporter
$response = $null
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    try { $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:9182/metrics' -TimeoutSec 10; break }
    catch { if ($attempt -eq 14) { throw 'Exporter did not become readable on loopback' }; Start-Sleep -Seconds 2 }
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 9182)
if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw 'Exporter listener is not loopback only' }
foreach ($metric in @('windows_cpu_time_total', 'windows_memory_physical_total_bytes', 'windows_logical_disk_size_bytes')) {
    if ($response.Content -notmatch ('(?m)^' + $metric + '(\{| )')) { throw ('Missing bounded exporter metric: ' + $metric) }
}
[ordered]@{ Version=$version; SHA256=$sha256; Service='windows_exporter'; Listener='127.0.0.1:9182'; Collectors='cpu,memory,logical_disk,system'; Filesystems=@('C:', 'M:'); FirewallChanged=$false } | ConvertTo-Json -Depth 3
