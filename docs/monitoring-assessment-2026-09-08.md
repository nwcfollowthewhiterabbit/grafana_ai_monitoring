# Managed monitoring review — 2026-09-08

## Product boundary

Keep Prometheus/Grafana/Loki, the existing Telegram bot and customer Grafana
organizations. The useful model is Company → Server → Application → Component;
resources are application totals with a container drilldown. Rabbit Platform is
an authenticated operator workspace, not a second metrics store or alert sender.
Deployment/migration evidence lives in `docs/deployments/`, not in this review.

## Changes verified in this iteration

- Gateway schema v2 preserves incidents/outbox, rejects future schemas, fences
  expired delivery leases and persists Telegram-wide flood-control cooldowns.
  Historical/orphan resolved occurrences cannot reopen through delayed retries.
- Status is explicit: `-1 UNKNOWN`, `0 unreachable/stopped/missing`, `1
  reachable/running`. Missing or stale Docker inventory must not fabricate DOWN
  or a green application. Successful scrape, textfile age ≤15 min, parse status
  and plausible timestamps gate observed application/component data.
- CPU, RAM and network totals deduplicate containers before aggregation; the
  monitoring stack is included. Missing expected services remain visible.
- Zero open incidents is shown only with a reachable, company-scoped gateway
  scrape. Integrity evidence expires after25h; backup age uses the worst value.
- Site resource checks follow the final redirect/base URL, prioritize CSS/JS and
  detect HTTP200 HTML fallback responses masquerading as assets. Normal content
  changes still do not require a visual baseline.
- Final gateway tests:36 passed. Catalog/checker/compose/transport unit tests:30 passed.
  Ten fixtures passed in the actual pinned Prometheus3.4 evaluator, including
  telemetry loss, stale data, missing services, duplicates and tenant isolation.

## Limits that must stay visible

1. A running container is not a successful Docker healthcheck. Current exporter
   data does not provide that evidence; do not label it simply "healthy".
2. Alertmanager `resolved` means the rule stopped firing. A disappeared source
   or a rule change can resolve an alert without proving service recovery.
   Gateway ordering prevents Recovery without a delivered DOWN, but does not
   independently validate physical recovery. Fresh-source reconciliation is P0.
3. A new startsAt after an unobserved prior Recovery still needs reconciliation;
   there is no universal exactly-once guarantee for Telegram network outcomes.
4. HTTP/resource inspection is not a browser render check. JS-only failures,
   layout breakage and interactive user journeys require a bounded browser
   probe. Add twice-daily evidence collection before optional LLM judgement;
   advisory LLM findings alone must not page customers.
5. Subscription/domain deadlines require inventory dates and responsible
   contacts. Unknown dates remain unknown, not "no upcoming expiry".
6. Existing Greenleaf Docker collector gaps, test/NAT listeners and Rentall VPN
   faults predate migration. Preserve their unknown/down evidence and report
   separately; central relocation cannot manufacture the missing telemetry.
7. Central deployment remains one failure domain. Add an independent external
   dead-man signal and off-host tested backups before claiming high availability.

## Next acceptance gates

P0: fresh evidence for recovery; source expiry/reconciliation; external watchdog;
tested restore of incidents, Grafana credentials and platform PostgreSQL.

P1: Docker healthcheck and replica requirements; real service deadlines;
read-only Platform incident/inventory projection with explicit freshness and
workspace binding. Grafana is the drilldown, not an unrestricted datasource proxy.

P2: inexpensive browser failure detection and optional LLM evidence triage;
customer portal only after tenant-scoped API isolation tests and genuine demand.
