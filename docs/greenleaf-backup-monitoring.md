# Green Leaf backup observations

Implementation record: `2026-09-09 UTC`. This adds **read-only monitoring**, not
backup execution in Rabbit Platform. Backup jobs, storage access, restore tests,
retention and credentials remain customer-owned on `cloud`.

## Deployment status

- Customer collectors and the existing metrics-service drop-in have been
  installed on `cloud`; end-to-end native exporter/Prometheus verification is
  still pending at this record's creation.
- The central rules, dedicated network attachment and platform read-only view
  are prepared in source. **Central/platform production activation is pending.**
- Existing Keycloak backup and isolated database restore evidence is described
  in `greenleaf_cloud-server/docs/services/keycloak-sso.md`. Full application
  recovery is **not verified**; a restored database is not a tested login.

Update this status only after observing the deployed rule group, scoped API and
authenticated platform view. A local test is not deployment evidence.

## Data path and source ownership

```text
cloud: existing backup jobs → private metadata → native node_exporter :9100
  → deployment Prometheus → company=greenleaf enforcing proxy
  → rabbit_backup_observations internal network → platform read-only projection
```

| Component | Authoritative implementation / runtime path |
| --- | --- |
| Customer backup procedures | `greenleaf_cloud-server/docs/runbooks/backups.md` |
| Generic collector | `greenleaf_cloud-server/ops/backups/cloud-backup-metrics.sh` → `/usr/local/bin/cloud-backup-metrics.sh` |
| SSO collector | `greenleaf_cloud-server/ops/backups/greenleaf-sso-backup-metrics.py` → `/usr/local/sbin/greenleaf-sso-backup-metrics` |
| Existing schedule | `cloud-backup-metrics.timer` → `cloud-backup-metrics.service`; no second timer |
| Service extension | `/etc/systemd/system/cloud-backup-metrics.service.d/greenleaf-sso.conf` |
| Actual cloud textfiles | `/var/lib/prometheus/node-exporter/{greenleaf-backups,greenleaf-sso-backups}.prom` |
| Rules | `monitoring/prometheus/rules/greenleaf-backups.yml`, group `greenleaf_backup_observations` |
| Central network attachment | `deploy/deployment-monitoring-compose.yml` |
| Platform overlay | `rabbit-platform/deploy/compose.operator-backup-monitoring.yml` |
| Platform projection | `rabbit-platform/internal/backupmonitoring/`, authenticated `GET /api/v1/workspaces/{workspaceID}/backup-monitoring` |

The native cloud exporter reads `/var/lib/prometheus/node-exporter`, **not** the
old `/var/lib/node-exporter-textfile` target. A successful collector writing to
the wrong directory does not establish scrape visibility. The customer repo is
authoritative for installed collectors; this repo's older
`scripts/cloud-backup-metrics.sh` and `docs/cloud-backup-inspection.md` describe
legacy behavior and must not overwrite the current source.

## Trust and verification levels

- Generic full archives: local/remote timestamp, manifest presence and nonzero
  size. Remote objects are inspected through direct rclone, not the FUSE mount.
  These observations establish **archive presence**, not consistency,
  checksums or restoration. Daily full archives include ERP.
- ERP operational profile: a separate **local** six-hour archive. It is not a
  six-hour off-host full copy and must not share that interpretation.
- SSO local: bounded private manifest/checksum metadata and nonempty regular
  artifact presence. The collector stats, but never opens, the database dump
  or deployment/secrets archive; it does not rehash their contents.
- SSO remote: a matching `remote-verified.json` with literal boolean
  `remote_download_verified: true`, exact backup ID and valid verification time.
  This records the backup process's download comparison; it is not a fresh
  independent remote availability check.
- SSO database restore: matching `restore-verified.json` with
  `database_restore: verified` and literal `scratch_container_removed: true`.
  Application restore requires a separate explicit `keycloak_login_test:
  verified` receipt. Current application status remains not verified.

Restore timestamps are historical evidence for a tested backup, not proof that
every newer backup restores. The root-only SSO collector accepts only fixed
metadata filenames beneath `/var/backups/greenleaf-sso`, rejects symlinks,
unsafe permissions, malformed/oversized data, mismatched IDs and dates more than
60 seconds ahead. It publishes fixed labels `company=greenleaf`, `alias=cloud`,
`stack=sso.greenleafpacific.com`; no secret, receipt body or private path is
copied to Prometheus or the platform.

SSO state `-1` means unknown/never run/in progress, not success. Timer success
requires enabled **and** active. Collector errors publish current attempt time
with `collector_success=0`; publication failure retains the old atomic file,
which must age out. The `ExecStartPre=-...` extension does not block the legacy
collector if SSO observation fails. Published textfiles are atomic `0644` files.

## Freshness and alert semantics

| Observation | Condition / pending period |
| --- | --- |
| Generic or SSO telemetry | 15-minute freshness, no more than 60 seconds ahead; unavailable/invalid for 10 minutes |
| Daily remote full archive, including ERP | Missing/incomplete or older than 25 hours, for 10 minutes |
| ERP local operational archive | Missing/incomplete or older than 7 hours, for 5 minutes |
| SSO verified remote logical backup | Missing or older than 25 hours, for 10 minutes |
| SSO latest completed run | Failed for 5 minutes, even if an older good backup exists |
| Backup timer | Not enabled and active, for 10 minutes |
| FUSE browse mount | Unhealthy for 30 minutes; warning, not proof direct upload failed |

The recording rules also require successful `node_exporter_clients` scraping
and `node_textfile_scrape_error=0`; SSO additionally requires collector success.
Missing observation is **unknown backup state**, not a claim of data loss.
SSO is excluded from generic stack discovery/alerts because it has a separate
logical backup. The rules do not invent a full-restore alarm or a restore SLA.

Fixed SSO alert identities retain an unavailable-evidence condition after
telemetry disappears. For dynamic generic stack/timer labels, rules preserve
known series using **only a two-day history window**. After that window expires,
a per-stack alert can end without a fresh successful backup. The fixed
`CloudBackupMetricsMissing` alert remains; do not interpret label expiry as a
verified recovery. Persistent expected-backup inventory/reconciliation is a
future improvement. `keep_firing_for: 5m` is a debounce, not durable inventory.

Alerts use the existing Prometheus → Alertmanager → incident gateway → Telegram
admin route. No second sender, webhook owner or platform notification engine is
introduced. Do not suppress the observation alert to obtain a green dashboard.

## Platform isolation

Create `rabbit_backup_observations` as an **internal** external Docker network;
Compose references it but does not create or prove its isolation. Attach only
the platform API and existing `monitoring-prom-label-proxy-greenleaf` to this
dedicated link. The proxy retains its monitoring-side attachment to reach
Prometheus and enforces `company=greenleaf` with `-error-on-replace`.

The platform overlay sets `RABBIT_BACKUP_PROMETHEUS_URL` to
`http://monitoring-prom-label-proxy-greenleaf:8080`, not raw Prometheus. Worker
and database receive no monitoring attachment or backup credentials. No new
host/public port is needed. Verify the network's `Internal` flag and membership
before activation; never connect the platform to the whole monitoring network.

The API accepts no caller-supplied PromQL, target URL or query parameters. It
requires authenticated workspace access plus `workspace.read` and
`monitoring.open`; only `ws-greenleaf` is configured. The server uses a fixed
metric allowlist and bounded requests. Other customers do not inherit Green
Leaf observations. This view cannot start/stop a backup, restore data or change
timers. Unknown or stale data must remain distinguishable from healthy state.

## Validation and response

Before central activation, run `promtool check rules` on the new rule file and
`promtool test rules tests/greenleaf-backups.test.yml` from the repository root.
Fixtures cover daily/local cadence, failed and missing evidence, partial fields,
database/application distinction and disappearance without immediate recovery.
Source collector tests live in the customer repo. Observe actual exporter
samples and scoped proxy results separately; do not trigger a production backup
or Telegram canary merely to validate read access.

For an alert: identify its profile, inspect collector freshness first, then
systemd metadata and the exact expected artifact/receipt. Check whether a job is
already running before any separately authorized execution. Do not read/archive
secrets into a support log or delete backup sets as a monitoring repair.

Rollback the optional platform projection independently of customer backups.
Do not remove valid collector path configuration, stop backup timers, restart
the old central stack on `con`, or enable a second Telegram sender. Removing an
active rule can appear as recovery; preserve incident evidence and review that
effect before rule rollback.
