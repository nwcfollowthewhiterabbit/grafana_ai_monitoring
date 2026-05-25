param(
    [string]$ExporterVersion = "latest",
    [string]$ListenAddress = "0.0.0.0",
    [int]$ListenPort = 9182,
    [string[]]$ServiceNames = @("Winmgmt", "vmms", "wbengine"),
    [string[]]$BackupPaths = @(),
    [string]$MetricsDir = "C:\ProgramData\windows_exporter\textfile_inputs"
)

$ErrorActionPreference = "Stop"

function Get-LatestWindowsExporterVersion {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/prometheus-community/windows_exporter/releases/latest" -UseBasicParsing
    return $release.tag_name.TrimStart("v")
}

if ($ExporterVersion -eq "latest") {
    $ExporterVersion = Get-LatestWindowsExporterVersion
}

$workDir = "C:\ProgramData\grafana-ai-monitoring"
$scriptDir = Join-Path $workDir "scripts"
New-Item -ItemType Directory -Force -Path $workDir, $scriptDir, $MetricsDir | Out-Null

$msiName = "windows_exporter-$ExporterVersion-amd64.msi"
$msiUrl = "https://github.com/prometheus-community/windows_exporter/releases/download/v$ExporterVersion/$msiName"
$msiPath = Join-Path $workDir $msiName

Write-Host "Downloading $msiUrl"
Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing

$collectors = "cpu,cs,logical_disk,memory,net,os,service,system,tcp,textfile,process,hyperv"
$msiArgs = @(
    "/i", "`"$msiPath`"",
    "ENABLED_COLLECTORS=`"$collectors`"",
    "TEXTFILE_DIRS=`"$MetricsDir`"",
    "LISTEN_ADDR=$ListenAddress",
    "LISTEN_PORT=$ListenPort",
    "/qn", "/norestart"
)

Write-Host "Installing windows_exporter $ExporterVersion"
$process = Start-Process -FilePath "msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "msiexec failed with exit code $($process.ExitCode)"
}

Copy-Item -Path (Join-Path $PSScriptRoot "windows-custom-metrics.ps1") -Destination (Join-Path $scriptDir "windows-custom-metrics.ps1") -Force

$servicesArg = $ServiceNames | ConvertTo-Json -Compress
$backupPathsArg = $BackupPaths | ConvertTo-Json -Compress
$actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptDir\windows-custom-metrics.ps1`" -MetricsDir `"$MetricsDir`" -ServiceNamesJson '$servicesArg' -BackupPathsJson '$backupPathsArg'"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration ([TimeSpan]::MaxValue)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask -TaskName "Grafana Windows Custom Metrics" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "Grafana Windows Custom Metrics"

New-NetFirewallRule -DisplayName "windows_exporter metrics" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $ListenPort -ErrorAction SilentlyContinue | Out-Null

Write-Host "Done. Test locally: Invoke-WebRequest http://127.0.0.1:$ListenPort/metrics"
