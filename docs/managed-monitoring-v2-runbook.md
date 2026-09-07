# Managed Monitoring v2 rollout and operations runbook

This runbook moves Managed Monitoring v2 from repository validation to shadow operation, controlled notification and live cutover. It assumes the legacy `/root/monitoring` stack remains available for rollback.

## Safety rules

- Do not run a recursive copy over `/root/monitoring`.
- Do not read, print or commit secret values. Compare secret file names, ownership and permissions only.
- Do not delete monitoring data, Docker data, release backups or stack backups as an implicit deployment step.
- Do not start a second Prometheus or Loki while disk capacity fails the preflight gate.
- Do not let a second process call Telegram `getUpdates`, `setWebhook` or `deleteWebhook` with the existing bot token.
- Do not enable two Telegram senders for the same production alert route during cutover.
- Keep the incident database and outbox during rollback; stopping delivery must not erase state.

## Phase 0 — repository validation

From the repository root:

```sh
jq -e . monitoring/grafana/provisioning/dashboards/managed-*.json
jq -e . monitoring/grafana/provisioning/company-dashboards/greenleaf/managed-*.json
git diff --check
git status --short
```

Confirm that:

- each dashboard UID is unique;
- Greenleaf dashboards contain a hidden fixed `company=greenleaf` variable;
- Greenleaf dashboards use no Loki datasource;
- network and block I/O panels use rate/increase semantics rather than raw cumulative totals;
- no secret, real chat ID or token appears in a dashboard or document.

The generated dashboards may be refreshed with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/generate-managed-monitoring-dashboards.py
```

Review generated changes before committing them.

## Phase 1 — live drift capture

Perform this phase read-only. Store manifests in an approved operator work area, not in a public repository.

Inventory the deployed services and paths:

```sh
docker compose ls --all
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker network ls
systemctl list-timers --all --no-pager
```

Create a non-secret checksum manifest. Explicitly exclude deployed secret files:

```sh
cd /root/monitoring
find . -type f ! -name .env ! -name .greenleaf-viewer-password -print0 \
  | sort -z \
  | xargs -0 sha256sum
```

Reconcile, at minimum:

- server-only Blackbox DNS and site-identity modules;
- `/etc/promtail/config.yml` without its credentials;
- `/root/monitoring/loki/local-config.yaml`;
- Grafana database-managed rules, contact-point names and routing policy metadata;
- systemd service/timer files and exporter scripts;
- differences between live and repository dashboard versions.

Preserve live behavior as an explicit repository change or a documented intentional exception. Do not resolve drift by choosing whichever file is newer.

## Phase 2 — capacity gate

Capture filesystem, inode and monitoring-data usage:

```sh
df -hT /
df -ih /
du -sh /var/lib/monitoring/prometheus /var/lib/monitoring/loki
docker system df
```

The audited host had only 4.6 GiB free and therefore fails the full parallel-stack gate. For this host:

- a stateless incident gateway plus small database may proceed with an explicit storage budget;
- a duplicate Prometheus/Loki must not proceed until storage is expanded or cleanup is separately reviewed and approved;
- configure log rotation and an outbox/incident retention policy before live traffic;
- alert on root filesystem free space and incident database growth.

A practical deployment gate is at least 10 GiB free and below 85% root usage after accounting for the proposed component's retention budget. Recalculate the gate rather than treating those numbers as permanent capacity planning.

## Phase 3 — isolated deployment

Deploy the v2 service pair alongside the legacy stack without replacing its containers or data:

- checkout path: `/opt/rabbit-monitoring-v2`;
- separate Compose project name;
- separate persistent data root and an intentional attachment to the existing private `monitoring_default` network;
- loopback-only ingress, initially on an unused port such as 8180;
- no Docker socket mount;
- no Telegram sending in the initial profile;
- `/healthz` for process liveness and `/readyz` for database, mode, worker and live-mode Telegram-configuration readiness;
- a metrics endpoint containing bounded gateway, transition and delivery counters.

Required configuration names are documented in the example environment file. Secret values belong in runtime secret files. The SQLite database path must be writable. Live readiness fails closed when the Telegram bot token or chat ID is absent; webhook authentication is optional in the implementation but should be configured before the endpoint is reachable by anything outside the private monitoring network.

Readiness checks must distinguish:

- process live;
- database reachable and migrations current;
- live-mode outbox worker running;
- Telegram credentials configured in live mode, without sending a production message.

Prometheus discovery and Alertmanager-to-gateway delivery are separate end-to-end checks; they are not part of the gateway's local readiness response.

Before shadow ingestion, back up and validate the narrowly scoped Prometheus changes that add Alertmanager discovery/routing, then reload Prometheus. Do not copy the repository tree over `/root/monitoring` or replace the legacy Grafana route.

## Phase 4 — shadow ingestion

Feed the gateway copies of production events while outbound notification remains disabled. The legacy webhook remains authoritative.

For every inbound event, verify:

- normalization into `company`, `alias`, `stack`, rule/check and target;
- stable dedupe key across repeated Grafana payloads;
- event persistence before response;
- state transition and generation;
- no notification-outbox row in shadow mode;
- no token, authorization header or complete sensitive payload in logs.

Compare shadow outcomes with source events daily. Categorize differences as normalization, threshold, ordering, source-noise or legacy behavior; do not tune rules merely to make the two systems numerically identical.

Shadow mode persists incidents and immutable incident events, but deliberately creates no notification work. Switching mode increments a delivery generation and cancels any unsent rows from an earlier generation, so shadow history cannot become a live Telegram backlog.

An incident opened in shadow remains attached to the shadow generation: repeated firing events after a mode switch do not manufacture a live DOWN for that already-open occurrence. Before cutover, require zero unexplained open shadow incidents. Resolve the underlying sources and observe their closure, or explicitly account for each still-active problem and trigger a new controlled live occurrence after the mode switch. Never assume that changing `GATEWAY_MODE` replays current outages.

### Required synthetic lifecycle matrix

Run controlled synthetic events that cannot be confused with production incidents:

| Scenario | Expected result |
| --- | --- |
| One failure below a Prometheus rule's `for` threshold | No firing event reaches the gateway; no incident or DOWN. |
| Firing event in shadow mode | One open incident and immutable firing event; no outbox row. |
| Duplicate firing payload in shadow mode | `last_seen_at` updates; no additional firing event or outbox row. |
| Two affected targets in one application | Separate dedupe keys or one explicitly modelled aggregate, never accidental merging. |
| Recovery with no open incident | Orphan diagnostic; no Telegram Recovery. |
| Late recovery from older generation | Newer open incident remains open. |
| Mode changes | Unsent rows from the old delivery generation are retained as cancelled and are not replayed. |

Exercise notification behavior in a separate live-mode test instance with an approved test Telegram destination, not through the production route:

| Scenario | Expected result |
| --- | --- |
| First firing event | One incident generation and one DOWN outbox row. |
| Duplicate firing payload | `last_seen_at` updates; no second DOWN row. |
| Recovery after delivered DOWN | Same generation resolves; one Recovery is queued after DOWN. |
| DOWN delivery fails, then recovery arrives | Incident records resolved; DOWN keeps retrying. Once DOWN is sent, Recovery is queued and sent after it, never alone. |
| Gateway restarts with queued DOWN | Durable retry resumes and ordering is preserved. Delivery is at-least-once if failure occurs after Telegram accepts the message but before the local success commit. |
| Telegram rate limit/transient error | Retry indefinitely with capped exponential delay, honor `retry_after`, and never set a false delivered flag. |

Do not advance until every scenario has deterministic database evidence.

## Phase 5 — dashboard validation

Provision the new files without replacing existing dashboards:

- admin: Fleet Overview → Server Drilldown → Application Drilldown;
- customer: the equivalent Greenleaf sequence in org 2.

Validate the following selections:

1. Company constrains the server list.
2. Server constrains the application list.
3. Application constrains component and container lists.
4. Dashboard links preserve the selected hierarchy and time range.
5. Application CPU/RAM are sums of running components.
6. Network and block I/O use rates and remain non-negative across container restarts.
7. Missing planned metrics display No data rather than a false green status, except explicitly documented numeric fallbacks.
8. External HTTP state can disagree with component state without one masking the other.

For Greenleaf, test with a non-admin customer account. Confirm in browser/network inspection that label enumeration and PromQL cannot escape `company=greenleaf`. A hidden company variable alone is not an isolation control.

The customer dashboards must have no Loki datasource or links to shared log exploration.

## Phase 6 — controlled Telegram canary

The gateway may reuse the OpenClaw bot token for outbound messages only. Enforce the contract in code review and, where possible, with a restricted notifier interface exposing only `sendMessage`.

Before the canary:

- verify OpenClaw remains the sole inbound webhook owner;
- verify the gateway contains no `getUpdates`, `setWebhook` or `deleteWebhook` call;
- select a dedicated test topic or approved test destination;
- keep production incident routes in shadow mode;
- verify Bot API success from the parsed `ok` field;
- test HTML/plain-text fallback without treating an error dictionary as success;
- confirm rate-limit handling and retry visibility.

The canary is successful only when database delivery state, Telegram message presence and metrics agree.

## Phase 7 — live cutover

Schedule a short change window.

1. Record current Grafana contact-point and routing metadata without secret values.
2. Confirm gateway readiness, database backup, understood retry backlog and current clock synchronization.
3. Confirm there are zero unexplained open shadow incidents; mode switching intentionally does not replay them.
4. Stop or disable the legacy production notification path while retaining its configuration for rollback.
5. If replacing the isolated shadow Compose project with the full-stack Compose services, stop the shadow Alertmanager/gateway first. Both definitions intentionally use the same loopback ports and private-network aliases and must not run together.
6. Enable the new receiver for one low-risk rule group.
7. Trigger one controlled firing/recovery lifecycle and verify both messages and their shared incident ID.
8. Expand routing by criticality or company, not all at once.
9. Observe duplicates, notification lag, outbox age and orphan recoveries.
10. Keep the legacy stack collecting metrics throughout cutover.

Avoid a period where both OpenClaw and the gateway send the same production alert. Dual ingestion is acceptable; dual notification is not.

Recommended initial live gates:

- zero standalone Recovery messages;
- exactly one DOWN outbox row per generation and no duplicates in controlled delivery tests, while retaining an explicit at-least-once caveat for a crash at the Telegram/local-commit boundary;
- zero notifications marked delivered when Bot API `ok` is not true;
- no unexplained or indefinitely stale retry rows; attempt count, last error and next-attempt time are visible;
- every open incident traceable to a source event and inventory object;
- no cross-company query or notification leakage.

## Rollback

Rollback is routing and sender control, not data deletion.

1. Disable new outbound claims so no additional messages are sent.
2. Preserve the incident database and outbox for diagnosis.
3. Restore the recorded legacy Grafana route/contact point.
4. Confirm the legacy webhook is receiving events.
5. Restart the gateway in shadow mode to cancel unsent rows into the retained `cancelled_mode_switch` state; do not replay stale Recovery messages after rollback.
6. Keep v2 ingestion in shadow only if it cannot affect live notifications.
7. Capture timestamps and incident IDs around the rollback boundary.

Do not remove v2 volumes or overwrite `/root/monitoring`. A later cleanup is a separate approved change.

## Routine incident operations

### DOWN received

1. Open Fleet Overview and confirm company/server/application.
2. Open Server Drilldown to distinguish server failure from one application failure.
3. Open Application Drilldown and inspect required component state and aggregate resource rates.
4. Compare external HTTP/integrity with infrastructure health.
5. Record owner acceptance and any time-bounded suppression in the current operator process. Gateway ACK/snooze controls are backlog and are not available in the initial v2 API.

### Recovery received

Verify that the message names an existing incident generation and that its DOWN delivery was recorded. If not, treat it as a lifecycle defect, hold the notification route and inspect event ordering/outbox state.

### Site reported down

Check independently:

- DNS/TCP/TLS/HTTP result;
- browser resource failures and obvious empty/error output;
- server and required component health;
- whether a live re-probe succeeded;
- whether the source alert cleared before the configured failure threshold.

A successful container check does not close an external-site incident. A successful secondary probe may suppress opening a false incident, but it must also prevent a later standalone Recovery.

### Service event due

Confirm the due date, owner, recipient policy and evidence. In the initial implementation, resolve the generated incident by correcting the reviewed registry date/status and letting Prometheus observe the new metric state. Native reminder acknowledgement/completion controls are backlog. Changing a due date must remain an auditable registry change.

## Monitoring pipeline

Use this section for `PrometheusConfigReloadFailed`, `AlertmanagerNotDiscovered`, `AlertmanagerDown` and `IncidentGatewayDown`.

1. Check component health and readiness independently; a running container is not sufficient.
2. Verify Prometheus retained its last valid configuration and inspect the reload timestamp/error without reloading blindly.
3. Confirm Prometheus discovers exactly the intended Alertmanager endpoint.
4. Confirm Alertmanager can resolve the private gateway address and receives a successful authenticated webhook response.
5. Check gateway database readiness, mode generation, worker health, oldest pending/retry outbox item, attempt count, next-attempt time and last error.
6. Keep application incidents open while the notification pipeline is impaired; do not manufacture recoveries to clear the queue.

Restore the failed hop first, then use a controlled synthetic lifecycle to prove end-to-end delivery.

## Synthetic checkers

Use this section for missing or stale scheduled-site metrics, Blackbox pipeline failures and integrity-check failures.

- Distinguish `up{job="blackbox_http_services"}=0` (probe pipeline failed) from `probe_success=0` (probe ran and found a problem).
- Check the scheduled checker timer, last finish timestamp, output-file timestamp and Prometheus scrape visibility.
- A stale output file is a monitoring failure, not proof that every website is down.
- For integrity checks, retain deterministic evidence: final HTTP state, empty/error-page classification and failed critical-resource ratio.
- Do not change expected page text to silence normal content updates.

After repair, require a fresh successful cycle before resolving the checker incident.

## Public site down

1. Identify the endpoint and application from `company`, `alias` and `stack`.
2. Compare Blackbox history with the lower-frequency scheduled checker.
3. Inspect DNS, TCP, TLS, redirect chain, HTTP status and response duration.
4. Check the browser/integrity signal for failed CSS, JavaScript or images and empty/error output.
5. Check application components separately; do not infer user-visible success from healthy containers.
6. Re-probe from a controlled location. Record whether the failure is origin, edge/CDN or checker-specific.

Resolve only from recovery evidence for the same incident fingerprint. A successful secondary probe that prevents DOWN must also prevent a later standalone Recovery.

## Node or exporter down

1. Determine whether only exporter scraping failed or the server itself is unreachable.
2. Check network/VPN dependency health before restarting an exporter.
3. Compare node-exporter and cAdvisor reachability for the same alias.
4. Check textfile collector freshness; stale Docker-stack metrics can make application state misleading.
5. If the server is reachable, inspect exporter service/container health and listen scope.
6. If the server is unreachable, follow its infrastructure escalation path and treat dependent application alerts as symptoms.

Do not close child application incidents solely because the exporter disappeared.

## TLS or service event expiry

Confirm the authoritative due timestamp, timezone, owner and renewal mechanism. For TLS, distinguish certificate expiry from a failed TLS handshake or an unreachable endpoint. For domains and subscriptions, retain registrar/provider evidence outside the alert label set.

After renewal, verify the externally served certificate or provider due date, update the service-event registry through review, and let the same event generation resolve. Avoid manually silencing a due event without a replacement date.

## Backup stale or unavailable

1. Identify whether the failure is scheduler, source snapshot, local archive, remote copy, mount/object storage or metric freshness.
2. Check last successful timestamps and expected cadence before starting a manual backup.
3. Ensure another backup process is not already running.
4. Verify the resulting artifact and manifest; file presence alone is not restore evidence.
5. Record the recovery timestamp and schedule a restore test when integrity is uncertain.

Never delete old backup sets as an incidental response to a monitoring-host disk alert.

## Disk capacity

Inspect filesystem usage, inodes, Prometheus/Loki growth, Docker logs and backup directories. Identify ownership and retention before proposing deletion. Prefer expansion, configured retention and recoverable archival. Any cleanup of release or stack backups requires separate approval and a verified retained copy.

Do not deploy a duplicate TSDB while the host fails the capacity gate. After remediation, verify free-space alert recovery and projected growth, not only the immediate percentage.

## Scheduled verification

Daily:

- open incidents with no update beyond their criticality window;
- oldest pending/retry outbox row, attempt count and last error;
- target and scheduled-check freshness;
- root disk free space;
- last successful incident database backup.

Weekly:

- inventory/runtime drift;
- customer datasource isolation;
- certificate/domain/subscription deadlines;
- standalone or manually created containers such as Promtail;
- alert rules without a live receiver and receivers without rules;
- synthetic DOWN → Recovery canary.

Monthly:

- restore-test the incident database backup;
- review metric cardinality and retention growth;
- review bot permissions and destinations without displaying the token;
- reconcile live configuration checksums with Git;
- remove obsolete exceptions only through a reviewed change.

## External watchdog backlog

Until an independent watchdog exists, document that the monitoring host cannot reliably report its own total outage. The future watchdog should run outside this server and verify gateway health, scrape freshness, scheduled-check freshness and a notification canary through an independent route.

Do not simulate this independence by running another container on the same host.
