#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

python_bin="${PYTHON_BIN:-python3}"
cache_root="$(mktemp -d "${TMPDIR:-/tmp}/rabbit-monitoring-ci.XXXXXX")"
trap 'rm -rf -- "$cache_root"' EXIT
export PYTHONPYCACHEPREFIX="$cache_root/pycache"

echo "Checking Python sources without writing repository bytecode"
"$python_bin" - <<'PY'
from pathlib import Path

ignored = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "venv"}
paths = sorted(
    path
    for path in Path(".").rglob("*.py")
    if not any(part in ignored for part in path.parts)
)
for path in paths:
    compile(path.read_bytes(), str(path), "exec")
print(f"compiled {len(paths)} Python source files")
PY

test_directories="$cache_root/test-directories"
find . -type f -name 'test_*.py' -not -path './.git/*' -print \
  | sed 's#/[^/]*$##' \
  | sort -u >"$test_directories"
if [[ ! -s "$test_directories" ]]; then
  echo "No Python unit tests found" >&2
  exit 1
fi
while IFS= read -r test_directory; do
  echo "Running unit tests in $test_directory"
  "$python_bin" -m unittest discover -s "$test_directory" -p 'test_*.py' -v
done <"$test_directories"

if [[ -f scripts/validate-service-catalog.py && -f monitoring/service-catalog.yml ]]; then
  "$python_bin" scripts/validate-service-catalog.py monitoring/service-catalog.yml
fi

if [[ -f scripts/render-monitoring-config.py && -f monitoring/service-catalog.yml ]]; then
  "$python_bin" scripts/render-monitoring-config.py \
    --catalog monitoring/service-catalog.yml \
    --output monitoring/prometheus/file_sd/http_targets.yml \
    --check
fi

if [[ -f scripts/generate-managed-monitoring-dashboards.py ]]; then
  "$python_bin" scripts/generate-managed-monitoring-dashboards.py --check
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to validate Grafana dashboards" >&2
  exit 1
fi
dashboard_count=0
while IFS= read -r -d '' dashboard; do
  jq empty "$dashboard"
  dashboard_count=$((dashboard_count + 1))
done < <(find monitoring/grafana -type f -name '*.json' -print0)
if [[ "$dashboard_count" -eq 0 ]]; then
  echo "No Grafana dashboard JSON files found" >&2
  exit 1
fi
echo "validated $dashboard_count Grafana dashboard JSON files"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker with Compose is required for configuration validation" >&2
  exit 1
fi
docker compose --env-file monitoring/.env.example \
  -f monitoring/docker-compose.yml config --quiet
docker compose --env-file monitoring/.env.example \
  -f deploy/con-shadow-compose.yml config --quiet

if [[ "${SKIP_CONTAINER_VALIDATION:-0}" == "1" ]]; then
  echo "Skipping containerized promtool/amtool checks by explicit request"
  exit 0
fi

prometheus_image="prom/prometheus:v3.4.0"
alertmanager_image="quay.io/prometheus/alertmanager:v0.33.1"

docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --entrypoint /bin/promtool \
  -v "$repository_root/monitoring/prometheus:/etc/prometheus:ro" \
  "$prometheus_image" check config /etc/prometheus/prometheus.yml

while IFS= read -r -d '' rule_file; do
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --entrypoint /bin/promtool \
    -v "$rule_file:/work/rules.yml:ro" \
    "$prometheus_image" check rules /work/rules.yml
done < <(find "$repository_root/monitoring/prometheus/rules" -type f -name '*.yml' -print0)

docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --entrypoint /bin/amtool \
  -v "$repository_root/monitoring/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
  "$alertmanager_image" check-config /etc/alertmanager/alertmanager.yml
