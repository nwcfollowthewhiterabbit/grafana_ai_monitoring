# Windows Monitoring Playbook

This playbook describes how to add a Windows Server or Windows VM to this Grafana AI Monitoring stack.

## Overview

Windows hosts are monitored through `windows_exporter` on TCP `9182`. Prometheus discovers Windows targets from:

```text
monitoring/prometheus/file_sd/windows_targets.yml
```

The installer in `scripts/windows/install-windows-monitoring.ps1` also sets up a textfile collector task for custom metrics:

- watched Windows services;
- Hyper-V VM state and uptime, when Hyper-V PowerShell cmdlets exist;
- watched backup paths;
- latest Windows Server Backup success/failure events.
- Remote Desktop session activity from `quser`.

## Prerequisites

Network requirements:

- Prometheus server `con` must be able to reach the Windows host on TCP `9182`.
- If the host is behind NAT, establish the site VPN or another private route first.
- For remote installation, `con` must reach WinRM on TCP `5985`.

Windows account requirements:

- local administrator credentials;
- PowerShell running as Administrator for local preparation;
- Remote UAC filter disabled for local admin WinRM access.

Enable WinRM on the Windows host:

```powershell
reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f
Enable-PSRemoting -Force
netsh advfirewall firewall set rule group="Windows Remote Management" new enable=yes
Restart-Service WinRM
```

If the host is old, for example Windows Server 2016, keep TLS 1.2 enabled for GitHub downloads:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
```

## Choose Labels

Every Windows target needs stable labels:

```yaml
alias: <short-node-name>
company: <company-segment>
workspace: <openclaw-workspace>
role: <server-role>
```

Use existing workspace labels for alert routing:

- `workspace=greenleaf`
- `workspace=rentoll`
- `workspace=personal`

Examples:

```yaml
alias: rentall-hyperv
company: rentall
workspace: rentoll
role: hyperv
```

```yaml
alias: rentall-rdp
company: rentall
workspace: rentoll
role: rdp
```

## Install Exporter

Copy `scripts/windows/` to the Windows host, then run PowerShell as Administrator from that directory.

Generic host:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
.\install-windows-monitoring.ps1 `
  -ExporterVersion "0.31.7" `
  -ServiceNames @("Winmgmt", "TermService") `
  -BackupPaths @()
```

Hyper-V host example:

```powershell
.\install-windows-monitoring.ps1 `
  -ExporterVersion "0.31.7" `
  -ServiceNames @("vmms", "vmcompute", "MSSQLSERVER", "SQLBrowser", "SQLWriter", "TermService", "SessionEnv", "UmRdpService") `
  -BackupPaths @("D:\Backup")
```

RDP VM example:

```powershell
.\install-windows-monitoring.ps1 `
  -ExporterVersion "0.31.7" `
  -ServiceNames @("TermService", "SessionEnv", "UmRdpService", "Spooler", "VSS", "vmicvss") `
  -BackupPaths @()
```

The installer:

- downloads and installs `prometheus-community/windows_exporter`;
- configures collectors: CPU, memory, disks, physical disks, network, OS, service, system, TCP, process, Hyper-V and textfile;
- opens inbound TCP `9182` in Windows Firewall;
- creates `C:\ProgramData\grafana-ai-monitoring\windows-custom-metrics.ps1`;
- creates a scheduled task named `Grafana Windows Custom Metrics` that refreshes custom metrics every minute.

## Local Smoke Test

Run on the Windows host:

```powershell
Invoke-WebRequest http://127.0.0.1:9182/metrics -UseBasicParsing
Get-Content C:\ProgramData\windows_exporter\textfile_inputs\windows_custom.prom
```

Expected signals:

```text
windows_exporter_collector_success{collector="textfile"} 1
windows_memory_physical_total_bytes ...
windows_custom_service_desired_running{service="...",state="Running"} 1
windows_custom_rdp_session_idle_seconds{user="...",state="active"} ...
```

## RDP Activity Metrics

The custom textfile script runs `quser` and exports one series per interactive session:

```text
windows_custom_rdp_session_idle_seconds
windows_custom_rdp_session_last_input_timestamp_seconds
windows_custom_rdp_session_logon_timestamp_seconds
windows_custom_rdp_session_active
```

Use these metrics to decide whether it is safe to reboot an RDP server:

- `state="active"` and low `idle_seconds`: the user is likely working now;
- `state="active"` and high `idle_seconds`: the session is open but probably idle;
- `state="disc"`: disconnected session.

The script normalizes localized Windows session states into ASCII labels: `active`, `disc`, or `other`.

## Add Prometheus Target

Edit:

```text
monitoring/prometheus/file_sd/windows_targets.yml
```

Example:

```yaml
- targets:
    - 192.168.112.19:9182
  labels:
    alias: rentall-rdp
    company: rentall
    workspace: rentoll
    role: rdp
```

Apply on `con`:

```bash
cp monitoring/prometheus/file_sd/windows_targets.yml /root/monitoring/prometheus/file_sd/windows_targets.yml
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill -s HUP monitoring-prometheus
```

## Prometheus Smoke Test

Run on `con`:

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up{job="windows_exporter_clients"}' | jq
```

Check custom service metrics for a specific host:

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=windows_custom_service_desired_running{job="windows_exporter_clients",alias="rentall-rdp"}' | jq
```

## Grafana

Windows hosts appear in:

```text
https://grafana.exemstsc.world/d/windows-server-2019/windows-server-2019
```

The dashboard title is `Windows Server / Hyper-V`. The UID remains `windows-server-2019` for compatibility with existing links.

## Troubleshooting

If WinRM authentication fails for a local administrator, confirm `LocalAccountTokenFilterPolicy=1` and restart WinRM.

If GitHub downloads fail on Windows Server 2016, set TLS 1.2 and use a fixed exporter version:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
.\install-windows-monitoring.ps1 -ExporterVersion "0.31.7"
```

If `/metrics` works but `windows_custom_*` is missing, verify that textfile collector is enabled in the service path:

```powershell
Get-CimInstance Win32_Service -Filter "Name='windows_exporter'" | Select-Object PathName
```

The service path must include:

```text
--collectors.enabled="...,textfile,..." --collector.textfile.directories="C:\ProgramData\windows_exporter\textfile_inputs"
```

If custom service metrics appear as one combined service name, the scheduled task or CMD wrapper broke JSON quoting. Re-run the current installer from this repository; it uses a PowerShell wrapper file to avoid CMD JSON quoting issues.
