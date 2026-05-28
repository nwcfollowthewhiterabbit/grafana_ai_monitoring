#!/usr/bin/env python3
import argparse
import concurrent.futures
import fcntl
import hashlib
import os
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import yaml


@dataclass(frozen=True)
class Target:
    url: str
    labels: Dict[str, str]
    queue_bucket: int


@dataclass
class ProbeResult:
    success: bool
    status_code: int
    duration: float
    error: str


@dataclass
class TargetState:
    target: Target
    attempts: List[ProbeResult]


def prom_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labelset(labels: Dict[str, str]) -> str:
    return ",".join(f'{key}="{prom_escape(value)}"' for key, value in sorted(labels.items()))


def metric_line(name: str, labels: Dict[str, str], value: object) -> str:
    return f"{name}{{{labelset(labels)}}} {value}"


def load_targets(path: str, queue_buckets: int) -> List[Target]:
    with open(path, "r", encoding="utf-8") as fh:
        catalog = yaml.safe_load(fh) or {}

    targets: List[Target] = []
    for item in catalog.get("http_services", []):
        url = item.get("url")
        if not url:
            continue
        monitoring = item.get("monitoring", True)
        if monitoring is False:
            continue

        labels = {
            "site_company": str(item.get("company", "")),
            "site_alias": str(item.get("alias", "")),
            "stack": str(item.get("stack", "")),
            "service": str(item.get("service", "")),
            "criticality": str(item.get("criticality", "")),
            "site_instance": str(url),
        }
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % queue_buckets
        targets.append(Target(url=url, labels=labels, queue_bucket=bucket))

    return sorted(
        targets,
        key=lambda target: (
            target.queue_bucket,
            target.labels["site_company"],
            target.labels["site_alias"],
            target.labels["criticality"],
            target.labels["stack"],
            target.url,
        ),
    )


def check_url(target: Target, timeout: float, user_agent: str) -> ProbeResult:
    started = time.monotonic()
    request = urllib.request.Request(target.url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 0) or 0)
            response.read(1)
        duration = time.monotonic() - started
        return ProbeResult(
            success=200 <= status_code < 400,
            status_code=status_code,
            duration=duration,
            error="",
        )
    except urllib.error.HTTPError as exc:
        duration = time.monotonic() - started
        return ProbeResult(
            success=200 <= int(exc.code) < 400,
            status_code=int(exc.code),
            duration=duration,
            error=f"http_{exc.code}",
        )
    except urllib.error.URLError as exc:
        duration = time.monotonic() - started
        reason = getattr(exc, "reason", exc)
        return ProbeResult(False, 0, duration, type(reason).__name__)
    except (TimeoutError, socket.timeout):
        duration = time.monotonic() - started
        return ProbeResult(False, 0, duration, "timeout")
    except ssl.SSLError as exc:
        duration = time.monotonic() - started
        return ProbeResult(False, 0, duration, f"tls_{exc.__class__.__name__}")
    except Exception as exc:
        duration = time.monotonic() - started
        return ProbeResult(False, 0, duration, exc.__class__.__name__)


def probe_many(
    targets: Iterable[Target],
    timeout: float,
    max_workers: int,
    user_agent: str,
) -> Dict[str, ProbeResult]:
    target_list = list(targets)
    if not target_list:
        return {}

    results: Dict[str, ProbeResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(check_url, target, timeout, user_agent): target
            for target in target_list
        }
        for future in concurrent.futures.as_completed(future_map):
            target = future_map[future]
            try:
                results[target.url] = future.result()
            except Exception as exc:
                results[target.url] = ProbeResult(False, 0, 0.0, exc.__class__.__name__)
    return results


def write_metrics(
    path: str,
    states: List[TargetState],
    cycle_started: int,
    cycle_finished: int,
    failure_threshold: int,
) -> None:
    lines = [
        "# HELP scheduled_public_site_cycle_last_start_timestamp_seconds Last scheduled public site check cycle start time.",
        "# TYPE scheduled_public_site_cycle_last_start_timestamp_seconds gauge",
        f"scheduled_public_site_cycle_last_start_timestamp_seconds {cycle_started}",
        "# HELP scheduled_public_site_cycle_last_finish_timestamp_seconds Last scheduled public site check cycle finish time.",
        "# TYPE scheduled_public_site_cycle_last_finish_timestamp_seconds gauge",
        f"scheduled_public_site_cycle_last_finish_timestamp_seconds {cycle_finished}",
        "# HELP scheduled_public_site_target_count Number of public site targets in the scheduled checker.",
        "# TYPE scheduled_public_site_target_count gauge",
        f"scheduled_public_site_target_count {len(states)}",
        "# HELP scheduled_public_site_last_probe_success Last attempt result for a public site in the scheduled checker.",
        "# TYPE scheduled_public_site_last_probe_success gauge",
        "# HELP scheduled_public_site_confirmed_down Public site failed enough attempts in one scheduled cycle to notify.",
        "# TYPE scheduled_public_site_confirmed_down gauge",
        "# HELP scheduled_public_site_attempt_failures Failed attempts in the last scheduled cycle.",
        "# TYPE scheduled_public_site_attempt_failures gauge",
        "# HELP scheduled_public_site_attempt_total Total attempts in the last scheduled cycle.",
        "# TYPE scheduled_public_site_attempt_total gauge",
        "# HELP scheduled_public_site_last_duration_seconds Last attempt duration in seconds.",
        "# TYPE scheduled_public_site_last_duration_seconds gauge",
        "# HELP scheduled_public_site_last_status_code Last HTTP status code seen by the scheduled checker.",
        "# TYPE scheduled_public_site_last_status_code gauge",
        "# HELP scheduled_public_site_last_check_timestamp_seconds Last completed check timestamp for the public site.",
        "# TYPE scheduled_public_site_last_check_timestamp_seconds gauge",
        "# HELP scheduled_public_site_queue_bucket Stable queue bucket assigned to the public site.",
        "# TYPE scheduled_public_site_queue_bucket gauge",
        "# HELP scheduled_public_site_last_error Last checker error label for a public site.",
        "# TYPE scheduled_public_site_last_error gauge",
    ]

    for state in states:
        labels = dict(state.target.labels)
        attempts = state.attempts
        last = attempts[-1] if attempts else ProbeResult(False, 0, 0.0, "not_checked")
        failures = sum(1 for attempt in attempts if not attempt.success)
        confirmed_down = 1 if failures >= failure_threshold else 0
        lines.append(metric_line("scheduled_public_site_last_probe_success", labels, 1 if last.success else 0))
        lines.append(metric_line("scheduled_public_site_confirmed_down", labels, confirmed_down))
        lines.append(metric_line("scheduled_public_site_attempt_failures", labels, failures))
        lines.append(metric_line("scheduled_public_site_attempt_total", labels, len(attempts)))
        lines.append(metric_line("scheduled_public_site_last_duration_seconds", labels, f"{last.duration:.6f}"))
        lines.append(metric_line("scheduled_public_site_last_status_code", labels, last.status_code))
        lines.append(metric_line("scheduled_public_site_last_check_timestamp_seconds", labels, cycle_finished))
        lines.append(metric_line("scheduled_public_site_queue_bucket", labels, state.target.queue_bucket))
        error_labels = dict(labels)
        error_labels["error"] = last.error or "none"
        lines.append(metric_line("scheduled_public_site_last_error", error_labels, 1))

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".scheduled-public-sites.", suffix=".prom", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        fh.write("\n")
    os.chmod(tmp_path, 0o644)
    os.replace(tmp_path, path)


def acquire_lock(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock_fh = open(path, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"another scheduled public site check is already running: {path}", file=sys.stderr)
        sys.exit(0)
    return lock_fh


def main() -> int:
    parser = argparse.ArgumentParser(description="Queued scheduled public site checker")
    parser.add_argument("--catalog", default="/root/monitoring/service-catalog.yml")
    parser.add_argument("--output", default="/var/lib/node-exporter-textfile/scheduled-public-sites.prom")
    parser.add_argument("--lock", default="/run/scheduled-public-site-checker/lock")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--queue-buckets", type=int, default=180)
    parser.add_argument("--retry-count", type=int, default=3)
    parser.add_argument("--retry-interval", type=int, default=300)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--user-agent", default="Greenleaf Scheduled Public Site Checker/1.0")
    args = parser.parse_args()

    lock_fh = acquire_lock(args.lock)

    cycle_started = int(time.time())
    targets = load_targets(args.catalog, args.queue_buckets)
    states = {target.url: TargetState(target=target, attempts=[]) for target in targets}

    first_results = probe_many(targets, args.timeout, args.max_workers, args.user_agent)
    for target in targets:
        states[target.url].attempts.append(first_results[target.url])

    retry_targets = [target for target in targets if not states[target.url].attempts[-1].success]
    for retry_index in range(args.retry_count):
        if not retry_targets:
            break
        time.sleep(args.retry_interval)
        retry_results = probe_many(retry_targets, args.timeout, args.max_workers, args.user_agent)
        for target in retry_targets:
            states[target.url].attempts.append(retry_results[target.url])

    cycle_finished = int(time.time())
    write_metrics(
        args.output,
        [states[target.url] for target in targets],
        cycle_started,
        cycle_finished,
        args.failure_threshold,
    )

    confirmed = [
        state.target.url
        for state in states.values()
        if sum(1 for attempt in state.attempts if not attempt.success) >= args.failure_threshold
    ]
    if confirmed:
        print("confirmed down:", ", ".join(confirmed), file=sys.stderr)
    print(f"checked {len(targets)} targets; confirmed_down={len(confirmed)}")
    lock_fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
