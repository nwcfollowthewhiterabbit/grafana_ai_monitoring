# Cloud Backup Inspection

Inspected host: `cloud`

Repository with operational documentation:

- Path: `/home/csrss/greenleaf_cloud-server`
- Remote: `git@github.com:nwcfollowthewhiterabbit/greenleaf_cloud-server.git`
- Backup runbook: `docs/runbooks/backups.md`
- Backup issue note: `docs/issues/greenleafbackup-rclone-io-error.md`

## Active Design

- `/greenleafbackup` is an rclone mount to Wasabi bucket `wasabi:greenleafbackup`.
- Mount service: `greenleafbackup-mount.service`.
- Main scheduled backup file: `/etc/cron.d/greenleaf-backup`.
- ERP stack backup runs every 6 hours:
  - `/home/csrss/backup/run-erp-backup.sh`
  - target stack: `erp.greenleafpacific.com`
- Daily stack backup is intended to run at `02:00 UTC`:
  - `/home/csrss/backup/run-daily-backups.sh`
  - target: all stacks except ERP.

## Findings

- The Wasabi mount was healthy during inspection and could be listed.
- ERP backups are present and fresh under:
  - `/greenleafbackup/backups/vps-c8572e16/stacks/erp.greenleafpacific.com`
- The daily non-ERP wrapper was broken:
  - it passed all stack names after a single `--stack`
  - `per-stack-backup.sh` expects repeated `--stack NAME`
  - observed failure: `Unknown option: beautylab.spa.com.fj`
- Restic backup unit exists:
  - `backup-restic.service`
  - `backup-restic.timer`
  - timer is disabled/inactive, so it is not part of active backup scheduling.

## Monitoring Added

Exporter:

- `/usr/local/bin/cloud-backup-metrics.sh`
- systemd timer: `cloud-backup-metrics.timer`
- textfile output: `/var/lib/node-exporter-textfile/greenleaf-backups.prom`

Metrics include:

- rclone mount health
- cron file presence
- per-stack backup count
- per-stack newest backup timestamp
- latest archive size
- manifest presence
- latest volume archive count
- restic script/log/local repo/timer state

Dashboard:

- `Cloud Backups`
- UID: `cloud-backups`
