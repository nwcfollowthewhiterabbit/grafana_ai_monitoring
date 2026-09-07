# Managed Monitoring Roadmap

This roadmap separates the deployed production baseline from operational remediation and future product work. The current deployment record is `docs/deployments/con-integrated-compose.md`.

## Production baseline

- Hierarchical service catalog: company → server → application → component.
- Existing Prometheus, Grafana, Loki, Blackbox, node, cAdvisor and SNMP collection reused on `con`.
- Alertmanager routing and inhibition integrated into the `monitoring` Compose project.
- SQLite incident gateway with durable, idempotent DOWN → Recovery delivery to Telegram.
- Legacy Grafana → OpenClaw alert processing paused and retained only as the rollback sender.
- Admin Fleet → Server → Application dashboards in Grafana org 1.
- Greenleaf customer dashboards in org 2 through a server-enforced `company=greenleaf` Prometheus proxy.
- Frequent HTTP/TLS probes, queued retrying site checks, and independent page-integrity checks.
- Service-event registry/exporter framework for domains, certificates, subscriptions and periodic actions.
- CI validation for catalog/config generation, dashboards, Compose, Prometheus rules, Alertmanager config and gateway lifecycle tests.

## Immediate operational remediation

- Restore safe free-space headroom on `con`; root usage was 95% at cutover. Review retention and backup ownership before deleting anything.
- Repair `rentall-vpn.service`, then verify both Windows exporters and both MikroTik SNMP targets recover.
- Restore Greenleaf `cloud` cAdvisor and Docker inventory metrics. `ExpectedComponentMissing` remains inhibited while inventory is stale.
- Repair and verify Greenleaf mount, ERP and per-stack backup metrics; add restore-test age rather than treating file presence as sufficient proof.
- Renew or replace the certificate behind the active `TLSCertificateExpiryCritical` incident.
- Restore the two unavailable Linux node-exporter paths or explicitly change their inventory status after review.
- Establish and test routine rotation for the shared monitoring credentials and runtime secret files without committing values.

## Next product increment

- Populate real domain/subscription/service renewal dates, owners and customer-recipient policy in the service-event registry.
- Add maintenance windows and reviewed silence ownership.
- Add acknowledgement, snooze and reminder state to the incident control plane.
- Add automatic, verified backups for the incident database and alert-delivery audit state.
- Add a small external watchdog in a different failure domain for Prometheus freshness, gateway readiness and notification canaries.
- Add direct-origin probes where an edge/CDN success can hide an origin failure.
- Complete owner, repository and runbook links for every managed application.
- Add explicit notification routing by company/criticality after recipient policy is verified.

## Rentall backup backlog

- Configure automatic cloud backups for M.E.Doc on `192.168.112.20`.
- Configure automatic cloud backups for 1C on `192.168.112.19`.
- Configure Hyper-V backups for the RDP/1C and MikroTik VMs.
- Export freshness, size, result, destination availability and restore-check age.
- Enable the corresponding alert rules only after stable source metrics exist.

## Later

- Migrate node log collection from Promtail to Grafana Alloy after equivalent coverage is proven.
- Add OpenTelemetry/Tempo tracing for ERPNext, bots, APIs and OpenClaw services.
- Add bounded security/audit signals for SSH failures, sudo events, Docker restarts, pending updates and exposed ports.
- Evaluate a dedicated monitoring bot to reduce the shared Telegram credential blast radius.
- Build a Rabbit Systems branded customer portal only after the Grafana-based managed-monitoring workflow is stable.

## Deliberate non-goals

- No duplicate Prometheus or Loki on the capacity-constrained monitoring host.
- No automatic discovery becoming managed inventory without review.
- No golden-page comparison that breaks whenever normal website content changes.
- No customer access to shared Loki data without enforceable tenant isolation.
- No deletion of legacy Grafana/OpenClaw configuration until rollback is intentionally retired.
