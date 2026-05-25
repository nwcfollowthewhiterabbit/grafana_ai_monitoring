param(
    [string]$ExporterVersion = "latest",
    [string]$ListenAddress = "0.0.0.0",
    [int]$ListenPort = 9182,
    [string[]]$ServiceNames = @("Winmgmt", "vmms", "wbengine"),
    [string[]]$BackupPaths = @(),
    [string]$MetricsDir = "C:\ProgramData\windows_exporter\textfile_inputs"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-LatestWindowsExporterVersion {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/prometheus-community/windows_exporter/releases/latest" -UseBasicParsing
    return $release.tag_name.TrimStart("v")
}

if ($ExporterVersion -eq "latest") {
    $ExporterVersion = Get-LatestWindowsExporterVersion
}

$workDir = "C:\ProgramData\grafana-ai-monitoring"
New-Item -ItemType Directory -Force -Path $workDir, $MetricsDir | Out-Null

$msiName = "windows_exporter-$ExporterVersion-amd64.msi"
$msiUrl = "https://github.com/prometheus-community/windows_exporter/releases/download/v$ExporterVersion/$msiName"
$msiPath = Join-Path $workDir $msiName

Write-Host "Downloading $msiUrl"
Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing

$collectors = "cpu,memory,logical_disk,physical_disk,net,os,service,system,tcp,textfile,process,hyperv"
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

$exporterExe = "C:\Program Files\windows_exporter\windows_exporter.exe"
$binPath = '"{0}" --collectors.enabled="{1}" --collector.textfile.directories="{2}" --web.listen-address=":{3}"' -f $exporterExe, $collectors, $MetricsDir, $ListenPort
$service = Get-CimInstance Win32_Service -Filter "Name='windows_exporter'"
$change = Invoke-CimMethod -InputObject $service -MethodName Change -Arguments @{ PathName = $binPath }
if ($change.ReturnValue -ne 0) {
    throw "failed to configure windows_exporter service path, return value $($change.ReturnValue)"
}

Copy-Item -Path (Join-Path $PSScriptRoot "windows-custom-metrics.ps1") -Destination (Join-Path $workDir "windows-custom-metrics.ps1") -Force

$servicesArg = $ServiceNames | ConvertTo-Json -Compress
$backupPathsArg = $BackupPaths | ConvertTo-Json -Compress

$collectorScript = Join-Path $workDir "collect-windows-custom-metrics.ps1"
$runnerScript = Join-Path $workDir "run-custom-metrics.cmd"
@(
    ('${servicesJson} = ''{0}''' -f ($servicesArg -replace "'", "''")),
    ('${backupPathsJson} = ''{0}''' -f ($backupPathsArg -replace "'", "''")),
    ('& "{0}" -MetricsDir "{1}" -ServiceNamesJson ${servicesJson} -BackupPathsJson ${backupPathsJson}' -f (Join-Path $workDir "windows-custom-metrics.ps1"), $MetricsDir)
) | Set-Content -Encoding ASCII -Path $collectorScript
@(
    "@echo off",
    ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $collectorScript)
) | Set-Content -Encoding ASCII -Path $runnerScript

& $runnerScript
schtasks.exe /Create /TN "Grafana Windows Custom Metrics" /SC MINUTE /MO 1 /TR "`"$runnerScript`"" /RU SYSTEM /RL HIGHEST /F | Out-Null

Restart-Service windows_exporter -Force

New-NetFirewallRule -DisplayName "windows_exporter metrics" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $ListenPort -ErrorAction SilentlyContinue | Out-Null

Write-Host "Done. Test locally: Invoke-WebRequest http://127.0.0.1:$ListenPort/metrics"
