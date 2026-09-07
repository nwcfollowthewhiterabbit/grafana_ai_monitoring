# Rabbit Systems Managed Monitoring

Managed monitoring for Rabbit Systems infrastructure and customer services.

## Managed Monitoring v2

The repository contains the Managed Monitoring v2 implementation: hierarchical inventory and generated targets, operational admin/customer dashboards, Prometheus and Alertmanager rules, and a stateful SQLite incident gateway. The gateway is outbound-only to Telegram, persists incident transitions before responding, and enforces DOWN then Recovery ordering.

The v2 Alertmanager/gateway pair was integrated into the existing `monitoring` Compose project on `con` and cut over to live delivery on 2026-09-07. OpenClaw remains the Telegram webhook owner, while its legacy Grafana notification processing is paused to prevent duplicate sends. See:

- `docs/deployments/con-integrated-compose.md` for the active production file set, verified state and rollback;
- `docs/managed-monitoring-v2-architecture.md` for the model, guarantees, audited baseline and boundaries;
- `docs/managed-monitoring-v2-runbook.md` for validation, shadow deployment, canary, cutover and rollback;
- `services/incident-gateway/README.md` for the implemented gateway contract.

## Production topology

```text
service catalog + exporters + HTTP/integrity checks + service-event scheduler
                                  │
                                  ▼
                              Prometheus
                         rules + recording rules
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
                Grafana                    Alertmanager
          admin/customer views          grouping + inhibition
                                                │
                                                ▼
                                    incident gateway + SQLite
                                      DOWN → Recovery outbox
                                                │
                                                ▼
                                      Telegram via sendMessage

legacy Grafana → OpenClaw alert processing: PAUSED (rollback path retained)
OpenClaw → Telegram inbound webhook: ACTIVE
```

| Concern | Production source of truth |
| --- | --- |
| Inventory hierarchy | `monitoring/service-catalog.yml` |
| Health and alert evaluation | Prometheus on `con` |
| Incident lifecycle and delivery | `/var/lib/rabbit-monitoring-v2/incident-gateway/incidents.db` |
| Admin UI | Grafana org 1 |
| Greenleaf customer UI | Grafana org 2 through the enforced `company=greenleaf` proxy |
| Notifications | Alertmanager → incident gateway → existing Telegram bot/topic |
| Deployment | `/root/monitoring/docker-compose.yml` plus both `deploy/con-monitoring-v2.*.yml` layers |
| Rollback | Restore OpenClaw Grafana processing only after returning the gateway to shadow |

The current deployment and verification evidence are recorded in `docs/deployments/con-integrated-compose.md`. `deploy/con-shadow-compose.yml` is retained only as rollout history and an isolated rollback/test layout; it is not the active production project.

## Managed inventory

The validated catalog currently contains 3 companies, 7 servers, 41 applications, 67 components and 13 public HTTP services.

| Company ID | Server IDs |
| --- | --- |
| greenleaf | cloud, testing, new |
| rentall | payroll, howbot |
| my-own | test, con |

## Files

- `ROADMAP.md` - deployed baseline, immediate remediation and sequenced product backlog.
- `monitoring/prometheus/prometheus.yml` - Prometheus scrape config.
- `monitoring/prometheus/rules/` - Prometheus alert rules for node, cAdvisor, disk, memory, container state, and stale stack metrics.
- `monitoring/blackbox/config.yml` - Blackbox Exporter HTTP probe configuration.
- `monitoring/service-catalog.yml` - service inventory, public endpoints, and pending discovery list.
- `monitoring/alloy/config.template.alloy` - future Grafana Alloy collector template for OpenTelemetry-ready collection.
- `monitoring/promtail/config.template.yml` - Docker log collection template for client nodes.
- `monitoring/grafana/provisioning/dashboards/` - Grafana dashboard provisioning.
- `monitoring/grafana/provisioning/datasources/` - Grafana datasource provisioning.
- `monitoring/docker-compose.yml` - repository full-stack Compose reference; the drift-preserving live `con` base is `/root/monitoring/docker-compose.yml` plus the two v2 deployment layers.
- `scripts/cloud-backup-metrics.sh` - `cloud` backup health exporter for node_exporter textfile collection.
- `scripts/cloud-run-daily-backups.sh` - corrected `cloud` daily backup wrapper for all non-ERP stacks.
- `scripts/scheduled-public-site-checker.py` - queued, retrying public HTTP checker that provides independent supporting evidence; production `PublicSiteDown` is evaluated from sustained Blackbox failures.
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
- `docs/deployments/con-shadow-2026-09-07.md` - historical shadow deployment and findings carried into cutover.
- `docs/deployments/con-integrated-compose.md` - current production file set, applied migration evidence and rollback.
- `docs/deployments/deployment-shadow-2026-09-07.md` - isolated, credential-free shadow stage on the future deployment host; production routing remains on `con`.
- `deploy/con-monitoring-v2.override.yml` - shadow-by-default integrated Alertmanager/gateway override; no build or existing-service definitions.
- `deploy/con-monitoring-v2.live.yml` - mandatory final layer for live gateway delivery; omitting it returns the gateway to shadow mode.
- `deploy/openclaw-grafana-paused.override.yml` - required OpenClaw API layer for as long as the gateway is authoritative; omitting it re-enables the legacy sender.
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
- Managed Monitoring v2 evaluates a sustained high-frequency Blackbox window
  for production availability. The independent queued checker runs every 3
  hours, limits concurrency, retries initially failed URLs 3 more times 5
  minutes apart, and exposes supporting confirmed-down evidence only after at
  least 3 failed attempts in that cycle. It is not the source of the
  `PublicSiteDown` alert.
- The independent site-integrity checker runs twice daily and looks for explicit
  failure evidence such as empty/error pages and failed critical resources. It
  does not compare normal content with a saved page.
- `test` is behind NAT and is monitored through a reverse SSH tunnel:
  `test:127.0.0.1:9100 -> con:172.17.0.1:19100`.
- `con` is monitored locally through compose services `node-exporter-con`
  and `cadvisor-con`; its Docker stack metrics are exported through the
  node_exporter textfile collector.
- `new` is currently configured in Prometheus but remains down until `node_exporter`
  is installed/listening on `139.99.171.55:9100` and the host is reachable.
- Grafana-managed alert rules are provisioned in
  `monitoring/grafana/provisioning/alerting/immediate-infrastructure-alerts.yml`.
  Their existing OpenClaw webhook route is retained for rollback, but OpenClaw
  processing is paused while the v2 Alertmanager/gateway route is authoritative.

## Apply

On `con`, Prometheus reads:

```bash
/root/monitoring/prometheus/prometheus.yml
```

Live Compose operations must retain the integrated file set:

```bash
docker compose --project-name monitoring --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml
```

See `docs/deployments/con-integrated-compose.md` before recreating Alertmanager, the gateway or the whole project. Do not use the base file alone with `--remove-orphans`.

OpenClaw has a separate but equally important invariant: while the gateway is
live, every OpenClaw API recreate must layer
`deploy/openclaw-grafana-paused.override.yml` over `/opt/helper/docker-compose.yml`.
A base-only recreate re-enables the legacy Grafana sender and can duplicate
Telegram notifications.

Grafana reads provisioning from:

```bash
/root/monitoring/grafana/provisioning
```

After changing Prometheus config:

```bash
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill --signal HUP monitoring-prometheus
```

The same validated HUP reload applies after changing an already-mounted alert
rule. If a Compose mount or service definition itself changes, recreate only the
affected service with the complete production file set:

```bash
docker compose --project-name monitoring --project-directory /root/monitoring \
  -f /root/monitoring/docker-compose.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.override.yml \
  -f /opt/rabbit-monitoring-v2/deploy/con-monitoring-v2.live.yml \
  up -d prometheus
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
