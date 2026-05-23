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

## Alerting

Grafana-managed alert rules exist for immediate infrastructure notifications:

- `cloud-s3-mount-down`: `/greenleafbackup` unhealthy for more than 30 minutes.
- `cloud-erp-backup-stale`: ERP backup older than 7 hours.
- `cloud-daily-stack-backup-stale`: non-ERP stack backup missing or older than 25 hours.
- `public-site-down`: any public blackbox HTTP probe fails for more than 1 minute.

Pending notification delivery setup:

- Telegram/email contact points.
- Notification policy routing to the selected contact point.
- Service-specific ownership from `monitoring/service-catalog.yml`.
- Runbook links in every notification.
- Noise control with grouping, inhibition, and maintenance windows.
