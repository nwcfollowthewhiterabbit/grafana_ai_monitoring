#!/usr/bin/env bash
set -euo pipefail
if [ -d /var/lib/node-exporter-textfile ]; then
  OUT_DIR=/var/lib/node-exporter-textfile
else
  OUT_DIR=/var/lib/prometheus/node-exporter
fi
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/docker-stacks.prom"
TMP="${OUT}.tmp"
bytes() {
  local v n u
  v=$(printf '%s' "$1" | xargs)
  [ -n "$v" ] || { echo 0; return; }
  n=$(printf '%s' "$v" | sed -E 's/^([0-9.]+).*/\1/')
  u=$(printf '%s' "$v" | sed -E 's/^[0-9.]+[[:space:]]*//')
  awk -v n="$n" -v u="$u" 'BEGIN {
    m=1
    if (u=="B" || u=="") m=1
    else if (u=="kB" || u=="KB") m=1000
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
  docker ps -a --no-trunc --format '{{.ID}}' | while read -r id; do
    [ -n "$id" ] || continue
    name=$(docker inspect --format '{{.Name}}' "$id" | sed 's#^/##')
    image=$(docker inspect --format '{{.Config.Image}}' "$id")
    state=$(docker inspect --format '{{.State.Status}}' "$id")
    project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$id" 2>/dev/null || true)
    service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$id" 2>/dev/null || true)
    stack=$(docker inspect --format '{{index .Config.Labels "com.docker.stack.namespace"}}' "$id" 2>/dev/null || true)
    swarm_service=$(docker inspect --format '{{index .Config.Labels "com.docker.swarm.service.name"}}' "$id" 2>/dev/null || true)
    if [ -n "$project" ] && [ "$project" != "<no value>" ]; then stack="$project"; fi
    if [ -n "$swarm_service" ] && [ "$swarm_service" != "<no value>" ]; then
      service="$swarm_service"
      if [ -z "$stack" ] || [ "$stack" = "<no value>" ]; then stack="${swarm_service%%_*}"; fi
      service="${swarm_service#${stack}_}"
    fi
    if [ -z "$stack" ] || [ "$stack" = "<no value>" ]; then stack="${name%%_*}"; fi
    if [ -z "$service" ] || [ "$service" = "<no value>" ]; then
      rest="${name#${stack}_}"
      service="${rest%%.*}"
      [ "$service" = "$name" ] && service="$name"
    fi
    running=0; [ "$state" = "running" ] && running=1
    cpu=0; mem_use=0; mem_limit=0; mem_pct=0; net_rx=0; net_tx=0; block_read=0; block_write=0
    if [ "$state" = "running" ]; then
      line=$(docker stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}' "$id" 2>/dev/null || true)
      if [ -n "$line" ]; then
        cpu=$(printf '%s' "$line" | cut -d'|' -f1 | tr -d '%')
        mem_usage=$(printf '%s' "$line" | cut -d'|' -f2)
        mem_pct=$(printf '%s' "$line" | cut -d'|' -f3 | tr -d '%')
        net_io=$(printf '%s' "$line" | cut -d'|' -f4)
        block_io=$(printf '%s' "$line" | cut -d'|' -f5)
        mem_use=$(bytes "$(printf '%s' "$mem_usage" | awk -F' / ' '{print $1}')")
        mem_limit=$(bytes "$(printf '%s' "$mem_usage" | awk -F' / ' '{print $2}')")
        net_rx=$(bytes "$(printf '%s' "$net_io" | awk -F' / ' '{print $1}')")
        net_tx=$(bytes "$(printf '%s' "$net_io" | awk -F' / ' '{print $2}')")
        block_read=$(bytes "$(printf '%s' "$block_io" | awk -F' / ' '{print $1}')")
        block_write=$(bytes "$(printf '%s' "$block_io" | awk -F' / ' '{print $2}')")
      fi
    fi
    sizes=$(docker inspect --size --format '{{.SizeRw}}|{{.SizeRootFs}}' "$id" 2>/dev/null || echo '0|0')
    size_rw=$(printf '%s' "$sizes" | cut -d'|' -f1); [ "$size_rw" = "<no value>" ] && size_rw=0
    size_rootfs=$(printf '%s' "$sizes" | cut -d'|' -f2); [ "$size_rootfs" = "<no value>" ] && size_rootfs=0
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
} > "$TMP"
mv "$TMP" "$OUT"
