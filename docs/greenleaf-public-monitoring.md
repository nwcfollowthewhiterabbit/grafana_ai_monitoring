# Greenleaf Public Monitoring

Greenleaf public endpoints are monitored from `con` through two layers:

- `blackbox_http_services` for frequent diagnostic probes.
- `scheduled-public-site-checker` for notification-grade availability decisions.

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

`public-site-down` is based on `scheduled_public_site_confirmed_down`, not raw
`probe_success` from the blackbox job.

The scheduled checker runs once every 3 hours. It puts URLs from
`monitoring/service-catalog.yml` into a stable queue, checks them with bounded
concurrency, and does not fan out all targets at once. If a URL fails the first
check, the checker runs 3 additional checks for that URL with 5 minutes between
retry rounds. A notification is eligible only when at least 3 attempts in that
cycle fail.

The current production timer is:

```text
scheduled-public-site-checker.timer
```

The current textfile metrics path is:

```text
/var/lib/node-exporter-textfile/scheduled-public-sites.prom
```

For Cloudflare-proxied or policy-drifted domains, a public probe only proves the
edge path. If an incident suggests origin slowness, verify the direct origin from
`cloud` and compare Caddy logs with blackbox probe timing.

## Scheduled Checker Apply

On `con`:

```bash
cd /root/monitoring
python3 scripts/scheduled-public-site-checker.py --retry-interval 1 --retry-count 0 --output /tmp/scheduled-public-sites.prom
sudo systemctl daemon-reload
sudo systemctl enable --now scheduled-public-site-checker.timer
sudo systemctl restart scheduled-public-site-checker.service
```

Verify metrics:

```bash
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=scheduled_public_site_target_count'
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=scheduled_public_site_confirmed_down'
```
