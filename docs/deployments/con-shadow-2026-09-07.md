# con shadow deployment — 2026-09-07

Managed Monitoring v2 was deployed on `con` from commit `6ccc290` in shadow mode. This record contains no credentials.

Status: historical. The shadow project was replaced by the integrated live deployment recorded in `docs/deployments/con-integrated-compose.md`; its bind-mounted state was preserved.

## Applied scope

- Checkout: `/opt/rabbit-monitoring-v2`.
- Added isolated Compose project `rabbit-monitoring-v2-shadow` with Alertmanager 0.33.1 and the SQLite incident gateway.
- Reused the existing Prometheus, Grafana, Loki and exporters. No second TSDB or Loki was started.
- Gateway and Alertmanager publish only on loopback and join the existing private `monitoring_default` network.
- Gateway uses the OpenClaw Telegram bot credentials through read-only secret files, but `GATEWAY_MODE=shadow` creates no notification outbox and cannot send a message.
- Installed availability, site-integrity and service-event systemd timers. The first integrity cycle checked 13 targets and reported zero current problems.
- Loaded four validated Prometheus rule files and the generated HTTP `file_sd` inventory. Alertmanager and gateway scrape targets were both `up` after reload.
- Provisioned three admin dashboards in Grafana org 1 and three Greenleaf customer dashboards in org 2.

The firing → duplicate firing → resolved smoke test produced one incident, one firing event, one resolved event and zero outbox rows. At that historical stage the production Telegram route had not been tested or cut over, and the legacy Grafana/OpenClaw route was authoritative.

## Preserved state and rollback evidence

- The existing `/root/monitoring` data volumes were retained.
- Pre-change Prometheus config/rules: `/var/backups/rabbit-monitoring-v2/pre-prometheus-70cab6a`.
- Pre-change scheduled-checker units: `/var/backups/rabbit-monitoring-v2/pre-v2-70cab6a`.
- Shadow data: `/var/lib/rabbit-monitoring-v2`; initial usage was about 520 KiB.
- The live server-only Blackbox and Loki configurations were not overwritten.
- The OpenClaw checkout at `/opt/helper` was inspected but not modified.

Use the main rollout runbook for routing rollback. Do not delete the incident database as part of rollback.

## Observed blockers before notification cutover

- Root filesystem was 95% used with about 4.0 GiB free. The shadow pair was
  small, but a parallel Prometheus/Loki deployment was blocked.
- Ten scrape targets were down. `rentall-vpn.service` had been failed since
  2026-08-31, which explained the Windows/MikroTik path failures observed then.
- Greenleaf `cloud` node metrics were reachable, but cAdvisor and Docker
  inventory metrics were absent. Thirteen expected Greenleaf components
  therefore remained unconfirmed.
- Backup metrics were absent/stale and correctly produced non-green shadow evidence.
- The service-event registry deliberately contained zero entries because real
  domain/subscription dates and owners had not been verified.
- Open incidents created in shadow would not be replayed when switching to live;
  they had to be reconciled before the controlled cutover.

These findings were carried into the controlled cutover record instead of being discarded or replayed as new Telegram incidents.

## Subsequent transition

Commit `1e84d41` added `deploy/con-monitoring-v2.override.yml`, the explicit live opt-in and the reversible OpenClaw sender pause. On 2026-09-07 the pair moved into project `monitoring`; the stopped shadow containers were removed without volumes, and the same `/var/lib/rabbit-monitoring-v2` state continued in live generation 2. See `docs/deployments/con-integrated-compose.md` for verification and rollback evidence.
