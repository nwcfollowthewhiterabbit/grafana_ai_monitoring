# Greenleaf Public Monitoring

Greenleaf public endpoints are monitored from `con` through three independent
signals:

- `blackbox_http_services` performs frequent HTTP/TLS probes and is the source of
  the production `PublicSiteDown` rules.
- `scheduled-public-site-checker` runs a lower-frequency queued/retrying check
  and provides independent supporting evidence plus checker-health metrics.
- `site-integrity-checker` runs twice daily and looks for explicit empty/error
  pages and failed critical resources without comparing normal content to a
  golden page.

Infrastructure/container health and these external-interface signals remain
independent. A healthy container does not prove that a page works, and a public
edge response does not prove that every origin component is healthy.

## Source Of Truth

- Monitoring inventory: `monitoring/service-catalog.yml`
- Prometheus scrape config: `monitoring/prometheus/prometheus.yml`
- Production routing inventory: `greenleaf_cloud-server:ops/public-sites.yml`
- Production routing runbook: `greenleaf_cloud-server:docs/runbooks/public-sites.md`

When a production public site is added, removed, or disabled, update both the
production routing inventory and this monitoring repo in the same change window.

## Active Public Checks

The catalog verified on `2026-09-07 UTC` contains 13 active Greenleaf `cloud`
public HTTPS checks:

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
docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml
docker kill --signal HUP monitoring-prometheus
```

This validates and reloads the live files already mounted from
`/root/monitoring`. Sync only the reviewed files into that tree; never copy the
repository over it wholesale or operate the production Compose project with a
partial file set and `--remove-orphans`.

Verify all public checks:

```bash
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=probe_success%7Bjob%3D%22blackbox_http_services%22%7D'
```

Expected inventory count: `13` series. Individual values can be `0` during a
real endpoint incident; the series count and probe result are separate checks.

## Availability thresholds and supporting evidence

For critical/high endpoints, `PublicSiteDown` fires only after the entire
10-minute `probe_success` window has no success and the rule remains pending for
another 2 minutes. Medium-criticality non-production endpoints use a 15-minute
window. The queued checker is not referenced by either alert expression.

The scheduled checker runs once every 3 hours. It puts URLs from
`monitoring/service-catalog.yml` into a stable queue, checks them with bounded
concurrency, and does not fan out all targets at once. If a URL fails the first
check, the checker runs 3 additional checks for that URL with 5 minutes between
retry rounds. `scheduled_public_site_confirmed_down` becomes evidence only when
at least 3 attempts in that cycle fail. Operators compare it with Blackbox
history when diagnosing an incident; it does not directly open or close the
production availability incident.

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

The service runs the checker from the versioned checkout at
`/opt/rabbit-monitoring-v2`. After updating the checkout or unit files on `con`:

```bash
cd /opt/rabbit-monitoring-v2
python3 scripts/scheduled-public-site-checker.py --help
sudo install -m 0644 systemd/scheduled-public-site-checker.service /etc/systemd/system/
sudo install -m 0644 systemd/scheduled-public-site-checker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scheduled-public-site-checker.timer
sudo systemctl restart scheduled-public-site-checker.service
```

Verify metrics:

```bash
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=scheduled_public_site_target_count'
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=scheduled_public_site_confirmed_down'
```

The integrity timer is `site-integrity-checker.timer`; its checked-in schedule
is 02:15 and 14:15 daily with up to 15 minutes of randomized delay. Verify its
self metrics separately from availability:

```bash
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=site_integrity_checker_up'
curl -sS 'http://127.0.0.1:9090/api/v1/query?query=site_integrity_confirmed_problem'
```
