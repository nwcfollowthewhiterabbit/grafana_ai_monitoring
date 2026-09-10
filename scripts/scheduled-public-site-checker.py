#!/usr/bin/env python3
"""Bounded, stateful availability checks for public sites in the service catalog."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from monitoring_catalog import CatalogValidationError, iter_http_services, load_catalog


CHECKER_VERSION = 2
MAX_WORKERS = 64
MAX_QUEUE_BUCKETS = 4096
MAX_TIMEOUT_SECONDS = 120.0
MAX_RETRY_COUNT = 10
MAX_RETRY_INTERVAL_SECONDS = 3600.0
MAX_BUCKET_PAUSE_SECONDS = 60.0


@dataclass(frozen=True)
class Target:
	url: str
	labels: dict[str, str]
	queue_bucket: int


@dataclass(frozen=True)
class ProbeResult:
	success: bool
	status_code: int
	duration: float
	error: str
	checked_at: int


@dataclass
class TargetState:
	target: Target
	attempts: list[ProbeResult]


class LockBusyError(RuntimeError):
	pass


def prom_escape(value: object) -> str:
	return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labelset(labels: Mapping[str, object]) -> str:
	return ",".join(f'{key}="{prom_escape(value)}"' for key, value in sorted(labels.items()))


def metric_line(name: str, labels: Mapping[str, object], value: object) -> str:
	return f"{name}{{{labelset(labels)}}} {value}"


def _bounded_int(name: str, minimum: int, maximum: int) -> Callable[[str], int]:
	def parse(value: str) -> int:
		try:
			parsed = int(value)
		except ValueError as exc:
			raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
		if not minimum <= parsed <= maximum:
			raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
		return parsed

	return parse


def _bounded_float(name: str, minimum: float, maximum: float) -> Callable[[str], float]:
	def parse(value: str) -> float:
		try:
			parsed = float(value)
		except ValueError as exc:
			raise argparse.ArgumentTypeError(f"{name} must be a number") from exc
		if not minimum <= parsed <= maximum:
			raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
		return parsed

	return parse


def validate_user_agent(value: str) -> str:
	if not value or len(value) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in value):
		raise argparse.ArgumentTypeError("user-agent must be 1..200 visible characters")
	return value


def load_targets(path: str | Path, queue_buckets: int) -> tuple[dict, list[Target]]:
	catalog = load_catalog(path)
	targets: list[Target] = []
	for item in iter_http_services(catalog, "availability"):
		url = str(item["url"])
		labels = {
			"site_company": str(item["company"]),
			"site_alias": str(item["alias"]),
			"stack": str(item["stack"]),
			"service": str(item["service"]),
			"criticality": str(item["criticality"]),
			"site_instance": url,
		}
		digest = hashlib.sha256(url.encode("utf-8")).digest()
		bucket = int.from_bytes(digest[:4], "big") % queue_buckets
		targets.append(Target(url=url, labels=labels, queue_bucket=bucket))
	return catalog, sorted(
		targets,
		key=lambda target: (
			target.queue_bucket,
			target.labels["site_company"],
			target.labels["site_alias"],
			target.labels["stack"],
			target.labels["service"],
			target.url,
		),
	)


def check_url(target: Target, timeout: float, user_agent: str) -> ProbeResult:
	started = time.monotonic()
	request = urllib.request.Request(
		target.url,
		headers={"User-Agent": user_agent, "Accept": "*/*"},
		method="GET",
	)
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:
			status_code = int(getattr(response, "status", 0) or 0)
			response.read(1)
		return ProbeResult(
			success=200 <= status_code < 400,
			status_code=status_code,
			duration=time.monotonic() - started,
			error="",
			checked_at=int(time.time()),
		)
	except urllib.error.HTTPError as exc:
		status_code = int(exc.code)
		return ProbeResult(
			200 <= status_code < 400,
			status_code,
			time.monotonic() - started,
			f"http_{status_code}",
			int(time.time()),
		)
	except urllib.error.URLError as exc:
		reason = getattr(exc, "reason", exc)
		error = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else type(reason).__name__
		return ProbeResult(False, 0, time.monotonic() - started, error, int(time.time()))
	except (TimeoutError, socket.timeout):
		return ProbeResult(False, 0, time.monotonic() - started, "timeout", int(time.time()))
	except ssl.SSLError:
		return ProbeResult(False, 0, time.monotonic() - started, "tls_error", int(time.time()))
	except Exception as exc:  # Defensive: one target must not abort a cycle.
		return ProbeResult(False, 0, time.monotonic() - started, type(exc).__name__, int(time.time()))


def probe_many(
	targets: Iterable[Target], timeout: float, max_workers: int, user_agent: str
) -> dict[str, ProbeResult]:
	target_list = list(targets)
	if not target_list:
		return {}
	results: dict[str, ProbeResult] = {}
	with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(target_list))) as pool:
		future_map = {
			pool.submit(check_url, target, timeout, user_agent): target for target in target_list
		}
		for future in concurrent.futures.as_completed(future_map):
			target = future_map[future]
			try:
				results[target.url] = future.result()
			except Exception as exc:  # Defensive around executor failures.
				results[target.url] = ProbeResult(False, 0, 0.0, type(exc).__name__, int(time.time()))
	return results


def probe_bucket_batches(
	targets: Iterable[Target],
	timeout: float,
	max_workers: int,
	user_agent: str,
	bucket_pause: float,
	*,
	probe: Callable[[Iterable[Target], float, int, str], dict[str, ProbeResult]] = probe_many,
	sleep: Callable[[float], None] = time.sleep,
) -> dict[str, ProbeResult]:
	"""Probe one stable hash bucket at a time instead of merely sorting by bucket."""

	buckets: dict[int, list[Target]] = {}
	for target in targets:
		buckets.setdefault(target.queue_bucket, []).append(target)
	results: dict[str, ProbeResult] = {}
	for index, bucket in enumerate(sorted(buckets)):
		if index and bucket_pause:
			sleep(bucket_pause)
		results.update(probe(buckets[bucket], timeout, max_workers, user_agent))
	return results


def is_confirmed_down(state: TargetState, failure_threshold: int) -> bool:
	return bool(
		state.attempts
		and not state.attempts[-1].success
		and sum(not attempt.success for attempt in state.attempts) >= failure_threshold
	)


def _atomic_write(path: str | Path, content: str, mode: int = 0o644) -> None:
	destination = Path(path)
	destination.parent.mkdir(parents=True, exist_ok=True)
	fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			handle.write(content)
			handle.flush()
			os.fsync(handle.fileno())
		os.chmod(temporary, mode)
		os.replace(temporary, destination)
	except BaseException:
		try:
			os.unlink(temporary)
		except FileNotFoundError:
			pass
		raise


def atomic_write_json(path: str | Path, value: object) -> None:
	_atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_previous_success(path: str | Path) -> int:
	state_path = Path(path)
	if not state_path.exists():
		return 0
	with state_path.open("r", encoding="utf-8") as handle:
		state = json.load(handle)
	value = state.get("last_success_timestamp", 0)
	if isinstance(value, bool) or not isinstance(value, int) or value < 0:
		raise ValueError("invalid last_success_timestamp in state")
	return value


def render_target_metrics(
	states: Sequence[TargetState], cycle_started: int, cycle_finished: int, failure_threshold: int
) -> str:
	lines = [
		"# HELP scheduled_public_site_cycle_last_start_timestamp_seconds Last availability cycle start time.",
		"# TYPE scheduled_public_site_cycle_last_start_timestamp_seconds gauge",
		f"scheduled_public_site_cycle_last_start_timestamp_seconds {cycle_started}",
		"# HELP scheduled_public_site_cycle_last_finish_timestamp_seconds Last successful availability cycle finish time.",
		"# TYPE scheduled_public_site_cycle_last_finish_timestamp_seconds gauge",
		f"scheduled_public_site_cycle_last_finish_timestamp_seconds {cycle_finished}",
		"# HELP scheduled_public_site_target_count Number of enabled availability targets.",
		"# TYPE scheduled_public_site_target_count gauge",
		f"scheduled_public_site_target_count {len(states)}",
		"# HELP scheduled_public_site_last_probe_success Last attempt result for a public site.",
		"# TYPE scheduled_public_site_last_probe_success gauge",
		"# HELP scheduled_public_site_confirmed_down Final attempt failed and failure threshold was reached.",
		"# TYPE scheduled_public_site_confirmed_down gauge",
		"# HELP scheduled_public_site_attempt_failures Failed attempts in the latest cycle.",
		"# TYPE scheduled_public_site_attempt_failures gauge",
		"# HELP scheduled_public_site_attempt_total Attempts in the latest cycle.",
		"# TYPE scheduled_public_site_attempt_total gauge",
		"# HELP scheduled_public_site_last_duration_seconds Last attempt duration.",
		"# TYPE scheduled_public_site_last_duration_seconds gauge",
		"# HELP scheduled_public_site_last_status_code Last HTTP status code.",
		"# TYPE scheduled_public_site_last_status_code gauge",
		"# HELP scheduled_public_site_last_check_timestamp_seconds Last completed target attempt time.",
		"# TYPE scheduled_public_site_last_check_timestamp_seconds gauge",
		"# HELP scheduled_public_site_queue_bucket Stable queue bucket assigned to the site.",
		"# TYPE scheduled_public_site_queue_bucket gauge",
		"# HELP scheduled_public_site_last_error Sanitized last checker error category.",
		"# TYPE scheduled_public_site_last_error gauge",
	]
	for state in states:
		labels = state.target.labels
		last = state.attempts[-1]
		failures = sum(not attempt.success for attempt in state.attempts)
		lines.extend(
			(
				metric_line("scheduled_public_site_last_probe_success", labels, int(last.success)),
				metric_line("scheduled_public_site_confirmed_down", labels, int(is_confirmed_down(state, failure_threshold))),
				metric_line("scheduled_public_site_attempt_failures", labels, failures),
				metric_line("scheduled_public_site_attempt_total", labels, len(state.attempts)),
				metric_line("scheduled_public_site_last_duration_seconds", labels, f"{last.duration:.6f}"),
				metric_line("scheduled_public_site_last_status_code", labels, last.status_code),
				metric_line("scheduled_public_site_last_check_timestamp_seconds", labels, last.checked_at),
				metric_line("scheduled_public_site_queue_bucket", labels, state.target.queue_bucket),
			)
		)
		error_labels = dict(labels)
		error_labels["error"] = last.error or "none"
		lines.append(metric_line("scheduled_public_site_last_error", error_labels, 1))
	return "\n".join(lines) + "\n"


def render_self_metrics(
	*, up: bool, catalog_valid: bool, attempt_timestamp: int, last_success_timestamp: int,
	duration: float, target_count: int, error: str,
) -> str:
	return "\n".join(
		(
			"# HELP scheduled_public_site_checker_up Whether the latest checker cycle completed successfully.",
			"# TYPE scheduled_public_site_checker_up gauge",
			f"scheduled_public_site_checker_up {int(up)}",
			"# HELP scheduled_public_site_catalog_valid Whether strict catalog validation succeeded.",
			"# TYPE scheduled_public_site_catalog_valid gauge",
			f"scheduled_public_site_catalog_valid {int(catalog_valid)}",
			"# HELP scheduled_public_site_cycle_last_attempt_timestamp_seconds Latest checker invocation time.",
			"# TYPE scheduled_public_site_cycle_last_attempt_timestamp_seconds gauge",
			f"scheduled_public_site_cycle_last_attempt_timestamp_seconds {attempt_timestamp}",
			"# HELP scheduled_public_site_cycle_last_success_timestamp_seconds Latest completed cycle; use time() minus this gauge for staleness.",
			"# TYPE scheduled_public_site_cycle_last_success_timestamp_seconds gauge",
			f"scheduled_public_site_cycle_last_success_timestamp_seconds {last_success_timestamp}",
			"# HELP scheduled_public_site_cycle_duration_seconds Latest checker invocation duration.",
			"# TYPE scheduled_public_site_cycle_duration_seconds gauge",
			f"scheduled_public_site_cycle_duration_seconds {duration:.6f}",
			"# HELP scheduled_public_site_checker_target_count Targets loaded by checker.",
			"# TYPE scheduled_public_site_checker_target_count gauge",
			f"scheduled_public_site_checker_target_count {target_count}",
			"# HELP scheduled_public_site_checker_error Latest bounded checker error category.",
			"# TYPE scheduled_public_site_checker_error gauge",
			metric_line("scheduled_public_site_checker_error", {"error": error}, 1),
		)
	) + "\n"


def state_document(
	states: Sequence[TargetState], cycle_finished: int, failure_threshold: int
) -> dict:
	return {
		"version": CHECKER_VERSION,
		"last_success_timestamp": cycle_finished,
		"targets": [
			{
				"url": state.target.url,
				"labels": state.target.labels,
				"queue_bucket": state.target.queue_bucket,
				"confirmed_down": is_confirmed_down(state, failure_threshold),
				"attempts": [asdict(attempt) for attempt in state.attempts],
			}
			for state in states
		],
	}


def acquire_lock(path: str | Path):
	lock_path = Path(path)
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	lock_handle = lock_path.open("w", encoding="utf-8")
	try:
		fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
	except BlockingIOError as exc:
		lock_handle.close()
		raise LockBusyError(f"another checker cycle holds {lock_path}") from exc
	return lock_handle


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Queued scheduled public site availability checker")
	parser.add_argument("--catalog", default="/root/monitoring/service-catalog.yml")
	parser.add_argument("--output", default="/var/lib/node-exporter-textfile/scheduled-public-sites.prom")
	parser.add_argument("--self-output")
	parser.add_argument("--state")
	parser.add_argument("--lock", default="/run/scheduled-public-site-checker/lock")
	parser.add_argument("--timeout", type=_bounded_float("timeout", 0.1, MAX_TIMEOUT_SECONDS), default=12.0)
	parser.add_argument("--max-workers", type=_bounded_int("max-workers", 1, MAX_WORKERS), default=16)
	parser.add_argument("--queue-buckets", type=_bounded_int("queue-buckets", 1, MAX_QUEUE_BUCKETS), default=180)
	parser.add_argument("--bucket-pause", type=_bounded_float("bucket-pause", 0, MAX_BUCKET_PAUSE_SECONDS), default=0.0)
	parser.add_argument("--retry-count", type=_bounded_int("retry-count", 0, MAX_RETRY_COUNT), default=3)
	parser.add_argument("--retry-interval", type=_bounded_float("retry-interval", 0, MAX_RETRY_INTERVAL_SECONDS), default=300.0)
	parser.add_argument("--failure-threshold", type=_bounded_int("failure-threshold", 1, MAX_RETRY_COUNT + 1), default=3)
	parser.add_argument("--user-agent", type=validate_user_agent, default="Rabbit Systems Availability Checker/2.0")
	args = parser.parse_args(argv)
	if args.failure_threshold > args.retry_count + 1:
		parser.error("failure-threshold cannot exceed retry-count + 1")
	output = Path(args.output)
	args.self_output = args.self_output or str(output.with_name("scheduled-public-site-checker-self.prom"))
	args.state = args.state or str(output.with_name("scheduled-public-sites-state.json"))
	return args


def run(args: argparse.Namespace) -> tuple[list[TargetState], int, int]:
	cycle_started = int(time.time())
	_catalog, targets = load_targets(args.catalog, args.queue_buckets)
	states = {target.url: TargetState(target, []) for target in targets}
	retry_targets = list(targets)
	for attempt_index in range(args.retry_count + 1):
		if not retry_targets:
			break
		if attempt_index:
			time.sleep(args.retry_interval)
		results = probe_bucket_batches(
			retry_targets, args.timeout, args.max_workers, args.user_agent, args.bucket_pause
		)
		next_retry_targets: list[Target] = []
		for target in retry_targets:
			result = results[target.url]
			states[target.url].attempts.append(result)
			if not result.success:
				next_retry_targets.append(target)
		retry_targets = next_retry_targets
	cycle_finished = int(time.time())
	ordered_states = [states[target.url] for target in targets]
	_atomic_write(args.output, render_target_metrics(ordered_states, cycle_started, cycle_finished, args.failure_threshold))
	atomic_write_json(args.state, state_document(ordered_states, cycle_finished, args.failure_threshold))
	return ordered_states, cycle_started, cycle_finished


def main(argv: Sequence[str] | None = None) -> int:
	args = parse_args(argv)
	attempt_timestamp = int(time.time())
	monotonic_started = time.monotonic()
	last_success = 0
	try:
		last_success = load_previous_success(args.state)
	except (OSError, ValueError, json.JSONDecodeError):
		pass
	try:
		with acquire_lock(args.lock):
			states, _cycle_started, cycle_finished = run(args)
			last_success = cycle_finished
			_atomic_write(
				args.self_output,
				render_self_metrics(
					up=True, catalog_valid=True, attempt_timestamp=attempt_timestamp,
					last_success_timestamp=last_success, duration=time.monotonic() - monotonic_started,
					target_count=len(states), error="none",
				),
			)
	except (CatalogValidationError, LockBusyError, OSError, ValueError, KeyError) as exc:
		catalog_valid = not isinstance(exc, CatalogValidationError)
		error = "catalog_invalid" if isinstance(exc, CatalogValidationError) else "lock_busy" if isinstance(exc, LockBusyError) else "runtime_error"
		try:
			_atomic_write(
				args.self_output,
				render_self_metrics(
					up=False, catalog_valid=catalog_valid, attempt_timestamp=attempt_timestamp,
					last_success_timestamp=last_success, duration=time.monotonic() - monotonic_started,
					target_count=0, error=error,
				),
			)
		except OSError:
			pass
		print(f"scheduled public site checker failed ({error}): {exc}", file=sys.stderr)
		return 1
	confirmed = [state.target.url for state in states if is_confirmed_down(state, args.failure_threshold)]
	if confirmed:
		print("confirmed down: " + ", ".join(confirmed), file=sys.stderr)
	print(f"checked {len(states)} targets; confirmed_down={len(confirmed)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
