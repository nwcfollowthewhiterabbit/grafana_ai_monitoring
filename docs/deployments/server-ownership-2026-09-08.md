# Owner-confirmed server classification — 2026-09-08

Status: catalog implemented and locally validated; live application pending.

## Scope

The owner asked to apply the server/customer map using the existing monitoring
inventory. `monitoring/service-catalog.yml` remains the sole managed catalog;
Grafana is its presentation, not a second source of ownership decisions.

- Greenleaf: `cloud` production; `testing` a separate test server, with the
  existing technical role `staging` retained. Moving outdated/unreliable websites
  there is future work; no application has been moved in this update.
- Rabbit infrastructure: existing `con`/`deployment`, plus newly registered
  `con2`/`voice`. Physical host ownership and application/customer ownership
  must not be inferred from one another.
- SeedQuest: newly registered `seedquest`, customer production.
- MB Skolas: newly registered `wherp`, customer ERP production.
- HOW: existing `howbot`/`payroll` production. Catalog display names corrected;
  stable ID and metric label `rentall` remain unchanged. This does not rename
  other legacy Rentall/Windows/VPN resources or establish their legal ownership.

The four new host entries are `pending_discovery`, monitoring disabled,
`customer_visible=false`, applications empty. No endpoints, credentials or
accounts are added. Customer visibility is metadata, **not** an authorization
boundary; existing datasource/proxy restrictions remain necessary and unchanged.
Old `new`/`test` entries are preserved rather than renamed, removed or equated
with similarly named hosts.

## Verification

- Strict catalog: **passed**, 5 companies / 12 servers / 43 applications /
  72 components / 13 HTTP services / 0 service events.
- Six focused ownership regression tests: **passed**; previous application
  placement, old metric labels, unchanged generated HTTP targets, disabled
  discovery entries and no new customer exposure in metadata.
- Full `tests/` suite: **passed**, 36 tests.
- Incident gateway suite: **passed**, 36 tests (including loopback HTTP fixtures
  after an approved rerun outside the network-restricted sandbox).
- Generated dashboards: no drift; all 29 JSON files valid. Full local validation
  stopped at Docker configuration checks because the local Docker daemon is
  absent; containerized checks are **not_run** locally, not a claimed pass.
- Generated HTTP target file: **unchanged**, renderer `--check` passed.
- `git diff --check`: **passed**.
- Live application and Prometheus readback: **not_run** at this checkpoint.

## Bounded application

Before applying, verify the exact clean `/opt/rabbit-monitoring-v2` checkout on
`deployment` and retain its previous catalog/revision. Fast-forward only to the
reviewed change, validate again, then start the **existing**
`service-event-metrics.service`. It renders inventory into the already scraped
textfile; no new service, timer, exporter, scrape configuration or client access
is needed. Do not run the broader deployment renderer for this metadata change.

Read back 12 inventory servers and `UNKNOWN` (-1) for the four uninspected hosts.
Check existing scrape identities and configuration remain unchanged. This does
not claim those hosts are monitored, SSO is connected, or platform DB/UI inventory
import is implemented. Grafana selectors still use historical metric labels.
