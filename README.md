# Rabbit Systems Managed Monitoring

Managed monitoring for Rabbit Systems infrastructure and customer services.

## Managed Monitoring v2

The repository contains the Managed Monitoring v2 implementation: hierarchical inventory and generated targets, operational admin/customer dashboards, Prometheus and Alertmanager rules, and a stateful SQLite incident gateway. The gateway is outbound-only to Telegram, persists incident transitions before responding, and enforces DOWN then Recovery ordering.

The central monitoring services and their existing data moved from `con` to `deployment` on 2026-09-08. Prometheus, Grafana, Loki, Alertmanager and the sole live incident gateway run in project `monitoring`; local collectors on `con` use a private SSH relay. OpenClaw remains the Telegram webhook owner on `con`, with legacy Grafana notification processing paused. See:

- `docs/deployments/deployment-production-2026-09-08.md` for the active production layout, verification and rollback;
- `docs/deployments/con-integrated-compose.md` for the historical first cutover on `con`;
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
| Health and alert evaluation | Prometheus on `deployment` |
| Incident lifecycle and delivery | `/var/lib/rabbit-monitoring-v2/incident-gateway/incidents.db` on `deployment` |
| Admin UI | Grafana org 1 |
| Greenleaf customer UI | Grafana org 2 through the enforced `company=greenleaf` proxy |
| Notifications | Alertmanager → incident gateway → existing Telegram bot/topic |
| Deployment | `deploy/deployment-monitoring-compose.yml` plus private `/etc/rabbit-monitoring/release.env` |
| Rollback | Stop destination sender; reconcile latest state and the matching schema/image before restoring a source sender |

The current deployment and verification evidence are recorded in `docs/deployments/deployment-production-2026-09-08.md`. The shadow and old `con` central containers are stopped; their data remains available for rollback. The original Grafana URL and authenticated collector ingestion URLs continue through Nginx on `con` and the private relay.

## Managed inventory

The validated catalog currently contains 5 companies, 12 servers, 43 applications,
72 components and 13 public HTTP services. The four newly registered servers
are `pending_discovery`, with monitoring disabled and no invented workloads or
scrape targets; registration is not proof of health.

| Company ID | Server IDs |
| --- | --- |
| greenleaf | cloud, testing, new |
| rentall (display name: HOW Production; historical metric label retained) | payroll, howbot |
| my-own | test, con, deployment, con2, voice |
| seedquest | seedquest |
| mb-skolas | wherp |

Owner-confirmed on 2026-09-08: `cloud` is Greenleaf production; `testing` is its
separate test server and intended future destination for outdated/unreliable
websites. No site migration is implied or performed by this catalog update.
Rabbit infrastructure ownership does not make every hosted customer application
Rabbit-owned. Existing `new` and `test` entries remain pending clarification.
Grafana's metric-based selectors still show legacy `rentall`; display metadata
does not rename time series, alter client access or merge customer scopes.
See [application and verification record](docs/deployments/server-ownership-2026-09-08.md).

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
- `monitoring/docker-compose.yml` - historical full-stack reference; production now uses `deploy/deployment-monitoring-compose.yml`.
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
- `docs/deployments/con-integrated-compose.md` - historical `con` integration and original rollback evidence.
- `docs/deployments/deployment-production-2026-09-08.md` - current central deployment, private relay, persisted data and verification.
- `docs/deployments/deployment-shadow-2026-09-07.md` - historical credential-free staging before the completed migration.
- `scripts/render-deployment-monitoring.py` - deployment scrape transport with preserved exporter instance identities.
- `deploy/con-monitoring-v2.override.yml` - historical con Alertmanager/gateway override; its service definitions are also reused by the new deployment Compose.
- `deploy/con-monitoring-v2.live.yml` - historical con live layer; active deployment selects live mode through its private `release.env`.
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
- `con` retains compose services `node-exporter-con` and `cadvisor-con`; the
  central Prometheus on `deployment` reaches them through the private relay.
  Both hosts publish local Docker stack metrics through node_exporter textfiles.
- `new` is currently configured in Prometheus but remains down until `node_exporter`
  is installed/listening on `139.99.171.55:9100` and the host is reachable.
- Grafana-managed alert rules are provisioned in
  `monitoring/grafana/provisioning/alerting/immediate-infrastructure-alerts.yml`.
  Their existing OpenClaw webhook route is retained for rollback, but OpenClaw
  processing is paused while the v2 Alertmanager/gateway route is authoritative.

## Apply

Run central operations on `deployment`, using the reviewed source checkout at
`/opt/rabbit-monitoring-v2`. The runtime configuration is `/etc/rabbit-monitoring`.

```sh
docker compose --env-file /etc/rabbit-monitoring/release.env \
  -f /opt/rabbit-monitoring-v2/deploy/deployment-monitoring-compose.yml ps
```

Use the same prefix with an explicit service for changes. The release file pins
the reviewed gateway image and `live` mode. After config/dashboard updates:

```sh
python3 /opt/rabbit-monitoring-v2/scripts/render-deployment-monitoring.py
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill --signal HUP monitoring-prometheus
```

Regenerate catalog textfiles with `systemctl start service-event-metrics.service`.
Checker timers run on `deployment`. Keep `/var/lib/node-exporter-textfile` mode
0755 and completed `.prom` files readable by node-exporter.

See the current deployment record before image/database upgrades or rollback.
Do not restart the stopped central stack on `con`. OpenClaw API changes there
must still include `deploy/openclaw-grafana-paused.override.yml` over
`/opt/helper/docker-compose.yml`; only the gateway owns live monitoring delivery.
