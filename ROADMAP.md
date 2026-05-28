# Monitoring Roadmap

## Now

- Service stack resource dashboards by company, node, stack, and service.
- Docker log collection to Loki with bounded labels: `company`, `alias`, `stack`, `service`, `container`.
- HTTP availability and TLS probes through Blackbox Exporter for diagnostics.
- Queued scheduled public checks for notification-grade public-site availability.
- Service catalog as code in `monitoring/service-catalog.yml`.
- Greenleaf `cloud` public Caddy endpoints are monitored as blackbox HTTP services.

## Next

- Expand the service catalog with owners, repository links, backup policy, and runbook links.
- Add confirmed URLs for internal/client services that are currently only visible as Docker stacks.
- Keep Greenleaf public monitoring synchronized with `greenleaf_cloud-server:ops/public-sites.yml`.
- Add explicit maintenance-window handling for planned Caddy/public-routing work.
- Migrate node log collection from Promtail to Grafana Alloy after the current dashboards are stable.
- Add OpenTelemetry/Tempo tracing for ERPNext, bots, APIs, and OpenClaw services.
- Add backup verification metrics: last successful backup, backup size, restore-check age, and storage free space.
- Add security/audit collection: SSH failures, sudo events, Docker restarts, pending updates, and exposed ports.

## Rentall Backup Backlog

- Configure automatic cloud backups for M.E.Doc on `192.168.112.20`.
- Configure automatic cloud backups for 1C on `192.168.112.19`.
- Add monitoring for M.E.Doc and 1C backup freshness, backup size, exit status, and cloud destination availability.
- Configure Hyper-V VM backups on `192.168.112.20` for:
  - RDP / 1C VM `192.168.112.19`;
  - MikroTik VM `192.168.112.1`.
- Add monitoring for Hyper-V VM backup freshness, last result, backup size, and backup storage free space.
- Add Grafana panels and alert rules after backup jobs produce stable metrics.

## Alerting

Grafana-managed alert rules exist for immediate infrastructure notifications:

- `cloud-s3-mount-down`: `/greenleafbackup` unhealthy for more than 30 minutes.
- `cloud-erp-backup-stale`: ERP backup older than 7 hours.
- `cloud-daily-stack-backup-stale`: non-ERP stack backup missing or older than 25 hours.
- `public-site-down`: scheduled public checker confirms at least 3 failed checks
  in one cycle. The checker runs every 3 hours and retries initially failed URLs
  3 more times with 5 minutes between retry rounds.

Pending notification delivery setup:

- Telegram/email contact points.
- Notification policy routing to the selected contact point.
- Service-specific ownership from `monitoring/service-catalog.yml`.
- Runbook links in every notification.
- Noise control with grouping, inhibition, and maintenance windows.
- Split public checks into edge-path and direct-origin probes where DNS or
  Cloudflare policy can hide origin behavior.

## Greenleaf Public Endpoint Backlog

- Keep `beautylab.spa.com.fj` and `trexfiji.com` out of public alerts until their DNS/certificate state is production-ready.
- Track `bulataxi.com` as monitored but with DNS/certificate remediation owned by the production ops repo.
- Add runbook links to public-site alert annotations after notification routing is configured.
