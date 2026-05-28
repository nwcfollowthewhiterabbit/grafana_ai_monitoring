# Greenleaf Public Monitoring

Greenleaf public endpoints are monitored from `con` through Prometheus
`blackbox_http_services`.

## Source Of Truth

- Monitoring inventory: `monitoring/service-catalog.yml`
- Prometheus scrape config: `monitoring/prometheus/prometheus.yml`
- Production routing inventory: `greenleaf_cloud-server:ops/public-sites.yml`
- Production routing runbook: `greenleaf_cloud-server:docs/runbooks/public-sites.md`

When a production public site is added, removed, or disabled, update both the
production routing inventory and this monitoring repo in the same change window.

## Active Public Checks

As of `2026-05-26 UTC`, Greenleaf `cloud` has 13 active public HTTPS checks:

- `https://cloud.greenleafpacific.com`
- `https://greenleafpacific.com`
- `https://erp.greenleafpacific.com`
- `https://cgi.greenleafpacific.com`
- `https://sg.greenleafpacific.com`
- `https://spa.com.fj`
- `https://furniture.com.fj`
- `https://pacific.cleaning`
- `https://fiji.pacific.cleaning`
- `https://testing.erp.greenleafpacific.com`
- `https://testing.greenleafpacific.com`
- `https://testing2.greenleafpacific.com`
- `https://bulataxi.com`

`beautylab.spa.com.fj` and `trexfiji.com` are intentionally not active public
alerts yet because their DNS/certificate state is not production-ready.

## Apply And Verify

On `con`:

```bash
cd /root/monitoring
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose restart prometheus
```

Verify all public checks:

```bash
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=probe_success%7Bjob%3D%22blackbox_http_services%22%7D'
```

Expected current count: `13` targets with value `1`.

## Flapping Policy

`public-site-down` requires 5 minutes of failed public HTTP probes before paging.
Shorter one-off failures should be investigated through Prometheus history, but
should not page by default.

For Cloudflare-proxied or policy-drifted domains, a public probe only proves the
edge path. If an incident suggests origin slowness, verify the direct origin from
`cloud` and compare Caddy logs with blackbox probe timing.
