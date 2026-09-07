# Grafana AI Monitoring

Prometheus and Grafana provisioning for client server monitoring.

## Managed Monitoring v2

The repository now contains a deployable v2 foundation: hierarchical inventory and generated targets, operational admin/customer dashboards, Prometheus and Alertmanager rules, a stateful SQLite incident gateway, and an isolated shadow Compose deployment. The gateway is outbound-only to Telegram, persists incident transitions before responding, and enforces DOWN then Recovery ordering.

This repository state is ready for validation and shadow operation; it does not by itself mean production notifications have been cut over. Until the rollout gates are completed, the legacy monitoring/OpenClaw route remains authoritative. See:

- `docs/managed-monitoring-v2-architecture.md` for the model, guarantees, audited baseline and boundaries;
- `docs/managed-monitoring-v2-runbook.md` for validation, shadow deployment, canary, cutover and rollback;
- `services/incident-gateway/README.md` for the implemented gateway contract.

## Current Segments

| Company | Nodes |
| --- | --- |
| greenleaf | cloud, testing, new |
| rentall | payroll, howbot |
| my own | test, con |

## Files

- `monitoring/prometheus/prometheus.yml` - Prometheus scrape config.
- `monitoring/prometheus/rules/` - Prometheus alert rules for node, cAdvisor, disk, memory, container state, and stale stack metrics.
- `monitoring/blackbox/config.yml` - Blackbox Exporter HTTP probe configuration.
- `monitoring/service-catalog.yml` - service inventory, public endpoints, and pending discovery list.
- `monitoring/alloy/config.template.alloy` - future Grafana Alloy collector template for OpenTelemetry-ready collection.
- `monitoring/promtail/config.template.yml` - Docker log collection template for client nodes.
- `monitoring/grafana/provisioning/dashboards/` - Grafana dashboard provisioning.
- `monitoring/grafana/provisioning/datasources/` - Grafana datasource provisioning.
- `monitoring/docker-compose.yml` - monitoring stack compose file used on `con`.
- `scripts/cloud-backup-metrics.sh` - `cloud` backup health exporter for node_exporter textfile collection.
- `scripts/cloud-run-daily-backups.sh` - corrected `cloud` daily backup wrapper for all non-ERP stacks.
- `scripts/scheduled-public-site-checker.py` - queued public HTTP checker for large endpoint lists and confirmed-down alerting.
- `scripts/windows/` - Windows install and textfile metric scripts for services, Hyper-V VMs, and backups.
- `systemd/cloud-backup-metrics.*` - timer for the `cloud` backup health exporter.
- `systemd/prometheus-test-tunnel.service` - persistent reverse SSH tunnel from `test` to `con`.
- `systemd/rentall-vpn.service` - Rentall L2TP/IPsec VPN bootstrap service on `con`.
- `docs/windows-monitoring-playbook.md` - generic playbook for adding Windows machines to monitoring.
- `docs/windows-production-monitoring.md` - current production implementation for Rentall Windows, Hyper-V, RDP VM and MikroTik monitoring.
- `docs/windows-2019-monitoring.md` - legacy combined Windows / Hyper-V / MikroTik runbook retained for compatibility.
- `docs/greenleaf-public-monitoring.md` - Greenleaf public Caddy endpoint monitoring scope and apply procedure.
- `docs/company-grafana-access.md` - read-only company-scoped Grafana access model.
- `docs/managed-monitoring-v2-architecture.md` - v2 architecture, incident lifecycle, isolation and deployment boundaries.
- `docs/managed-monitoring-v2-runbook.md` - staged validation, shadow, canary, cutover and rollback procedure.
- `docs/deployments/con-shadow-2026-09-07.md` - applied shadow deployment record and current cutover blockers.
- `services/incident-gateway/` - SQLite-backed Alertmanager-to-Telegram incident gateway.

## Runtime Notes

- Greenleaf `cloud` public endpoints are expected to be served by repo-managed
  Caddy on the production server. Public HTTP checks in
  `monitoring/prometheus/prometheus.yml` should match the active
  `monitoring/service-catalog.yml` entries and the production source of truth
  in `greenleaf_cloud-server:ops/public-sites.yml`.
- Greenleaf `cloud` exporters are scraped by direct origin IP
  `139.99.155.118`, not by `cloud.greenleafpacific.com`, because that hostname
  is a public website route and may be Cloudflare/proxy managed.
- Current Greenleaf `cloud` public blackbox scope is 13 HTTPS endpoints:
  Nextcloud, main site, ERP, CGI, SG, SPA, Furniture, Pacific Cleaning,
  Fiji Pacific Cleaning, Bulataxi, and the three testing storefront/ERP URLs.
- The legacy production Grafana route uses the queued scheduled checker, not raw
  Blackbox probe flaps. Managed Monitoring v2 also evaluates a sustained
  high-frequency Blackbox window in shadow so the two signals can be compared
  before notification cutover. The queued checker runs every 3 hours, limits concurrency, retries
  initially failed URLs 3 more times 5 minutes apart, and alerts only after at
  least 3 failed attempts in that cycle.
- `test` is behind NAT and is monitored through a reverse SSH tunnel:
  `test:127.0.0.1:9100 -> con:172.17.0.1:19100`.
- `con` is monitored locally through compose services `node-exporter-con`
  and `cadvisor-con`; its Docker stack metrics are exported through the
  node_exporter textfile collector.
- `new` is currently configured in Prometheus but remains down until `node_exporter`
  is installed/listening on `139.99.171.55:9100` and the host is reachable.
- Grafana-managed alert rules are provisioned in
  `monitoring/grafana/provisioning/alerting/immediate-infrastructure-alerts.yml`.
  A real contact point still needs Telegram, email/SMTP, Slack, or webhook
  credentials before notifications can be delivered.

## Apply

On `con`, Prometheus reads:

```bash
/root/monitoring/prometheus/prometheus.yml
```

Grafana reads provisioning from:

```bash
/root/monitoring/grafana/provisioning
```

After changing Prometheus config:

```bash
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose restart prometheus
```

After changing alert rules or compose mounts:

```bash
docker compose up -d prometheus
```

After changing the scheduled public site checker:

```bash
sudo systemctl daemon-reload
sudo systemctl restart scheduled-public-site-checker.service
sudo systemctl enable --now scheduled-public-site-checker.timer
```

After changing dashboard provisioning:

```bash
docker restart monitoring-grafana
```
