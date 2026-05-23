# Grafana AI Monitoring

Prometheus and Grafana provisioning for client server monitoring.

## Current Segments

| Company | Nodes |
| --- | --- |
| greenleaf | cloud, testing, new |
| rentall | payroll, howbot |
| my own | test, con |

## Files

- `monitoring/prometheus/prometheus.yml` - Prometheus scrape config.
- `monitoring/prometheus/rules/` - Prometheus alert rules for node, cAdvisor, disk, memory, container state, and stale stack metrics.
- `monitoring/blackbox/config.yml` - Blackbox Exporter HTTP probe configuration.
- `monitoring/service-catalog.yml` - service inventory, public endpoints, and pending discovery list.
- `monitoring/alloy/config.template.alloy` - future Grafana Alloy collector template for OpenTelemetry-ready collection.
- `monitoring/promtail/config.template.yml` - Docker log collection template for client nodes.
- `monitoring/grafana/provisioning/dashboards/` - Grafana dashboard provisioning.
- `monitoring/grafana/provisioning/datasources/` - Grafana datasource provisioning.
- `monitoring/docker-compose.yml` - monitoring stack compose file used on `con`.
- `scripts/cloud-backup-metrics.sh` - `cloud` backup health exporter for node_exporter textfile collection.
- `scripts/cloud-run-daily-backups.sh` - corrected `cloud` daily backup wrapper for all non-ERP stacks.
- `systemd/cloud-backup-metrics.*` - timer for the `cloud` backup health exporter.
- `systemd/prometheus-test-tunnel.service` - persistent reverse SSH tunnel from `test` to `con`.

## Runtime Notes

- `test` is behind NAT and is monitored through a reverse SSH tunnel:
  `test:127.0.0.1:9100 -> con:172.17.0.1:19100`.
- `con` is monitored locally through compose services `node-exporter-con`
  and `cadvisor-con`; its Docker stack metrics are exported through the
  node_exporter textfile collector.
- `new` is currently configured in Prometheus but remains down until `node_exporter`
  is installed/listening on `139.99.171.55:9100` and the host is reachable.
- Grafana-managed alert rules are provisioned in
  `monitoring/grafana/provisioning/alerting/immediate-infrastructure-alerts.yml`.
  A real contact point still needs Telegram, email/SMTP, Slack, or webhook
  credentials before notifications can be delivered.

## Apply

On `con`, Prometheus reads:

```bash
/root/monitoring/prometheus/prometheus.yml
```

Grafana reads provisioning from:

```bash
/root/monitoring/grafana/provisioning
```

After changing Prometheus config:

```bash
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill -s HUP monitoring-prometheus
```

After changing alert rules or compose mounts:

```bash
docker compose up -d prometheus
```

After changing dashboard provisioning:

```bash
docker restart monitoring-grafana
```
