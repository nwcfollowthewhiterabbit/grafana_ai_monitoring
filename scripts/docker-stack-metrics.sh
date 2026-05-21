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
  local v="$1" n u
  n="${v%[KMGTP]iB}"
  u="${v##$n}"
  awk -v n="$n" -v u="$u" 'BEGIN {m=1; if(u=="KiB")m=1024; else if(u=="MiB")m=1024^2; else if(u=="GiB")m=1024^3; else if(u=="TiB")m=1024^4; else if(u=="PiB")m=1024^5; printf "%.0f", n*m}'
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
    cpu=0; mem_use=0; mem_limit=0; mem_pct=0
    if [ "$state" = "running" ]; then
      line=$(docker stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}' "$id" 2>/dev/null || true)
      if [ -n "$line" ]; then
        cpu=$(printf '%s' "$line" | cut -d'|' -f1 | tr -d '%')
        mem_usage=$(printf '%s' "$line" | cut -d'|' -f2)
        mem_pct=$(printf '%s' "$line" | cut -d'|' -f3 | tr -d '%')
        mem_use=$(bytes "$(printf '%s' "$mem_usage" | awk -F' / ' '{print $1}')")
        mem_limit=$(bytes "$(printf '%s' "$mem_usage" | awk -F' / ' '{print $2}')")
      fi
    fi
    labels="stack=\"$(esc "$stack")\",service=\"$(esc "$service")\",container=\"$(esc "$name")\",image=\"$(esc "$image")\",state=\"$(esc "$state")\""
    echo "docker_stack_container_running{$labels} $running"
    echo "docker_stack_container_cpu_percent{$labels} $cpu"
    echo "docker_stack_container_memory_usage_bytes{$labels} $mem_use"
    echo "docker_stack_container_memory_limit_bytes{$labels} $mem_limit"
    echo "docker_stack_container_memory_percent{$labels} $mem_pct"
  done
} > "$TMP"
mv "$TMP" "$OUT"
