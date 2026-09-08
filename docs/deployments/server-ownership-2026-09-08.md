# Owner-confirmed server classification — 2026-09-08

Status: applied on deployment and verified through Prometheus on 2026-09-08.

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
- HOW Production (owner explicitly confirmed this is `rentall`): existing
  `howbot`/`payroll` production. Catalog display names corrected;
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
- Full [CI for f0d4a26](https://github.com/nwcfollowthewhiterabbit/grafana_ai_monitoring/actions/runs/34270524643):
  **passed**, including Docker configuration, promtool rule fixtures and amtool.
- Live catalog application: **passed**, `f0d4a268c612987938498d84f7e9882b1ca79327`
  fast-forwarded from clean `54a725aa925679dd6c3f98c9de6c9f0b33540392` after exact
  four-file change-set verification. Existing service-event generator exited 0
  at `2026-09-08T19:44:21Z`; textfile mode remains `0644`.
- Prometheus readback: **12** inventory servers; `con2`, `voice`, `seedquest`,
  `wherp` all **UNKNOWN (-1)**; generator self-check valid=1.
- All **36** scrape target identities unchanged (sorted-label SHA-256
  `6d258297d6cf787ae488cb7d3e1c94ea126e10bdca6fd7d72d08babd4ab9bad6`).
  **38** runtime configuration/provisioning files retained exact checksums.
  Prometheus, Grafana, Alertmanager, incident gateway and Greenleaf proxy retained
  start times and zero restarts. No alert rule, datasource or credential changed.
- Backup: `/var/backups/rabbit-monitoring-v2/server-ownership-20260908-f0d4a26/service-catalog.before.yml`,
  retained under mode `0700` directory. Runtime readback's final shell `rg` count
  was unavailable on the host; the authoritative Prometheus API count above was
  verified separately, without repeating the apply.

The owner's subsequent name clarification changes display metadata from HOW
to **HOW Production**; metric IDs/labels remain `rentall`. Live application of
that display-only follow-up is recorded after verification.

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
