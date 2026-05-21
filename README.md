# Grafana AI Monitoring

Prometheus and Grafana provisioning for client server monitoring.

## Current Segments

| Company | Nodes |
| --- | --- |
| greenleaf | cloud, testing, new |
| rentall | payroll, howbot |
| my own | test |

## Files

- `monitoring/prometheus/prometheus.yml` - Prometheus scrape config.
- `monitoring/grafana/provisioning/dashboards/` - Grafana dashboard provisioning.
- `monitoring/grafana/provisioning/datasources/` - Grafana datasource provisioning.
- `systemd/prometheus-test-tunnel.service` - persistent reverse SSH tunnel from `test` to `con`.

## Runtime Notes

- `test` is behind NAT and is monitored through a reverse SSH tunnel:
  `test:127.0.0.1:9100 -> con:172.17.0.1:19100`.
- `new` is currently configured in Prometheus but remains down until `node_exporter`
  is installed/listening on `139.99.171.55:9100` and the host is reachable.

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

After changing dashboard provisioning:

```bash
docker restart monitoring-grafana
```

