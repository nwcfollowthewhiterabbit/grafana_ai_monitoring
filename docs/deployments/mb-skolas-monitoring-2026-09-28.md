# MB Skolas ERP Live/Test monitoring rollout

Status: implementation prepared; **not deployed**. This file is a reviewed
deployment plan, not a runtime receipt. Backups of Live/Test are a separate
future task and are not represented by these signals.

## Exact identity and scope

- Customer/workspace: MB Skolas / `ws-mb-skolas`.
- Existing host: SSH alias `wherp`, `77.237.244.169`, monitoring labels
  `company="mb-skolas", alias="wherp"`. Both stacks share this physical VPS.
- Live application: Swarm stack `erpnext3pl`, public URL
  `https://erpnext.77.237.244.169.sslip.io`, criticality `high`.
- Test application: Swarm stack `erpnext3plstg`, public URL
  `https://erpnext-staging.77.237.244.169.sslip.io`, criticality `medium`.
- Private relay port for this host: `172.23.0.1:19133`; the adjacent 19132
  belongs to Rabbit Systems FPC and must remain unchanged.
- Host observations: node-exporter CPU, RAM and root filesystem. Application
  observations: existing `docker-stack-metrics.sh` textfile collector and
  public HTTP/TLS Blackbox checks. cAdvisor, logs, backups, browser journeys,
  provider control and customer Grafana access are outside this rollout.
- Platform server identity is already `mb-skolas:wherp`. It is Git-managed
  through this catalog; this rollout does not use the not-yet-implemented
  existing-server adoption action or invent a Contabo instance binding.

Read-only check on 2026-09-28: Live and Test HTTPS roots each returned 200 from
the monitoring host; `wherp` had both Swarm stacks running but no node-exporter,
cAdvisor, Alloy or Promtail listener/container. The central Prometheus, Grafana,
Alertmanager, incident gateway and Rabbit Platform were running. These checks
do not establish the future metrics path.

## Source reconciliation gate

The active monitoring checkout `/opt/rabbit-monitoring-v2` is at `9987dda` with
uncommitted changes in the catalog, HTTP targets, deployment renderer, SSHD
fragment, documentation and tests, plus an untracked relay unit. Those changes
belong to another rollout. Preserve their complete diff and non-secret file
checksums in a private backup; do not reset, clean, pull over, or recursively
copy onto that checkout. The reviewed MB changes must be combined with those
changes in a separate clean release checkout, resolved file by file, tested,
and published as one pinned revision before any live configuration is replaced.
GitHub `main` also predates the deployed Managed Monitoring v2 lineage; restore
canonical source control before calling this rollout complete. A direct merge
of this small patch into old `main` is not a valid release.

The 2026-09-28 source reconciliation retained the live Greenleaf relocation and
cloud cAdvisor relay as a separate commit, then kept the newer FPC source and
added MB Skolas. A read-only comparison found that all 15 active HTTP targets
match the candidate's non-MB targets exactly and that active rule files and
Windows targets match. The rendered Prometheus configuration differs from the
mounted runtime only by the prospective MB node target and its `19133` private
relabel. Timestamped `.backup`/`.before-*` files in the mounted directory are
retained runtime snapshots, not scrape inputs. This comparison is source
evidence, **not** an activation receipt; rerun it against the release SHA
immediately before deployment.

Before any change, back up the exact runtime configs, data and environment
required by the repository's current deployment procedure, validate archive
readability, and confirm server identity. Do not expose credential contents.
Review the existing Grafana/Alertmanager route so a new target does not create
an unplanned notification storm during activation.

### Operator preflight and private snapshots

This is an operator sequence, not a script that can be run unattended. Stop at
any mismatch. From the MB Skolas workspace, run the required project identity
gate **before either SSH connection**:

```sh
cd '/Users/bc/!RS/MB Skolas'
python3 scripts/validate_project_identity.py
ssh wherp 'hostname; hostname -I; docker stack ls --format "{{.Name}}"'
ssh deployment 'hostname; hostname -I; docker ps --format "{{.Names}}"'
```

Confirm `wherp` is `vmi3335569` / `77.237.244.169`, contains both
`erpnext3pl` and `erpnext3plstg`, and `deployment` is `vmi3489272` /
`169.58.132.8` with the sole central `monitoring-prometheus`. Confirm the
existing monitoring checkout SHA, `git status --short`, `sshd -T`, the exact
service units and ports 19100/19133 before writing. Obtain the fresh MB Skolas
ERP backup required by the project deployment rules and verify its archive;
that backup is not itself a monitoring signal.

On `deployment`, create a **new, timestamped, root-only** snapshot directory.
Save the current `/etc/rabbit-monitoring/prometheus` tree, relevant SSHD
configuration, active Compose manifest, `git diff --binary` and the exact
untracked relay unit from `/opt/rabbit-monitoring-v2`. On `wherp`, likewise
save its current SSHD configuration, any existing host-metrics units and
Compose files, plus the list of its Swarm services. Check that each snapshot
can be read before proceeding. Keep config snapshots private because they may
contain credentials; do not copy them into Git or post them in chat.

Do **not** perform `git pull`, `git reset`, `git clean`, an in-place checkout,
recursive `rsync`, or `docker compose down` on either existing application or
monitoring tree. Resolve the central dirty diff in a separate release checkout
and pin its full commit SHA. The `/opt/rabbit-monitoring-v2` tree stays
unchanged until its separate canonical-source reconciliation is complete.

## Private host collector and relay

1. On `wherp`, verify existing service names and that TCP `127.0.0.1:19100`
   is free. Install the pinned `deploy/mb-skolas-host-metrics.compose.yml` in
   an isolated `/opt/rabbit-host-metrics` directory. Create the root-owned
   `/var/lib/node-exporter-textfile` with mode 0755 before Compose starts.
   Install the reviewed `scripts/mb-docker-stack-metrics.sh` at the path
   referenced by the new systemd service, owned by root and not writable by
   others. This collector selects only current tasks from `erpnext3pl` and
   `erpnext3plstg`, samples Docker stats in one batch, and leaves the generic
   collector used by other hosts untouched.
2. Run the Docker collector once and inspect its exit status, output freshness,
   `docker_stack_container_running` series for all nine expected services in
   each of `erpnext3pl` and `erpnext3plstg`, and file readability by UID 65534.
   Measure the script's duration/host load before enabling its three-minute
   timer. The previous generic collector took 111 seconds on this host because
   it traversed 115 current and historical task containers; do not enable the
   timer until the MB-only collector is confirmed substantially faster. It
   reads Docker metadata/stats; it does not restart app stacks or mount the
   Docker socket into the exporter.
3. Start the node-exporter and verify the `/metrics` endpoint from loopback
   only. Verify no listening socket on a public interface, and no existing
   Swarm service changes. Do not expose port 9100/19100 publicly.
4. Generate a dedicated Ed25519 key on `wherp`; transfer only its public key to
   the monitoring host. Pin that host's already reviewed SSH host key. Create
   only the restricted destination account `monitoring-wherp`, limited to the
   exact source IP and `PermitListen 172.23.0.1:19133`. Add its section from
   `deploy/host-metrics-sshd.conf` without replacing unrelated current sections;
   run `sshd -t` before reload. Reuse the generic
   `rabbit-host-metrics-relay@.service` on `wherp` with
   `LISTEN=172.23.0.1:19133` in a protected local environment file.
5. Confirm that the reverse-forwarded socket is bound only to the private
   `172.23.0.1` monitoring bridge, the relay reconnects after an SSH break,
   and Prometheus can fetch the real node metrics through it. No private key
   moves to Rabbit Platform, Git or the monitoring host.

## Central monitoring activation

1. Reconcile the dirty checkout first. In the combined clean release, retain
   every unrelated target and relay, add only `node-exporter-wherp:9100` with
   exact company/alias labels, and rewrite that target to private bridge port
   19133 in `scripts/render-deployment-monitoring.py`. The rendered `instance`
   label must remain the stable original target, not the relay address.
2. Render to a staging directory. Validate the whole Prometheus config with
   `promtool check config`, then compare generated targets, rules and dashboard
   files with the current runtime. The central Compose mount reads
   `/etc/rabbit-monitoring/prometheus`, not the dirty checkout. Stage and
   compare at least the exact files below, then copy only these reviewed
   targets into the mounted tree:

   - `prometheus.yml` (adds one node exporter target and its private relabel);
   - `file_sd/http_targets.yml` (adds two HTTP/TLS probes).

   No unrelated rules, Grafana provisioning, Alertmanager, Loki or private
   `.env` files need replacement for this onboarding. The Prometheus image is
   `prom/prometheus:v3.4.0`; validate the **staged complete configuration**
   using its `promtool`, not a partial YAML parse. After a final diff against
   the protected snapshot, signal the running `monitoring-prometheus` with
   `HUP` (its Compose command does not enable the HTTP reload endpoint).
   Inspect its log and `/api/v1/status/config`, then check old target counts
   and the two new targets. If validation or reload fails, restore just the
   two snapshotted files and send another `HUP`; do not restart or replace the
   central data stores.
3. Wait for three fresh `up=1` scrapes for `company="mb-skolas",alias="wherp"`,
   then for the five-minute CPU rate window. Check RAM, root filesystem and
   textfile scrape errors. Confirm `rs_monitoring_docker_telemetry_fresh=1`,
   both app statuses, and all expected components against actual Swarm state.
4. Once those sources are present, activate the catalog/status and regenerate
   `http_targets.yml` with `scripts/render-monitoring-config.py`. Run the
   existing service-event inventory generator to publish the two applications.
   Confirm separate Blackbox results: Live `high`, Test `medium`, plus TLS
   expiry observations. Both probes are deliberately availability-only; the
   heuristic integrity checker is not enabled for these authenticated ERP sites.
5. Watch initial incident routing and verify that no preexisting unrelated
   targets, rules, Grafana identities or customer access changed.

The safe publication boundary is **after** the private relay, exporter and
textfile series are observed. Do not run the regular service-event publisher
against the prepared post-activation catalog while source telemetry is absent.
If that publisher's runtime still points at `/opt/rabbit-monitoring-v2`, update
only its reviewed catalog input/path through the normal release mechanism;
do not overwrite the checkout to make it work. Save its previous unit/config
and confirm the generated inventory diff contains only the MB Skolas additions.

The checked-in catalog represents the **post-activation** state; do not publish
its active status to runtime before collector and scrape evidence are present.
If activation stops earlier, retain `pending_discovery`/unknown rather than
claiming a healthy host or applications.

## Rabbit Platform projection

After the monitoring catalog has a reviewed full commit SHA, run Rabbit
Platform's `scripts/generate-infrastructure-catalog.py` against that exact
monitoring revision, review the `mb-skolas:wherp` row, and run `--check`.
Release the projection through Platform's normal image/CI/verification path.
Its existing authorized inventory API will then return fresh CPU/RAM/root
metrics and the two separate application rows/URLs inside `ws-mb-skolas`.
The Platform worker's managed-stand SSH collector excludes legacy catalog
hosts, so enabling that worker is not an alternative to this private
Prometheus path. The existing server's provider binding remains `unbound`
until its exact account and instance ID are independently verified.

## Verification and rollback

Run strict catalog validation, HTTP target renderer `--check`, focused Python
tests, repository validation/CI, Prometheus config/rule checks, and scoped
runtime reads. On Rabbit Platform verify only the authorized MB workspace
sees this server and exactly two applications. Before/after snapshots must
show no ERP container replacement or warehouse data mutation.

For rollback, restore the previous reviewed monitoring catalog, HTTP targets
and Prometheus scrape config, reload Prometheus, and reconcile any incident
opened during the window. Then stop the dedicated relay/timer/exporter and
revoke only the `monitoring-wherp` public key/account. Preserve monitoring
history and all customer stacks. Roll back the Rabbit Platform catalog
projection to the previous pinned revision if its release had completed.
The preflight snapshot and baseline `up`/HTTP results are the rollback receipt;
retain them until both environments have been observed through a full checking
cycle.
