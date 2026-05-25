# Windows Server 2019 Monitoring

This runbook adds a Windows Server 2019 / Hyper-V host to the Grafana AI Monitoring stack.

## What Is Collected

- Host availability through `up{job="windows_exporter_clients"}`.
- CPU, memory, logical disks, network, TCP, process, OS and system metrics from `windows_exporter`.
- Specific Windows services through `windows_custom_service_desired_running`.
- Hyper-V VM state and uptime through `windows_custom_hyperv_vm_state` and `windows_custom_hyperv_vm_uptime_seconds`.
- Backup health through watched backup paths and Windows Server Backup success events.

## Windows Install

Copy the `scripts/windows` directory to the Windows host, then run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\install-windows-monitoring.ps1 `
  -ServiceNames @("vmms", "Winmgmt", "wbengine") `
  -BackupPaths @("D:\Backups", "\\backup-share\server2019")
```

Adjust `-ServiceNames` and `-BackupPaths` to the real services and backup locations.

The installer:

- downloads the latest `prometheus-community/windows_exporter` MSI;
- installs it as a Windows service on port `9182`;
- enables host, disk, network, service, process, textfile and Hyper-V collectors;
- creates a scheduled task named `Grafana Windows Custom Metrics`;
- opens the local firewall port for Prometheus scraping.

Local smoke test on the Windows host:

```powershell
Invoke-WebRequest http://127.0.0.1:9182/metrics -UseBasicParsing
Get-Content C:\ProgramData\windows_exporter\textfile_inputs\windows_custom.prom
```

## Prometheus Target

After the Windows host is reachable from `con`, add it to:

```text
monitoring/prometheus/file_sd/windows_targets.yml
```

Example:

```yaml
- targets:
    - 10.0.0.25:9182
  labels:
    alias: win2019
    company: my own
    workspace: personal
    role: hyperv
```

Then apply on `con`:

```bash
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill -s HUP monitoring-prometheus
docker restart monitoring-grafana
```

## Alerts

Provisioned Grafana rules:

- `windows-exporter-down`: exporter unreachable for 5 minutes.
- `windows-watched-service-down`: configured service missing or not running for 2 minutes.
- `windows-hyperv-vm-not-running`: discovered Hyper-V VM not in `Running` state for 5 minutes.
- `windows-backup-path-unavailable`: backup path cannot be listed for 30 minutes.
- `windows-backup-stale`: watched backup path has no new files for 25 hours.

If some VMs are normally powered off, filter them in `windows-custom-metrics.ps1` or pause the VM rule until the expected VM list is known.
