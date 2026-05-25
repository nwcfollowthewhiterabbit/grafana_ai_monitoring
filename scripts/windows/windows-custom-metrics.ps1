param(
    [string]$MetricsDir = "C:\ProgramData\windows_exporter\textfile_inputs",
    [string]$ServiceNamesJson = "[]",
    [string]$BackupPathsJson = "[]"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $MetricsDir | Out-Null

function Escape-Label([string]$Value) {
    return ($Value -replace '\\', '\\' -replace '"', '\"' -replace "`n", "\n")
}

function Unix-Time([datetime]$Date) {
    return [int64]([DateTimeOffset]$Date).ToUnixTimeSeconds()
}

$serviceNames = @()
$backupPaths = @()
if ($ServiceNamesJson) { $serviceNames = @(ConvertFrom-Json $ServiceNamesJson) }
if ($BackupPathsJson) { $backupPaths = @(ConvertFrom-Json $BackupPathsJson) }

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# HELP windows_custom_service_desired_running Whether a watched Windows service is running.")
$lines.Add("# TYPE windows_custom_service_desired_running gauge")

foreach ($name in $serviceNames) {
    if (-not $name) { continue }
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    $value = 0
    $state = "missing"
    if ($svc) {
        $state = [string]$svc.Status
        if ($svc.Status -eq "Running") { $value = 1 }
    }
    $lines.Add(('windows_custom_service_desired_running{service="{0}",state="{1}"} {2}' -f (Escape-Label $name), (Escape-Label $state), $value))
}

$lines.Add("# HELP windows_custom_hyperv_vm_state Current VM state encoded as running=1, off=0, other=2.")
$lines.Add("# TYPE windows_custom_hyperv_vm_state gauge")
$lines.Add("# HELP windows_custom_hyperv_vm_uptime_seconds VM uptime in seconds when available.")
$lines.Add("# TYPE windows_custom_hyperv_vm_uptime_seconds gauge")

try {
    if (Get-Command Get-VM -ErrorAction SilentlyContinue) {
        foreach ($vm in Get-VM) {
            $stateValue = 2
            if ($vm.State -eq "Running") { $stateValue = 1 }
            elseif ($vm.State -eq "Off") { $stateValue = 0 }
            $vmName = Escape-Label ([string]$vm.Name)
            $state = Escape-Label ([string]$vm.State)
            $lines.Add(('windows_custom_hyperv_vm_state{vm="{0}",state="{1}"} {2}' -f $vmName, $state, $stateValue))
            $lines.Add(('windows_custom_hyperv_vm_uptime_seconds{vm="{0}"} {1}' -f $vmName, [int64]$vm.Uptime.TotalSeconds))
        }
    }
}
catch {
    $lines.Add(('windows_custom_hyperv_collection_error{error="{0}"} 1' -f (Escape-Label $_.Exception.Message)))
}

$lines.Add("# HELP windows_custom_backup_path_latest_timestamp_seconds Latest file write timestamp under a watched backup path.")
$lines.Add("# TYPE windows_custom_backup_path_latest_timestamp_seconds gauge")
$lines.Add("# HELP windows_custom_backup_path_available Whether a watched backup path can be listed.")
$lines.Add("# TYPE windows_custom_backup_path_available gauge")

foreach ($path in $backupPaths) {
    if (-not $path) { continue }
    $labelPath = Escape-Label $path
    try {
        $latest = Get-ChildItem -Path $path -File -Recurse -ErrorAction Stop |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        $timestamp = 0
        if ($latest) { $timestamp = Unix-Time $latest.LastWriteTimeUtc }
        $lines.Add(('windows_custom_backup_path_available{path="{0}"} 1' -f $labelPath))
        $lines.Add(('windows_custom_backup_path_latest_timestamp_seconds{path="{0}"} {1}' -f $labelPath, $timestamp))
    }
    catch {
        $lines.Add(('windows_custom_backup_path_available{path="{0}"} 0' -f $labelPath))
        $lines.Add(('windows_custom_backup_path_latest_timestamp_seconds{path="{0}"} 0' -f $labelPath))
    }
}

$lines.Add("# HELP windows_custom_windows_backup_last_success_timestamp_seconds Latest successful Microsoft-Windows-Backup event timestamp.")
$lines.Add("# TYPE windows_custom_windows_backup_last_success_timestamp_seconds gauge")
$lastBackupSuccess = 0
try {
    $event = Get-WinEvent -FilterHashtable @{ ProviderName = "Microsoft-Windows-Backup"; Id = 4 } -MaxEvents 1 -ErrorAction Stop
    if ($event) { $lastBackupSuccess = Unix-Time $event.TimeCreated.ToUniversalTime() }
}
catch {
    $lastBackupSuccess = 0
}
$lines.Add(('windows_custom_windows_backup_last_success_timestamp_seconds {0}' -f $lastBackupSuccess))

$tmp = Join-Path $MetricsDir "windows_custom.prom.tmp"
$out = Join-Path $MetricsDir "windows_custom.prom"
$lines | Set-Content -Encoding ASCII -Path $tmp
Move-Item -Force -Path $tmp -Destination $out
