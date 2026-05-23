# Monitoring Roadmap

## Now

- Service stack resource dashboards by company, node, stack, and service.
- Docker log collection to Loki with bounded labels: `company`, `alias`, `stack`, `service`, `container`.
- HTTP availability and TLS probes through Blackbox Exporter for confirmed public service endpoints.
- Service catalog as code in `monitoring/service-catalog.yml`.

## Next

- Expand the service catalog with owners, repository links, backup policy, and runbook links.
- Add confirmed URLs for internal/client services that are currently only visible as Docker stacks.
- Migrate node log collection from Promtail to Grafana Alloy after the current dashboards are stable.
- Add OpenTelemetry/Tempo tracing for ERPNext, bots, APIs, and OpenClaw services.
- Add backup verification metrics: last successful backup, backup size, restore-check age, and storage free space.
- Add security/audit collection: SSH failures, sudo events, Docker restarts, pending updates, and exposed ports.

## Later: Alerting

Alert notification routing is intentionally deferred. The current Prometheus rules can be used for visibility, but contact points, notification policies, escalation, and on-call routing should be designed as a separate phase.

Planned alerting work:

- Telegram/email contact points.
- Separate routing for critical and warning events.
- Service-specific ownership from `monitoring/service-catalog.yml`.
- Runbook links in every notification.
- Noise control with grouping, inhibition, and maintenance windows.
