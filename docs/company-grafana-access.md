# Company Grafana Access

This monitoring stack supports read-only customer access through separate
Grafana organizations.

## Greenleaf

Grafana organization:

```text
Greenleaf
```

Access policy:

- Users are `Viewer` only.
- Users belong only to the `Greenleaf` organization.
- Customer dashboards are provisioned from:

```text
monitoring/grafana/provisioning/company-dashboards/greenleaf
```

- Dashboards are provisioned into the `Greenleaf` folder.
- The `company` variable is hidden and fixed to `greenleaf`.
- Loki/log dashboards are not exposed to this organization.
- The Greenleaf Prometheus datasource points to `prom-label-proxy-greenleaf`,
  not directly to Prometheus.

The proxy enforces:

```text
company="greenleaf"
```

for Prometheus API query endpoints. This protects the datasource even if a
viewer can reach query UI or datasource APIs.

Runtime service:

```text
monitoring-prom-label-proxy-greenleaf
```

Image:

```text
quay.io/prometheuscommunity/prom-label-proxy:v0.13.0
```

Reference:

- https://github.com/prometheus-community/prom-label-proxy

## Add A Company

1. Add company labels to `monitoring/service-catalog.yml` and Prometheus target
   config.
2. Add a company-specific `prom-label-proxy-<company>` service to
   `monitoring/docker-compose.yml`.
3. Add a Grafana organization.
4. Add an org-scoped Prometheus datasource that points to the label proxy.
5. Generate company dashboards with the `company` variable hidden and fixed.
6. Create users with the `Viewer` role in only that organization.
