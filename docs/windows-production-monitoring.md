# Production Windows Monitoring

This document describes how Windows and related Rentall infrastructure are monitored in this production Grafana AI Monitoring deployment.

## Topology

Monitoring server:

- `con` runs the Docker monitoring stack: Prometheus, Grafana, exporters and file-based target discovery.
- Prometheus job for Windows hosts: `windows_exporter_clients`.
- Windows targets are defined in `monitoring/prometheus/file_sd/windows_targets.yml`.
- MikroTik SNMP targets are defined in `monitoring/prometheus/file_sd/mikrotik_targets.yml`.

Rentall site access:

- The Rentall site is behind NAT.
- `con` establishes L2TP/IPsec VPN to `vpn.rentall.in.ua` using `systemd/rentall-vpn.service`.
- VPN client address on `con`: `192.168.112.18`.
- Internal Rentall subnet used by monitoring: `192.168.112.0/24`.

## Monitored Windows Nodes

Current production Windows targets:

```yaml
- targets:
    - 192.168.112.20:9182
  labels:
    alias: rentall-hyperv
    company: rentall
    workspace: rentoll
    role: hyperv
- targets:
    - 192.168.112.19:9182
  labels:
    alias: rentall-rdp
    company: rentall
    workspace: rentoll
    role: rdp
```

### `rentall-hyperv`

Address:

```text
192.168.112.20:9182
```

Observed host identity:

- hostname: `ns3053862`;
- OS: Windows Server 2025 Standard;
- role: MSSQL Server, Hyper-V host and M.E.Doc server.

Hosted VMs and routed sites:

- `192.168.112.19`: RDP server and 1C server;
- `192.168.112.1`: MikroTik router.
- `192.168.1.1`: office MikroTik router, reachable through VPN routing on `192.168.112.1`.

Collected metrics:

- host availability: `up{job="windows_exporter_clients",alias="rentall-hyperv"}`;
- CPU, memory, disks, physical disks, network, OS, service, system, TCP, process;
- Hyper-V VM metrics from `windows_exporter` Hyper-V collector;
- custom Hyper-V VM state and uptime from `windows_custom_hyperv_vm_state` and `windows_custom_hyperv_vm_uptime_seconds`;
- custom watched service state from `windows_custom_service_desired_running`;
- custom backup path and Windows Backup event metrics.

Watched VMs:

- `buh`;
- `mikrotik`.

Watched backup path:

```text
D:\Backup
```

Watched services include:

- `vmms`;
- `vmcompute`;
- `MSSQLSERVER`;
- `MSSQL$RENTALLMSSQL`;
- `SQLBrowser`;
- `SQLWriter`;
- `Firebird server - ZvitGrp`;
- `ZvitGrp`;
- `TermService`;
- `SessionEnv`;
- `UmRdpService`;
- `CloudBackupRestoreSvc_43429c`.

Backup note:

- During initial inspection, Windows Backup reported VSS failure event `521` / `0x8100010C` on 2026-05-23.
- The custom exporter collects latest backup success timestamp, latest failure timestamp and latest failure event ID.

### `rentall-rdp`

Address:

```text
192.168.112.19:9182
```

Observed host identity:

- hostname: `WIN-7N65LE8EF7H`;
- OS: Windows Server 2016 Standard Evaluation;
- role: RDP server and 1C server.

Collected metrics:

- host availability: `up{job="windows_exporter_clients",alias="rentall-rdp"}`;
- CPU, memory, disks, physical disks, network, OS, service, system, TCP, process;
- custom watched service state from `windows_custom_service_desired_running`.

Watched services:

- `TermService`;
- `SessionEnv`;
- `UmRdpService`;
- `Spooler`;
- `VSS`;
- `vmicvss`.

No backup path is currently watched on this VM.

## Planned Backup Work

The current production monitoring watches existing backup signals where they are available, but the following backup automation still needs to be implemented:

- configure automatic cloud backups for M.E.Doc data on `192.168.112.20`;
- configure automatic cloud backups for 1C data on `192.168.112.19`;
- expose M.E.Doc and 1C backup freshness, size, exit status and destination availability as Prometheus metrics;
- configure VM-level backups on the Hyper-V host `192.168.112.20` for both VMs: `192.168.112.19` and `192.168.112.1`;
- expose Hyper-V VM backup freshness, last result, backup size and storage free space as Prometheus metrics;
- add Grafana panels and alerts after the backup jobs and metric files are stable.

## MikroTik Monitoring

The primary MikroTik is a VM on the Hyper-V host.

Address:

```text
192.168.112.1
```

The second MikroTik is the office router. The office LAN is behind it:

```text
office MikroTik: 192.168.1.1
office LAN:     192.168.1.0/24
```

VPN routing is arranged so these two networks can reach each other through the VPN server on `192.168.112.1`:

```text
192.168.112.0/24 <-> VPN server 192.168.112.1 <-> 192.168.1.0/24
```

`con` keeps a route for the office subnet:

```bash
ip route replace 192.168.1.0/24 via 192.168.112.1 dev ppp0
```

Prometheus does not poll RouterOS SNMP directly. It scrapes `snmp_exporter` on `con`, and `snmp_exporter` polls MikroTik through the VPN:

```text
Prometheus -> snmp_exporter on con -> VPN -> MikroTik 192.168.112.1 UDP/161
```

Current target:

```yaml
- targets:
    - 192.168.112.1
  labels:
    alias: rentall-mikrotik
    company: rentall
    workspace: rentoll
    role: router
    parent_host: rentall-hyperv
- targets:
    - 192.168.1.1
  labels:
    alias: rentall-mikrotik-remote
    company: rentall
    workspace: rentoll
    role: router
    parent_host: rentall-mikrotik
```

MikroTik SNMP is restricted to the VPN source address:

```text
192.168.112.18/32
```

## Dashboards

Rentall summary dashboard:

```text
https://grafana.exemstsc.world/d/rentall-overview/rentall-overview
```

Windows dashboard:

```text
https://grafana.exemstsc.world/d/windows-server-2019/windows-server-2019
```

Dashboard title:

```text
Windows Server / Hyper-V
```

The Rentall summary dashboard includes a dedicated RDP activity section for `192.168.112.19`. It is based on `quser` output collected into Prometheus metrics:

- `windows_custom_rdp_session_idle_seconds`;
- `windows_custom_rdp_session_last_input_timestamp_seconds`;
- `windows_custom_rdp_session_logon_timestamp_seconds`;
- `windows_custom_rdp_session_active`.

Use the `RDP Last Activity Time` and `RDP Idle Time` panels before rebooting the RDP / 1C VM. An active session with low idle time means a user is likely using the server; a disconnected or long-idle session is safer to coordinate for reboot.

MikroTik dashboard:

```text
https://grafana.exemstsc.world/d/mikrotik-router/mikrotik-router
```

## Alerts

Grafana alert rules are provisioned in:

```text
monitoring/grafana/provisioning/alerting/immediate-infrastructure-alerts.yml
```

Relevant Windows rules:

- `windows-exporter-down`: `windows_exporter` cannot be scraped;
- `windows-watched-service-down`: a watched Windows service is missing or not running;
- `windows-hyperv-vm-not-running`: a discovered Hyper-V VM is not running;
- `windows-backup-path-unavailable`: watched backup path cannot be listed for 30 minutes;
- `windows-backup-stale`: watched backup path has no new files for the configured stale window.

Alert routing uses labels such as:

```text
workspace=rentoll
company=rentall
alias=rentall-hyperv
alias=rentall-rdp
```

## Operational Checks

Check VPN on `con`:

```bash
ip -br addr show ppp0
ping -c 2 192.168.112.1
ping -c 2 192.168.1.1
ping -c 2 192.168.112.20
ping -c 2 192.168.112.19
```

Check Windows exporter from `con`:

```bash
curl -fsS http://192.168.112.20:9182/metrics | grep '^windows_custom_' | head
curl -fsS http://192.168.112.19:9182/metrics | grep '^windows_custom_' | head
```

Check Prometheus targets:

```bash
curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up{job="windows_exporter_clients"}' | jq
```

Apply target changes:

```bash
cp monitoring/prometheus/file_sd/windows_targets.yml /root/monitoring/prometheus/file_sd/windows_targets.yml
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill -s HUP monitoring-prometheus
```
