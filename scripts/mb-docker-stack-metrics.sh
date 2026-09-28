#!/usr/bin/env bash
# Current MB Skolas Swarm tasks only. A single Docker stats request avoids
# serial sampling of every historical task container on this busy host.
set -euo pipefail

out_dir="${MB_METRICS_OUTPUT_DIR:-/var/lib/node-exporter-textfile}"
[[ -d "$out_dir" && ! -L "$out_dir" ]] || {
  echo 'Metrics output directory is missing or unsafe' >&2
  exit 1
}
out="$out_dir/docker-stacks.prom"
tmp="$(mktemp "$out_dir/.docker-stacks.prom.XXXXXXXX")"
stats_tmp="$(mktemp /tmp/mb-docker-stats.XXXXXXXX)"
trap 'rm -f -- "$tmp" "$stats_tmp"' EXIT

bytes() {
  local value number unit
  value="$(printf '%s' "$1" | xargs)"
  [[ -n "$value" ]] || { echo 0; return; }
  number="$(printf '%s' "$value" | sed -E 's/^([0-9.]+).*/\1/')"
  unit="$(printf '%s' "$value" | sed -E 's/^[0-9.]+[[:space:]]*//')"
  awk -v n="$number" -v u="$unit" 'BEGIN {
    m=1
    if (u=="kB" || u=="KB") m=1000
    else if (u=="MB") m=1000^2
    else if (u=="GB") m=1000^3
    else if (u=="TB") m=1000^4
    else if (u=="KiB") m=1024
    else if (u=="MiB") m=1024^2
    else if (u=="GiB") m=1024^3
    else if (u=="TiB") m=1024^4
    printf "%.0f", n*m
  }'
}
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\n/ /g'; }

live_ids="$(docker ps --filter label=com.docker.stack.namespace=erpnext3pl --format '{{.ID}}')"
test_ids="$(docker ps --filter label=com.docker.stack.namespace=erpnext3plstg --format '{{.ID}}')"
ids=()
for listing in "$live_ids" "$test_ids"; do
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    [[ "$id" =~ ^[0-9a-f]{12,64}$ ]] || {
      echo 'Docker returned an invalid container ID' >&2
      exit 1
    }
    ids+=("$id")
  done <<< "$listing"
done

if ((${#ids[@]})); then
  docker stats --no-stream \
    --format '{{.ID}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}' \
    "${ids[@]}" > "$stats_tmp"
fi

{
  echo '# HELP docker_stack_container_running Container running state by stack/service.'
  echo '# TYPE docker_stack_container_running gauge'
  echo '# HELP docker_stack_container_cpu_percent Docker reported CPU percent per container.'
  echo '# TYPE docker_stack_container_cpu_percent gauge'
  echo '# HELP docker_stack_container_memory_usage_bytes Docker reported memory usage per container.'
  echo '# TYPE docker_stack_container_memory_usage_bytes gauge'
  echo '# HELP docker_stack_container_memory_limit_bytes Docker reported memory limit per container.'
  echo '# TYPE docker_stack_container_memory_limit_bytes gauge'
  echo '# HELP docker_stack_container_memory_percent Docker reported memory percent per container.'
  echo '# TYPE docker_stack_container_memory_percent gauge'
  echo '# HELP docker_stack_container_net_rx_bytes Docker reported cumulative/network receive bytes display value.'
  echo '# TYPE docker_stack_container_net_rx_bytes gauge'
  echo '# HELP docker_stack_container_net_tx_bytes Docker reported cumulative/network transmit bytes display value.'
  echo '# TYPE docker_stack_container_net_tx_bytes gauge'
  echo '# HELP docker_stack_container_block_read_bytes Docker reported block read bytes.'
  echo '# TYPE docker_stack_container_block_read_bytes gauge'
  echo '# HELP docker_stack_container_block_write_bytes Docker reported block write bytes.'
  echo '# TYPE docker_stack_container_block_write_bytes gauge'
  echo '# HELP docker_stack_container_size_rw_bytes Container writable layer size from docker inspect --size.'
  echo '# TYPE docker_stack_container_size_rw_bytes gauge'
  echo '# HELP docker_stack_container_size_rootfs_bytes Container rootfs size from docker inspect --size.'
  echo '# TYPE docker_stack_container_size_rootfs_bytes gauge'

  for id in "${ids[@]}"; do
    # One inspect replaces the per-field CLI calls in the generic collector.
    if ! info="$(docker inspect --size --format '{{.Name}}|{{.Config.Image}}|{{.State.Status}}|{{index .Config.Labels "com.docker.stack.namespace"}}|{{index .Config.Labels "com.docker.swarm.service.name"}}|{{.SizeRw}}|{{.SizeRootFs}}' "$id" 2>/dev/null)"; then
      # A task removed between `ps` and `inspect` is absent, not healthy.
      continue
    fi
    IFS='|' read -r name image state stack swarm_service size_rw size_rootfs <<< "$info"
    [[ "$stack" == erpnext3pl || "$stack" == erpnext3plstg ]] || {
      echo 'Docker task changed stack during metrics collection' >&2
      exit 1
    }
    [[ "$swarm_service" == "$stack"'_'* ]] || {
      echo 'Docker task lacks the expected Swarm service identity' >&2
      exit 1
    }
    name="${name#/}"
    service="${swarm_service#"$stack"_}"
    running=0
    [[ "$state" == running ]] && running=1
    cpu=0 mem_use=0 mem_limit=0 mem_pct=0 net_rx=0 net_tx=0 block_read=0 block_write=0
    if ((running)); then
      # Docker may report a 12- or 64-character ID; both must match this task.
      line="$(awk -F'|' -v id="$id" '$1 == id || index(id,$1) == 1 || index($1,id) == 1 {print; exit}' "$stats_tmp")"
      [[ -n "$line" ]] || { echo 'Docker stats omitted a running task' >&2; exit 1; }
      IFS='|' read -r cpu mem_usage mem_pct net_io block_io <<< "${line#*|}"
      cpu="${cpu//%/}"
      mem_pct="${mem_pct//%/}"
      mem_use="$(bytes "$(printf '%s' "$mem_usage" | awk -F' / ' '{print $1}')")"
      mem_limit="$(bytes "$(printf '%s' "$mem_usage" | awk -F' / ' '{print $2}')")"
      net_rx="$(bytes "$(printf '%s' "$net_io" | awk -F' / ' '{print $1}')")"
      net_tx="$(bytes "$(printf '%s' "$net_io" | awk -F' / ' '{print $2}')")"
      block_read="$(bytes "$(printf '%s' "$block_io" | awk -F' / ' '{print $1}')")"
      block_write="$(bytes "$(printf '%s' "$block_io" | awk -F' / ' '{print $2}')")"
    fi
    [[ "$size_rw" =~ ^[0-9]+$ ]] || size_rw=0
    [[ "$size_rootfs" =~ ^[0-9]+$ ]] || size_rootfs=0
    labels="stack=\"$(esc "$stack")\",service=\"$(esc "$service")\",container=\"$(esc "$name")\",image=\"$(esc "$image")\",state=\"$(esc "$state")\""
    echo "docker_stack_container_running{$labels} $running"
    echo "docker_stack_container_cpu_percent{$labels} $cpu"
    echo "docker_stack_container_memory_usage_bytes{$labels} $mem_use"
    echo "docker_stack_container_memory_limit_bytes{$labels} $mem_limit"
    echo "docker_stack_container_memory_percent{$labels} $mem_pct"
    echo "docker_stack_container_net_rx_bytes{$labels} $net_rx"
    echo "docker_stack_container_net_tx_bytes{$labels} $net_tx"
    echo "docker_stack_container_block_read_bytes{$labels} $block_read"
    echo "docker_stack_container_block_write_bytes{$labels} $block_write"
    echo "docker_stack_container_size_rw_bytes{$labels} $size_rw"
    echo "docker_stack_container_size_rootfs_bytes{$labels} $size_rootfs"
  done
} > "$tmp"

chmod 0644 "$tmp"
mv -f -- "$tmp" "$out"
