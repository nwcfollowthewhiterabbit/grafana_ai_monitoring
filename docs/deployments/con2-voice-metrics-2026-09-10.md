# Rabbit con2 / voice host metrics

Owner authorized host telemetry on both existing Rabbit Contabo VPS on 2026-09-10.
Application stacks were not recreated, reconfigured or automatically catalogued.

- `con2`: 169.58.53.13; `voice`: 109.205.177.191.
- Dedicated `/etc/rabbit-host-metrics/compose.yml` uses the existing immutable
  node-exporter 1.9.1 image digest from deployment, non-root, read-only root,
  no capabilities, no Docker socket, resource/log limits and host proc/rootfs
  read access. Metrics listen **only** at `127.0.0.1:19100`.
- A separate key is generated on each source host and never copied. Root-only
  config directory; pinned deployment Ed25519 host key read over admin SSH.
- `rabbit-host-metrics-relay@con2` / `@voice` systemd services forward respectively
  to `172.23.0.1:19130` / `:19131` on deployment's monitoring bridge.
- Dedicated destination accounts `monitoring-con2` / `monitoring-voice` accept
  source-IP-restricted keys, exact PermitListen sockets, reverse forwarding
  only; no sessions, password login, PTY, agent/X11 or local forwarding.
  `/etc/ssh/sshd_config.d/61-rabbit-host-metrics.conf` validated before SSH reload.
- Existing `node_exporter_clients` job gains two targets with exact
  `company="my own"`, aliases con2/voice. Renderer preserves scrape identities.
  Running Prometheus config was changed only for these targets/transports,
  validated with promtool, then HUP-reloaded, not restarted. Backup:
  `/etc/rabbit-monitoring/prometheus/prometheus.before-con2-voice-20260910.yml`.
- Existing service-event-metrics service regenerated the canonical inventory
  after changing observed hosts to active. Workload discovery remains incomplete.
  Raw CPU, memory, root filesystem metrics and exporter `up=1` verified.

Do not expose these ports publicly or reuse relay credentials for agent SSH.
To disconnect, remove/reload exact Prometheus targets first, then stop the
corresponding relay/exporter and revoke that dedicated key/account. Preserve
other monitoring sockets and source application containers. No automated cleanup
or rollback was performed. Host IP catalog metadata is display/search data, not
authority to reassign a provider instance or remotely execute commands.
