#!/usr/bin/env bash
set -euo pipefail

# Run daily full backups for all stacks except ERP.

STACKS_ROOT="/home/csrss/stacks"
ERP_STACKS=("erp.greenleafpacific.com")

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

mapfile -t all_stacks < <(find "${STACKS_ROOT}" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort)

declare -A skip=()
for s in "${ERP_STACKS[@]}"; do
  skip["$s"]=1
done

targets=()
for s in "${all_stacks[@]}"; do
  if [[ -n "${skip[$s]:-}" ]]; then
    continue
  fi
  targets+=("$s")
done

args=(--label stacks)
for s in "${targets[@]}"; do
  args+=(--stack "$s")
done

/home/csrss/backup/per-stack-backup.sh "${args[@]}"
