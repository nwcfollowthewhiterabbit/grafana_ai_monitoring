#!/usr/bin/env bash
set -uo pipefail

TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node-exporter-textfile}"
OUTPUT_FILE="${OUTPUT_FILE:-${TEXTFILE_DIR}/greenleaf-backups.prom}"
BACKUP_ROOT="${BACKUP_ROOT:-/greenleafbackup}"
STACKS_ROOT="${STACKS_ROOT:-/home/csrss/stacks}"
BACKUP_LABEL="${BACKUP_LABEL:-stacks}"
HOST_ALIAS="${HOST_ALIAS:-cloud}"
COMPANY="${COMPANY:-greenleaf}"
HOSTNAME_SHORT="$(hostname -s)"
DEST_ROOT="${BACKUP_ROOT}/backups/${HOSTNAME_SHORT}/${BACKUP_LABEL}"
RESTIC_SCRIPT="${RESTIC_SCRIPT:-/opt/backups/scripts/backup-restic.sh}"
RESTIC_LOG="${RESTIC_LOG:-/opt/backups/backup.log}"
RESTIC_LOCAL_REPO="${RESTIC_LOCAL_REPO:-/opt/backups/restic-local}"
CRON_FILE="${CRON_FILE:-/etc/cron.d/greenleaf-backup}"

mkdir -p "${TEXTFILE_DIR}"
tmp="$(mktemp "${OUTPUT_FILE}.tmp.XXXXXX")"

escape_label() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\n//g'
}

metric_labels() {
  printf 'company="%s",alias="%s"' "$(escape_label "${COMPANY}")" "$(escape_label "${HOST_ALIAS}")"
}

timestamp_to_epoch() {
  local ts="$1"
  date -u -d "${ts:0:4}-${ts:4:2}-${ts:6:2} ${ts:9:2}:${ts:11:2}:${ts:13:2}" +%s 2>/dev/null || printf '0'
}

write_header() {
  cat >"${tmp}" <<'EOF'
# HELP greenleaf_backup_mount_healthy Whether the remote backup mount can be listed.
# TYPE greenleaf_backup_mount_healthy gauge
# HELP greenleaf_backup_cron_present Whether the expected backup cron file exists.
# TYPE greenleaf_backup_cron_present gauge
# HELP greenleaf_backup_stack_configured Whether a local stack directory exists and should have backups.
# TYPE greenleaf_backup_stack_configured gauge
# HELP greenleaf_backup_stack_backup_count Number of backup directories found for a stack.
# TYPE greenleaf_backup_stack_backup_count gauge
# HELP greenleaf_backup_stack_latest_timestamp_seconds Unix timestamp of the newest backup directory for a stack.
# TYPE greenleaf_backup_stack_latest_timestamp_seconds gauge
# HELP greenleaf_backup_stack_latest_manifest_present Whether manifest.txt exists in the newest backup directory.
# TYPE greenleaf_backup_stack_latest_manifest_present gauge
# HELP greenleaf_backup_stack_latest_archive_bytes Size of the newest stack archive file.
# TYPE greenleaf_backup_stack_latest_archive_bytes gauge
# HELP greenleaf_backup_stack_latest_volume_archives Number of volume archive files in the newest backup directory.
# TYPE greenleaf_backup_stack_latest_volume_archives gauge
# HELP greenleaf_backup_restic_script_present Whether the restic backup script exists.
# TYPE greenleaf_backup_restic_script_present gauge
# HELP greenleaf_backup_restic_log_present Whether the restic backup log exists.
# TYPE greenleaf_backup_restic_log_present gauge
# HELP greenleaf_backup_restic_local_repo_present Whether the local restic repo directory exists.
# TYPE greenleaf_backup_restic_local_repo_present gauge
# HELP greenleaf_backup_restic_scheduled Whether the restic backup timer is enabled or active.
# TYPE greenleaf_backup_restic_scheduled gauge
EOF
}

write_header
base_labels="$(metric_labels)"

mount_healthy=0
if mountpoint -q "${BACKUP_ROOT}" && timeout 20 find "${BACKUP_ROOT}" -maxdepth 1 -mindepth 1 -print -quit >/dev/null 2>&1; then
  mount_healthy=1
fi
printf 'greenleaf_backup_mount_healthy{%s,path="%s",backend="rclone_wasabi"} %s\n' "${base_labels}" "$(escape_label "${BACKUP_ROOT}")" "${mount_healthy}" >>"${tmp}"

cron_present=0
[[ -f "${CRON_FILE}" ]] && cron_present=1
printf 'greenleaf_backup_cron_present{%s,path="%s"} %s\n' "${base_labels}" "$(escape_label "${CRON_FILE}")" "${cron_present}" >>"${tmp}"

if [[ -d "${STACKS_ROOT}" ]]; then
  while IFS= read -r stack_path; do
    stack="$(basename "${stack_path}")"
    stack_label="$(escape_label "${stack}")"
    printf 'greenleaf_backup_stack_configured{%s,stack="%s"} 1\n' "${base_labels}" "${stack_label}" >>"${tmp}"

    stack_backup_dir="${DEST_ROOT}/${stack}"
    backup_count=0
    latest=""
    if [[ "${mount_healthy}" -eq 1 && -d "${stack_backup_dir}" ]]; then
      while IFS= read -r backup_name; do
        [[ "${backup_name}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || continue
        backup_count=$((backup_count + 1))
        latest="${backup_name}"
      done < <(find "${stack_backup_dir}" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' 2>/dev/null | sort)
    fi

    latest_epoch=0
    manifest_present=0
    archive_bytes=0
    volume_archives=0
    if [[ -n "${latest}" ]]; then
      latest_epoch="$(timestamp_to_epoch "${latest}")"
      latest_dir="${stack_backup_dir}/${latest}"
      [[ -f "${latest_dir}/manifest.txt" ]] && manifest_present=1
      archive_path="${latest_dir}/${stack}.tar.gz"
      if [[ -f "${archive_path}" ]]; then
        archive_bytes="$(stat -c '%s' "${archive_path}" 2>/dev/null || printf '0')"
      fi
      if [[ -d "${latest_dir}/volumes" ]]; then
        volume_archives="$(find "${latest_dir}/volumes" -maxdepth 1 -type f -name '*.tar.gz' 2>/dev/null | wc -l | tr -d ' ')"
      fi
    fi

    printf 'greenleaf_backup_stack_backup_count{%s,stack="%s"} %s\n' "${base_labels}" "${stack_label}" "${backup_count}" >>"${tmp}"
    printf 'greenleaf_backup_stack_latest_timestamp_seconds{%s,stack="%s"} %s\n' "${base_labels}" "${stack_label}" "${latest_epoch}" >>"${tmp}"
    printf 'greenleaf_backup_stack_latest_manifest_present{%s,stack="%s"} %s\n' "${base_labels}" "${stack_label}" "${manifest_present}" >>"${tmp}"
    printf 'greenleaf_backup_stack_latest_archive_bytes{%s,stack="%s"} %s\n' "${base_labels}" "${stack_label}" "${archive_bytes}" >>"${tmp}"
    printf 'greenleaf_backup_stack_latest_volume_archives{%s,stack="%s"} %s\n' "${base_labels}" "${stack_label}" "${volume_archives}" >>"${tmp}"
  done < <(find "${STACKS_ROOT}" -maxdepth 1 -mindepth 1 -type d | sort)
fi

restic_script_present=0
restic_log_present=0
restic_local_repo_present=0
restic_scheduled=0
[[ -f "${RESTIC_SCRIPT}" ]] && restic_script_present=1
[[ -f "${RESTIC_LOG}" ]] && restic_log_present=1
[[ -d "${RESTIC_LOCAL_REPO}" ]] && restic_local_repo_present=1
if systemctl is-enabled --quiet backup-restic.timer 2>/dev/null || systemctl is-active --quiet backup-restic.timer 2>/dev/null; then
  restic_scheduled=1
fi
printf 'greenleaf_backup_restic_script_present{%s,path="%s"} %s\n' "${base_labels}" "$(escape_label "${RESTIC_SCRIPT}")" "${restic_script_present}" >>"${tmp}"
printf 'greenleaf_backup_restic_log_present{%s,path="%s"} %s\n' "${base_labels}" "$(escape_label "${RESTIC_LOG}")" "${restic_log_present}" >>"${tmp}"
printf 'greenleaf_backup_restic_local_repo_present{%s,path="%s"} %s\n' "${base_labels}" "$(escape_label "${RESTIC_LOCAL_REPO}")" "${restic_local_repo_present}" >>"${tmp}"
printf 'greenleaf_backup_restic_scheduled{%s,path="%s"} %s\n' "${base_labels}" "$(escape_label "${RESTIC_SCRIPT}")" "${restic_scheduled}" >>"${tmp}"

chmod 0644 "${tmp}"
mv "${tmp}" "${OUTPUT_FILE}"
