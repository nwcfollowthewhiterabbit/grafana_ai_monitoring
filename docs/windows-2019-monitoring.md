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

This Rentall site is reachable from `con` through the Rentall VPN:

- MikroTik VM: `192.168.112.1`.
- Host OS / Hyper-V / SQL / M.E.Doc / VM backups / VM RDP: `192.168.112.20`.
- RDP VM: `192.168.112.19`.

Current VPN status: IPsec and L2TP/PPP establish successfully from `con`; `con` receives `192.168.112.68`, and both `192.168.112.1` and `192.168.112.20` respond to ping.

After VPN is up and `windows_exporter` is installed on `192.168.112.20`, add the Windows target to:

```text
monitoring/prometheus/file_sd/windows_targets.yml
```

Example:

```yaml
- targets:
    - 192.168.112.20:9182
  labels:
    alias: win2019
    company: rentall
    workspace: rentoll
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

## MikroTik VM Monitoring

The MikroTik router is a VM on this Windows/Hyper-V host. Do not expose SNMP to the public internet. Prometheus scrapes `snmp_exporter` on `con`, and `snmp_exporter` polls the MikroTik through the VPN.

On the MikroTik, enable SNMP read-only access for the VPN/client source used by `con`. RouterOS example:

```routeros
/snmp set enabled=yes
/snmp community add name=grafana addresses=<con-vpn-client-ip>/32 read-access=yes
```

Smoke test from `con` after SNMP is enabled:

```bash
curl 'http://172.17.0.1:9116/snmp?auth=public_v2&module=if_mib&target=192.168.112.1'
```

Current SNMP status: ICMP reaches `192.168.112.1`, but SNMP returns `connection refused`. Enable SNMP on RouterOS and allow the VPN source IP, currently `192.168.112.68`, or the full monitoring VPN pool.

After the VPN is up, add the MikroTik target to:

```text
monitoring/prometheus/file_sd/mikrotik_targets.yml
```

Example:

```yaml
- targets:
    - 192.168.112.1
  labels:
    alias: rentall-mikrotik
    company: rentall
    workspace: rentoll
    role: router
    parent_host: win2019
```

Prometheus sends the `target` parameter to `snmp_exporter` on `con`:

```text
Prometheus -> snmp-exporter:9116 -> VPN -> MikroTik 192.168.112.1 UDP/161
```

Dashboard:

```text
https://grafana.exemstsc.world/d/mikrotik-router/mikrotik-router
```
