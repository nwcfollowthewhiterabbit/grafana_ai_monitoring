# Home FPC physical-host monitoring

The owner requested Rabbit Platform enrollment and monitoring on 2026-09-27.
The catalog identity is `my-own:fpc`, alias `fpc`, Rabbit workspace `ws-rabbit`.
This is the physical Windows host, not the separate WSL environment or Codex
Runner. No Contabo identity or inferred application inventory is attached.

## Installed source

On 2026-09-27 the reviewed `scripts/windows/install-home-exporter.ps1` installed
the official Windows exporter **0.31.8** executable as service
`windows_exporter`, automatic startup and bounded restart recovery. It binds
only **127.0.0.1:9182**. No Windows firewall, WinRM or router rule was changed.
Collectors are `cpu,memory,logical_disk,system`, with logical disks `C:` and `M:`;
no process list, user sessions, event-log collector or application logs are sent.
Files are under `C:\ProgramData\RabbitMonitoring`, writable only by SYSTEM and
Administrators. The binary runs as the normal SYSTEM Windows service account.

The official pinned release artifact is
[windows_exporter-0.31.8-amd64.exe](https://github.com/prometheus-community/windows_exporter/releases/download/v0.31.8/windows_exporter-0.31.8-amd64.exe),
SHA256 `03bb0fe80b8ad0b4e39606b96c4c5cc56b1f766760011ea2b00111157c6ef077`.
The installer verified that digest after download and checked the actual listener
and CPU/memory/disk output. Both PowerShell files passed Windows PowerShell parser
validation on FPC. No runtime policy was disabled.

The bounded live receipt at **2026-09-27T12:15:21Z** showed 16 logical CPUs,
33,158,033,408 bytes of usable physical RAM, and M: capacity
1,675,677,925,376 bytes with 986,848,428,032 bytes free. These are an observation,
not allocation guarantees. Windows logical-disk size/free performance counters
can lag 10–15 minutes even when Prometheus scrapes are current.

## Private outbound transport

`configure-home-metrics-relay.ps1 -Mode Prepare` generated a dedicated Ed25519
key on FPC; its private part stays there. Deployment's public host key was
verified through existing authenticated SSH and pinned. The dedicated destination
is `monitoring-fpc@169.58.132.8`, exact private listener `172.23.0.1:19132`, source
`127.0.0.1:9182`. This uses the existing monitoring bridge and reverse-SSH pattern;
no public exporter or new infrastructure service is needed.

At this checkpoint the relay is **prepared, not started** and destination
enrollment is **not applied**. The Windows task does not yet exist. After the
destination account is reviewed and installed, `-Mode Start` registers
`Rabbit-Home-Metrics-Relay` under SYSTEM at startup with reconnects. It works
without the Mac. The key permits only this remote listener; destination policy
denies sessions, local forwarding, password/interactive login, PTY and agent/X11.

`scripts/enroll-home-fpc-monitoring.py prepare` creates private preimages and
candidate files on deployment; `apply` requires the exact reviewed plan hash and
unchanged preimages. It adds only `/etc/ssh/sshd_config.d/62-home-fpc.conf`, the
dedicated account/key, one Windows `file_sd` target and its exact private relay
mapping, and the `managed-windows-host` admin dashboard. SSH and Prometheus are
validated before reload/HUP; no application container or database is restarted.
The prior `61-rabbit-host-metrics.conf` stays unchanged. If a late apply step
fails, only its unchanged candidates are restored and the new key is disabled;
the inert account and private receipts stay for reconciliation.

Prepare needs the exact existing Prometheus container name and dashboard source:

```sh
sudo python3 scripts/enroll-home-fpc-monitoring.py prepare \
  --state /opt/release-staging/home-fpc-monitoring-20260927 \
  --dashboard monitoring/grafana/provisioning/dashboards/managed-windows-host.json \
  --prometheus-container REVIEWED_EXISTING_CONTAINER
```

Do not infer completion from the prepared catalog or service state. Acceptance
requires the private destination socket, exact `up{job="windows_exporter_clients",
company="my own",alias="fpc"}=1`, the bounded Platform read through its existing
private metrics proxy, and authenticated server-card rendering. Existing
WindowsExporterDown alert routing is reused; no new notification destination,
GPU collector or CPU/memory resource alert is introduced by this slice.

## Platform contract and disconnection

The catalog carries `metrics_profile: {kind: windows_exporter, filesystem: 'M:'}`.
The Platform's fixed Windows profile keeps exact company/alias filtering,
duplicate/stale/down rejection and bounded queries; no browser controls a scrape
address, query or drive selector. Legacy Linux profiles still mean `/`. The
historical `root_bytes/root_percent` fields now include a `filesystem` qualifier;
the card reads **Диск M:** and exposes the counter-delay hint. This is not total
disk capacity, WSL RAM, a RAM limit or Runner health. Grafana links use the scoped
generic Windows host dashboard. Client dashboards/access are not changed.

To disconnect after an explicit operational decision: stop the FPC relay task,
remove only its target/relabel and HUP Prometheus, revoke the dedicated key, then
disable the exporter if desired. Preserve time-series history and preimages.
Do not revert entire Prometheus/SSH files over newer unrelated edits. Source
shutdown should naturally turn fresh observations into unavailable/stale state;
it must not keep a green card or manufacture zero resource usage.
