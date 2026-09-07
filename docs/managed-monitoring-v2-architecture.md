# Rabbit Systems Managed Monitoring v2

Status: v2 is deployed on `con`. The existing Prometheus, Grafana, Loki and exporters are reused; Alertmanager and the SQLite incident gateway run in the existing `monitoring` Compose project. Live Telegram delivery is enabled through the gateway, and legacy Grafana processing in OpenClaw is paused but retained for rollback. The applied change record is in `docs/deployments/con-integrated-compose.md`.

## Outcome

Managed Monitoring v2 is an operational system for answering, in order:

1. What companies, servers and applications do we manage?
2. Where does an application run?
3. Is the server, application and external interface working?
4. Is there an open incident or an approaching service deadline?
5. What component should an operator inspect next?

The hierarchy is:

`company → server (alias) → application (stack) → component (service/container)`

Dashboards are projections of this model. They are not a source of truth and they do not own incident state.

## Audited baseline

The read-only audit on 2026-09-07 found:

- the live configuration in `/root/monitoring`, deployed with Docker Compose rather than Swarm;
- Grafana 12.0.0, Prometheus 3.4.0, Loki 2.9.8, Blackbox Exporter, node-exporter, cAdvisor, SNMP Exporter and a Greenleaf label proxy;
- a standalone Promtail container outside the monitoring Compose project;
- seven configured Linux servers, two Windows targets, two MikroTik targets and thirteen HTTP services;
- 32 active Prometheus targets at audit time: 22 up and 10 down;
- no running Alertmanager and no Prometheus `alerting.alertmanagers` delivery path;
- a Grafana webhook routed to the OpenClaw API for rules labelled `notify=immediate`;
- OpenClaw in `/opt/helper`, with Telegram handled inside its FastAPI API container through a webhook, not `getUpdates` polling;
- only 4.6 GiB free on the root filesystem, while the existing Prometheus and Loki data occupied about 8.9 GiB;
- live files that differ from the repository, notably Blackbox DNS/identity modules and an older live service-stacks dashboard.

The audit also reproduced the principal incident-lifecycle defect. A firing website alert was suppressed after a successful secondary probe, but its later resolved event was sent to Telegram. Current code can also mark `telegram_notified` from the presence of message text rather than from a successful Bot API result. The existing pipeline therefore cannot guarantee DOWN → Recovery ordering.

## Design principles

- Prefer a small set of actionable signals over exhaustive collection.
- Keep infrastructure health and external user-visible health independent.
- Persist incident state before attempting notification.
- Deduplicate inbound transitions and notification rows transactionally; treat the final Telegram handoff as at-least-once.
- Never send a standalone Recovery without a registered incident whose DOWN notification was delivered.
- Treat Grafana as the operational viewer; Prometheus evaluates v2 rules and Alertmanager produces gateway events. None of them owns incident history.
- Keep customer isolation enforceable below the dashboard layer.
- Preserve working live configuration before replacing or normalizing it.
- Introduce components in shadow mode and keep rollback reversible.

## Sources of truth

| Concern | Source of truth | Notes |
| --- | --- | --- |
| Managed inventory | Versioned repository catalog | Company, server alias, application, endpoints, criticality, owner and service-event policy. |
| Runtime placement | Exporter/discovery observations | Docker labels and target discovery may differ temporarily from desired inventory. |
| Time-series health | Prometheus | Scrapes and recording metrics; not authoritative for notification history. |
| Incident lifecycle | Incident-gateway database | Current state, dedupe key, transition history and notification delivery state. |
| Notification work | Transactional outbox | The implemented gateway stores DOWN and RECOVERY work. Retries and delivery acknowledgements survive process restarts. |
| Domains/subscriptions/certificates | Versioned service-event registry plus scheduler state | Explicit due date, owner, recipients and reminder policy. |
| Presentation | Grafana provisioning | Dashboards contain no state that is required to recover an incident. |

The repository catalog should extend `monitoring/service-catalog.yml` rather than creating parallel hand-maintained lists. Runtime discovery may propose additions, but it must not silently become managed inventory.

## Data flow

```text
inventory + runtime exporters + external probes + service-event scheduler
                              │
                              ▼
                         Prometheus
                 recording rules / normalized labels
                              │
                         Alertmanager
                 grouping / routing / inhibition
                              │
                              ▼
                stateful incident gateway database
                   │                         │
                   │                         └── transactional outbox
                   │                                      │
                   ▼                                      ▼
             incident metrics                    Telegram sendMessage
                   │
                   ▼
           admin/customer Grafana views
```

The deployment reuses the existing Prometheus and Grafana and adds Alertmanager plus the gateway. During shadow operation the legacy Grafana-managed notification route remained authoritative; after the controlled cutover the gateway became authoritative and OpenClaw's Grafana processing was paused. A second Prometheus or Loki is not required.

The first deployment keeps the new pair in its own shadow Compose project. After observation, `deploy/con-monitoring-v2.override.yml` can move only those two services into the existing `monitoring` project while preserving the same state. `deploy/con-monitoring-v2.live.yml` is a separate, explicit notification opt-in; layout integration alone never enables Telegram delivery.

## Normalized labels

All normalized application and component metrics use:

- `company`: customer or Rabbit Systems administrative scope;
- `alias`: stable server alias;
- `stack`: application/deployment name;
- `service`: logical component such as backend, frontend or database;
- `container`: concrete runtime container where applicable;
- `criticality`: optional inventory-derived severity input.

Labels must be bounded. Incident IDs, URLs, error messages, certificate serials and arbitrary container hashes must not become unbounded metric labels.

## Recording metric contract

The new dashboards use catalog-aware recording metrics for identity and health. Raw exporter fallbacks remain only for resource/detail signals where absence cannot be misread as a healthy state.

| Planned metric | Required labels | Meaning / current fallback |
| --- | --- | --- |
| `rs_monitoring_server_inventory_info` | bounded server hierarchy/status | Catalog inventory used to populate the operator hierarchy without treating pending access as DOWN. |
| `rs_monitoring_application_inventory_info` | bounded application hierarchy/status | Catalog application inventory, independent from whether runtime metrics happen to exist. |
| `rs_monitoring_expected_component_info` | bounded component hierarchy | Components explicitly expected to be running; one-shot and discovery-pending entries are excluded. |
| `rs_monitoring_server_up` | `company,alias` | One when an active managed server is reachable. |
| `rs_monitoring_application_up` | `company,alias,stack` | One only when the number of running expected services equals the catalog expectation. |
| `rs_monitoring_component_up` | `company,alias,stack,service,container` | Observed container state restricted to expected catalog components. |
| `rs_monitoring_application_cpu_percent` | `company,alias,stack` | Sum of running component CPU percentages. |
| `rs_monitoring_application_memory_bytes` | `company,alias,stack` | Sum of running component resident memory. |
| `rs_monitoring_application_network_rx_bytes_per_second` | `company,alias,stack` | Application receive throughput. |
| `rs_monitoring_application_network_tx_bytes_per_second` | `company,alias,stack` | Application transmit throughput. |
| `rs_monitoring_application_block_read_bytes_per_second` | `company,alias,stack` | Application block-read throughput. |
| `rs_monitoring_application_block_write_bytes_per_second` | `company,alias,stack` | Application block-write throughput. |
| `rs_monitoring_component_*` resource metrics | hierarchy plus component labels | Component equivalents of CPU, memory, network and block I/O. |
| `rs_monitoring_http_up` | hierarchy plus check identity | External HTTP result, independent from container health; falls back to Blackbox `probe_success`. |
| `rs_monitoring_integrity_up` | hierarchy plus endpoint identity | Browser/resource/integrity result; intentionally has no misleading fallback. |
| `rs_monitoring_tls_expiry_timestamp_seconds` | hierarchy plus endpoint identity | Certificate expiry timestamp; falls back to Blackbox TLS expiry. |
| `rs_monitoring_backup_last_success_timestamp_seconds` | hierarchy plus backup identity | Last verified usable backup; the panel remains No data until a source is explicitly normalized. |
| `rs_monitoring_alert_firing` | bounded hierarchy/severity | Countable raw firing signal. `ALERTS` is a diagnostic fallback, not an incident. |
| `incident_gateway_incidents` | `state` | Current gateway-wide diagnostic lifecycle count; never use it as a scoped customer/server fallback. |
| `rs_monitoring_open_incident` | bounded hierarchy, severity and state | Implemented scoped aggregate for fleet/server filtering and incident tables. It omits incident IDs and unbounded text. |
| `rs_monitoring_service_event_due_timestamp_seconds` | bounded hierarchy and event type | Due timestamp for domain, subscription, certificate or maintenance event. |

The current Docker textfile exporter reports network and block counters as cumulative values sampled approximately every three minutes. Dashboards therefore use a non-negative 15-minute `rate()` fallback. Raw cumulative I/O totals are not shown as throughput.

## Incident state machine

The gateway uses the Alertmanager alert fingerprint as its dedupe key. If a payload omits that fingerprint, it hashes the complete sorted label set. Alert rules must therefore keep volatile values and descriptive text out of labels so that one occurrence retains a stable identity.

```text
Prometheus rule: inactive ──failure──▶ pending ──`for` elapsed──▶ firing
                                                                          │
                                                                          ▼
Gateway:                                                           open ──resolved event──▶ resolved
```

Prometheus/Alertmanager own failure thresholds and pending state. The implemented gateway receives only firing/resolved source events and persists `open`/`resolved` incident state. ACK, snooze, reminder controls and a separate terminal `closed` state are later control-plane work; they are not gateway APIs or database states in the initial v2 implementation.

Required persistence:

- `incidents`: current state, dedupe key, first/last seen, generation, severity and ownership;
- `incident_events`: append-only normalized `firing`, `resolved`, `orphan_resolved` and mode-change history;
- `notification_outbox`: implemented DOWN and RECOVERY rows, each unique for its incident generation, including attempt count, last error, lease and delivery timestamps.

Separate UPDATE/REMINDER message types and a normalized notification-attempt history table are future extensions. The current immutable incident-event table plus mutable outbox row provide the initial audit and retry evidence.

Transition rules:

1. Persist the source event and state transition in one transaction.
2. In live mode, opening an incident creates exactly one DOWN outbox row for that incident generation. Shadow mode creates no notification rows.
3. Delivery is successful only when Telegram returns `ok=true`; constructing text or receiving HTTP 200 from the gateway is insufficient.
4. Duplicate firing events update `last_seen_at`; they do not create another DOWN.
5. A resolved event with no matching open generation is stored as an orphan diagnostic and does not notify Telegram.
6. Recovery is enqueued only after the matching DOWN delivery is recorded successful. If a resolved event arrives while DOWN is still undelivered, the resolved transition is retained durably, DOWN continues retrying, and its eventual successful delivery atomically queues Recovery. The worker therefore sends delayed DOWN and then Recovery in strict order; it never sends Recovery alone.
7. A resolved source event applies only to the matching dedupe key and occurrence. Its Recovery notification remains tied to that incident generation; late or out-of-order events cannot resolve a newer occurrence.
8. Notification failures retry indefinitely with exponential backoff capped at the configured maximum delay, while Telegram `retry_after` is respected as a minimum. There is no terminal dead-letter state in the initial implementation.
9. The database guarantees one DOWN and one RECOVERY row per incident generation, but Telegram delivery is at-least-once: a process failure after Telegram accepts a message but before the local success commit can cause a duplicate retry.
10. Acknowledgement, snooze and operator reminder policy remain control-plane backlog and do not affect observed health in the implemented gateway.

## Website monitoring

Application infrastructure and the external interface are separate checks:

- infrastructure: server reachability, required components, healthchecks and resources;
- external HTTP: DNS/connect/TLS/HTTP and response timing;
- integrity/browser: empty or error page, failed critical CSS/JS/images and obvious rendering failure;
- backup/continuity: last successful, restorable backup signal.

The integrity check looks for evidence of breakage. It must not pin normal content, text or images to a golden page. A low-cost model may classify captured evidence later, but deterministic browser/network failures remain primary evidence.

## Service events

The service-event registry contains at minimum:

- stable event ID and company/application ownership;
- event type: domain, certificate, subscription or maintenance;
- due/expiry timestamp and timezone;
- administrative and optional customer recipient policy;
- reminder offsets and current registry status;
- evidence/reference link, never a credential.

The initial scheduler exposes due-date metrics that Prometheus rules can turn into ordinary firing/resolved incidents. Native reminder generations, acknowledgement state and a distinct reminder outbox message type are backlog; they must use durable idempotency guarantees when added.

The checked-in registry intentionally starts with no production events because no renewal dates were verified during the audit. Operators add an event only after confirming its due date and owner; the implementation must not invent a deadline to make a dashboard look complete.

## Telegram contract

OpenClaw owns the single inbound Telegram webhook. The incident gateway may reuse the current bot token only as an outbound client:

- implemented Bot API method: `sendMessage` only;
- forbidden methods: `getUpdates`, `setWebhook` and `deleteWebhook`;
- the token is injected through a secret file or runtime secret reference, never committed or logged;
- rate limits, chat permissions and topic IDs are shared and must be handled explicitly;
- provider success means parsed Bot API `ok=true`, not merely a non-empty response object.

A dedicated monitoring bot remains a later blast-radius reduction option.

## Grafana views and customer isolation

The admin views are:

- `managed-fleet-overview`;
- `managed-server-drilldown`;
- `managed-application-drilldown`.

They follow the same variable hierarchy and link into each other. Greenleaf copies fix `company=greenleaf`, are read-only, use Prometheus only and are intended for Grafana org 2.

Customer isolation does not depend on a hidden variable. Org 2 uses its own datasource through `prom-label-proxy`, which enforces `company=greenleaf` for queries and label APIs. Customer dashboards deliberately contain no Loki datasource because a shared Loki store does not yet provide equivalent tenant enforcement.

Future customers receive separate organizations and independently enforced label values. Dashboard JSON can be generated from the same templates, but credentials, organizations and datasource provisioning remain explicit deployment steps.

## Deployment boundaries

The first v2 deployment should use:

- `/opt/rabbit-monitoring-v2` as a separate checkout;
- a distinct Compose project and persistent data root, deliberately attached to the existing private `monitoring_default` network for Prometheus/Alertmanager/gateway name resolution;
- loopback-only host publishing, initially on a currently unused port such as 8180;
- no Docker socket in the incident gateway;
- the existing Prometheus as a read/event source during shadow mode;
- a dedicated persistent incident database or schema and transactional outbox.

The existing containers and `/var/lib/monitoring` data remain untouched during shadow deployment. Any scoped Prometheus configuration needed to copy events into Alertmanager must be backed up, validated and reloaded independently; never overwrite `/root/monitoring` wholesale.

## Capacity and drift constraints

At audit time the root filesystem was 94% used. A duplicate full-retention Prometheus/Loki would exceed available capacity. Before adding a second TSDB, expand storage or perform a separately approved, recoverable cleanup. Backups and Docker logs are large candidates for review, not automatic deletion targets.

Before any deployment, capture and reconcile:

- the live Blackbox DNS and identity modules absent from the repository;
- the standalone Promtail configuration;
- the live Loki configuration;
- the live versus repository service-stacks dashboard versions;
- current Grafana database-managed contact points, policies and rules.

Never replace `/root/monitoring` with a blind recursive copy.

## External watchdog backlog

The monitoring host is currently part of the monitored system. A later external watchdog should independently verify:

- the public Grafana/incident ingress health endpoint;
- Prometheus scrape freshness;
- incident-gateway readiness and outbox age;
- scheduled-check freshness;
- notification canary delivery.

It should run in a different failure domain and use a separate notification route. This is backlog and is not required for the initial local shadow deployment.

## Explicit non-goals for the first cut

- replacing the current Prometheus/Loki storage immediately;
- automatic discovery becoming managed inventory without review;
- semantic comparison of website content against a saved golden page;
- customer access to shared logs;
- making OpenClaw the long-term incident database;
- deleting legacy rules or live server-only configuration during shadow mode.
