#!/usr/bin/env python3
"""Heuristic public-site integrity checks without content baselines or external APIs."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import ipaddress
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import urldefrag, urljoin, urlsplit

from monitoring_catalog import CatalogValidationError, iter_http_services, load_catalog


STATE_VERSION = 1
DEFAULT_INTERVAL_SECONDS = 43_200
ERROR_MARKERS = (
	"404 not found",
	"500 internal server error",
	"502 bad gateway",
	"503 service unavailable",
	"application error",
	"database connection error",
	"internal server error",
	"site not found",
	"temporarily unavailable",
	"there has been a critical error",
)


@dataclass(frozen=True)
class IntegrityTarget:
	url: str
	labels: dict[str, str]


@dataclass(frozen=True)
class FetchResult:
	success: bool
	status_code: int
	content: bytes
	content_type: str
	truncated: bool
	error: str


@dataclass(frozen=True)
class IntegrityResult:
	target: IntegrityTarget
	bad: bool
	reasons: tuple[str, ...]
	status_code: int
	page_bytes: int
	page_truncated: bool
	resources_discovered: int
	resources_checked: int
	resource_failures: int
	resource_failure_ratio: float
	checked_at: int


class ResourceParser(HTMLParser):
	def __init__(self, base_url: str, extraction_cap: int):
		super().__init__(convert_charrefs=True)
		self.base_url = base_url
		self.extraction_cap = extraction_cap
		self.resources: dict[str, str] = {}
		self.visible: list[str] = []
		self.headline: list[str] = []
		self._hidden_depth = 0
		self._headline_depth = 0

	def _add(self, raw_url: str | None, kind: str) -> None:
		if not raw_url or len(self.resources) >= self.extraction_cap:
			return
		absolute, _fragment = urldefrag(urljoin(self.base_url, raw_url.strip()))
		parsed = urlsplit(absolute)
		if parsed.scheme in {"http", "https"} and parsed.hostname:
			self.resources.setdefault(absolute, kind)

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		attributes = dict(attrs)
		lower_tag = tag.lower()
		if lower_tag == "img":
			self._add(attributes.get("src"), "image")
			for candidate in (attributes.get("srcset") or "").split(","):
				self._add(candidate.strip().split(" ", 1)[0], "image")
		elif lower_tag == "source":
			self._add(attributes.get("src"), "image")
		elif lower_tag == "script":
			self._add(attributes.get("src"), "javascript")
		elif lower_tag == "link" and "stylesheet" in (attributes.get("rel") or "").lower().split():
			self._add(attributes.get("href"), "css")
		if lower_tag in {"script", "style", "noscript", "template"}:
			self._hidden_depth += 1
		if lower_tag in {"title", "h1"}:
			self._headline_depth += 1

	def handle_endtag(self, tag: str) -> None:
		lower_tag = tag.lower()
		if lower_tag in {"script", "style", "noscript", "template"} and self._hidden_depth:
			self._hidden_depth -= 1
		if lower_tag in {"title", "h1"} and self._headline_depth:
			self._headline_depth -= 1

	def handle_data(self, data: str) -> None:
		text = " ".join(data.split())
		if not text or self._hidden_depth:
			return
		if sum(map(len, self.visible)) < 200_000:
			self.visible.append(text)
		if self._headline_depth and sum(map(len, self.headline)) < 4_000:
			self.headline.append(text)


def prom_escape(value: object) -> str:
	return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric_line(name: str, labels: Mapping[str, object], value: object) -> str:
	label_text = ",".join(f'{key}="{prom_escape(value)}"' for key, value in sorted(labels.items()))
	return f"{name}{{{label_text}}} {value}"


def atomic_write(path: str | Path, content: str) -> None:
	destination = Path(path)
	destination.parent.mkdir(parents=True, exist_ok=True)
	fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			handle.write(content)
			handle.flush()
			os.fsync(handle.fileno())
		os.chmod(temporary, 0o644)
		os.replace(temporary, destination)
	except BaseException:
		try:
			os.unlink(temporary)
		except FileNotFoundError:
			pass
		raise


def is_public_http_url(url: str, *, resolve: bool = True) -> bool:
	parsed = urlsplit(url)
	if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
		return False
	hostname = parsed.hostname.rstrip(".").lower()
	if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
		return False
	try:
		literal = ipaddress.ip_address(hostname)
	except ValueError:
		literal = None
	if literal is not None and not literal.is_global:
		return False
	if not resolve:
		return True
	try:
		addresses = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
	except socket.gaierror:
		return True  # The fetch reports the DNS failure with a stable error category.
	return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
	def redirect_request(self, request, fp, code, message, headers, new_url):
		if not is_public_http_url(new_url):
			raise urllib.error.HTTPError(new_url, code, "unsafe redirect target", headers, fp)
		return super().redirect_request(request, fp, code, message, headers, new_url)


def fetch_url(url: str, timeout: float, size_cap: int, user_agent: str) -> FetchResult:
	if not is_public_http_url(url):
		return FetchResult(False, 0, b"", "", False, "unsafe_address")
	request = urllib.request.Request(
		url,
		headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.8"},
		method="GET",
	)
	try:
		with urllib.request.build_opener(SafeRedirectHandler()).open(request, timeout=timeout) as response:
			status = int(getattr(response, "status", 0) or 0)
			content = response.read(size_cap + 1)
			content_type = response.headers.get_content_type() if response.headers else ""
		return FetchResult(
			200 <= status < 400,
			status,
			content[:size_cap],
			content_type,
			len(content) > size_cap,
			"" if 200 <= status < 400 else f"http_{status}",
		)
	except urllib.error.HTTPError as exc:
		return FetchResult(False, int(exc.code), b"", "", False, f"http_{exc.code}")
	except urllib.error.URLError as exc:
		reason = getattr(exc, "reason", exc)
		return FetchResult(False, 0, b"", "", False, "timeout" if isinstance(reason, TimeoutError) else type(reason).__name__)
	except (TimeoutError, socket.timeout):
		return FetchResult(False, 0, b"", "", False, "timeout")
	except Exception as exc:
		return FetchResult(False, 0, b"", "", False, type(exc).__name__)


def decode_html(content: bytes) -> str:
	return content.decode("utf-8", errors="replace")


def inspect_html(base_url: str, content: bytes, extraction_cap: int, min_visible_chars: int) -> tuple[list[str], dict[str, str]]:
	parser = ResourceParser(base_url, extraction_cap)
	reasons: list[str] = []
	try:
		parser.feed(decode_html(content))
		parser.close()
	except Exception:
		reasons.append("html_parse_error")
	visible = " ".join(parser.visible).strip()
	headline = " ".join(parser.headline).lower()
	if len(visible) < min_visible_chars and not parser.resources:
		reasons.append("empty_page")
	if any(marker in headline for marker in ERROR_MARKERS):
		reasons.append("error_page")
	return reasons, parser.resources


def select_resources(resources: Mapping[str, str], maximum: int) -> list[str]:
	return sorted(resources, key=lambda url: (hashlib.sha256(url.encode()).hexdigest(), url))[:maximum]


def check_resource(url: str, timeout: float, size_cap: int, user_agent: str) -> bool:
	return fetch_url(url, timeout, size_cap, user_agent).success


def check_resources(urls: Iterable[str], timeout: float, size_cap: int, user_agent: str, workers: int) -> tuple[int, int]:
	url_list = list(urls)
	if not url_list:
		return 0, 0
	failures = 0
	with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(url_list))) as pool:
		futures = [pool.submit(check_resource, url, timeout, size_cap, user_agent) for url in url_list]
		for future in concurrent.futures.as_completed(futures):
			try:
				if not future.result():
					failures += 1
			except Exception:
				failures += 1
	return len(url_list), failures


def check_target(
	target: IntegrityTarget,
	*,
	timeout: float,
	page_size_cap: int,
	resource_size_cap: int,
	max_resources: int,
	resource_workers: int,
	resource_failure_threshold: float,
	min_visible_chars: int,
	user_agent: str,
) -> IntegrityResult:
	page = fetch_url(target.url, timeout, page_size_cap, user_agent)
	reasons: list[str] = []
	resources: dict[str, str] = {}
	if not page.success:
		reasons.append("page_unavailable")
	elif page.content_type and page.content_type not in {"text/html", "application/xhtml+xml"}:
		reasons.append("unexpected_content_type")
	else:
		html_reasons, resources = inspect_html(
			target.url, page.content, max(max_resources * 10, max_resources), min_visible_chars
		)
		reasons.extend(html_reasons)
	selected = select_resources(resources, max_resources)
	checked, failures = check_resources(selected, timeout, resource_size_cap, user_agent, resource_workers)
	ratio = failures / checked if checked else 0.0
	if checked and ratio >= resource_failure_threshold:
		reasons.append("resource_failures")
	return IntegrityResult(
		target=target,
		bad=bool(reasons),
		reasons=tuple(sorted(set(reasons))),
		status_code=page.status_code,
		page_bytes=len(page.content),
		page_truncated=page.truncated,
		resources_discovered=len(resources),
		resources_checked=checked,
		resource_failures=failures,
		resource_failure_ratio=ratio,
		checked_at=int(time.time()),
	)


def load_targets(path: str | Path) -> list[IntegrityTarget]:
	catalog = load_catalog(path)
	return [
		IntegrityTarget(
			url=str(item["url"]),
			labels={
				"site_company": str(item["company"]),
				"site_alias": str(item["alias"]),
				"stack": str(item["stack"]),
				"service": str(item["service"]),
				"criticality": str(item["criticality"]),
				"site_instance": str(item["url"]),
			},
		)
		for item in iter_http_services(catalog, "integrity")
	]


def load_state(path: str | Path) -> dict:
	state_path = Path(path)
	if not state_path.exists():
		return {"version": STATE_VERSION, "last_success_timestamp": 0, "targets": {}}
	with state_path.open("r", encoding="utf-8") as handle:
		state = json.load(handle)
	if state.get("version") != STATE_VERSION or not isinstance(state.get("targets"), dict):
		raise ValueError("unsupported or invalid integrity state")
	return state


def update_state(previous: Mapping, results: Sequence[IntegrityResult], confirmation_cycles: int, now: int) -> tuple[dict, dict[str, int]]:
	previous_targets = previous.get("targets", {})
	counts: dict[str, int] = {}
	targets = {}
	for result in results:
		old = previous_targets.get(result.target.url, {})
		old_count = old.get("consecutive_bad_cycles", 0)
		if isinstance(old_count, bool) or not isinstance(old_count, int) or old_count < 0:
			old_count = 0
		count = old_count + 1 if result.bad else 0
		counts[result.target.url] = count
		targets[result.target.url] = {
			"consecutive_bad_cycles": count,
			"confirmed_problem": bool(result.bad and count >= confirmation_cycles),
			"last_result": asdict(result)["target"] | {
				"bad": result.bad,
				"reasons": list(result.reasons),
				"checked_at": result.checked_at,
			},
		}
	return {"version": STATE_VERSION, "last_success_timestamp": now, "targets": targets}, counts


def render_metrics(results: Sequence[IntegrityResult], counts: Mapping[str, int], confirmation_cycles: int) -> str:
	lines = [
		"# HELP site_integrity_confirmed_problem Heuristic problem persisted for the configured number of cycles.",
		"# TYPE site_integrity_confirmed_problem gauge",
		"# HELP site_integrity_last_check_timestamp_seconds Latest completed integrity check time.",
		"# TYPE site_integrity_last_check_timestamp_seconds gauge",
		"# HELP site_integrity_check_completed Whether the target check completed.",
		"# TYPE site_integrity_check_completed gauge",
		"# HELP site_integrity_problem_detected Whether the latest cycle found a heuristic problem.",
		"# TYPE site_integrity_problem_detected gauge",
		"# HELP site_integrity_consecutive_bad_cycles Consecutive bad integrity cycles.",
		"# TYPE site_integrity_consecutive_bad_cycles gauge",
		"# HELP site_integrity_resource_failure_ratio Failed checked-resource ratio.",
		"# TYPE site_integrity_resource_failure_ratio gauge",
		"# HELP site_integrity_resources_checked Number of bounded resources checked.",
		"# TYPE site_integrity_resources_checked gauge",
		"# HELP site_integrity_resource_failures Number of checked resources that failed.",
		"# TYPE site_integrity_resource_failures gauge",
		"# HELP site_integrity_page_bytes Bytes read from the page under the configured cap.",
		"# TYPE site_integrity_page_bytes gauge",
		"# HELP site_integrity_page_truncated Whether page input exceeded the configured cap.",
		"# TYPE site_integrity_page_truncated gauge",
		"# HELP site_integrity_last_status_code HTTP status from the page request.",
		"# TYPE site_integrity_last_status_code gauge",
		"# HELP site_integrity_reason Bounded reason found by the latest check.",
		"# TYPE site_integrity_reason gauge",
	]
	for result in results:
		labels = result.target.labels
		count = counts[result.target.url]
		lines.extend(
			(
				metric_line("site_integrity_confirmed_problem", labels, int(result.bad and count >= confirmation_cycles)),
				metric_line("site_integrity_last_check_timestamp_seconds", labels, result.checked_at),
				metric_line("site_integrity_check_completed", labels, 1),
				metric_line("site_integrity_problem_detected", labels, int(result.bad)),
				metric_line("site_integrity_consecutive_bad_cycles", labels, count),
				metric_line("site_integrity_resource_failure_ratio", labels, f"{result.resource_failure_ratio:.6f}"),
				metric_line("site_integrity_resources_checked", labels, result.resources_checked),
				metric_line("site_integrity_resource_failures", labels, result.resource_failures),
				metric_line("site_integrity_page_bytes", labels, result.page_bytes),
				metric_line("site_integrity_page_truncated", labels, int(result.page_truncated)),
				metric_line("site_integrity_last_status_code", labels, result.status_code),
			)
		)
		for reason in result.reasons or ("none",):
			reason_labels = dict(labels)
			reason_labels["reason"] = reason
			lines.append(metric_line("site_integrity_reason", reason_labels, 1))
	return "\n".join(lines) + "\n"


def render_self_metrics(
	up: bool,
	catalog_valid: bool,
	attempt: int,
	last_success: int,
	target_count: int,
	error: str,
	interval_seconds: int,
) -> str:
	return "\n".join(
		(
			"# HELP site_integrity_checker_up Whether the latest checker cycle completed.",
			"# TYPE site_integrity_checker_up gauge",
			f"site_integrity_checker_up {int(up)}",
			"# HELP site_integrity_catalog_valid Whether strict catalog validation succeeded.",
			"# TYPE site_integrity_catalog_valid gauge",
			f"site_integrity_catalog_valid {int(catalog_valid)}",
			"# HELP site_integrity_cycle_last_attempt_timestamp_seconds Latest checker invocation.",
			"# TYPE site_integrity_cycle_last_attempt_timestamp_seconds gauge",
			f"site_integrity_cycle_last_attempt_timestamp_seconds {attempt}",
			"# HELP site_integrity_cycle_last_success_timestamp_seconds Latest successful cycle; use time() minus this for staleness.",
			"# TYPE site_integrity_cycle_last_success_timestamp_seconds gauge",
			f"site_integrity_cycle_last_success_timestamp_seconds {last_success}",
			"# HELP site_integrity_target_count Enabled integrity targets.",
			"# TYPE site_integrity_target_count gauge",
			f"site_integrity_target_count {target_count}",
			"# HELP site_integrity_expected_interval_seconds Configured interval between integrity cycles.",
			"# TYPE site_integrity_expected_interval_seconds gauge",
			f"site_integrity_expected_interval_seconds {interval_seconds}",
			"# HELP site_integrity_checker_error Latest bounded checker error category.",
			"# TYPE site_integrity_checker_error gauge",
			metric_line("site_integrity_checker_error", {"error": error}, 1),
		)
	) + "\n"


def bounded_int(name: str, minimum: int, maximum: int):
	def parse(value: str) -> int:
		try:
			parsed = int(value)
		except ValueError as exc:
			raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc
		if not minimum <= parsed <= maximum:
			raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
		return parsed
	return parse


def bounded_float(name: str, minimum: float, maximum: float):
	def parse(value: str) -> float:
		try:
			parsed = float(value)
		except ValueError as exc:
			raise argparse.ArgumentTypeError(f"{name} must be a number") from exc
		if not minimum <= parsed <= maximum:
			raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
		return parsed
	return parse


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--catalog", default="/root/monitoring/service-catalog.yml")
	parser.add_argument("--output", default="/var/lib/node-exporter-textfile/site-integrity.prom")
	parser.add_argument("--self-output")
	parser.add_argument("--state")
	parser.add_argument("--lock", default="/run/site-integrity-checker/lock")
	parser.add_argument("--timeout", type=bounded_float("timeout", 0.1, 120), default=15.0)
	parser.add_argument("--page-size-cap", type=bounded_int("page-size-cap", 1_024, 5_242_880), default=2_097_152)
	parser.add_argument("--resource-size-cap", type=bounded_int("resource-size-cap", 1, 65_536), default=1)
	parser.add_argument("--max-resources", type=bounded_int("max-resources", 1, 200), default=40)
	parser.add_argument("--site-workers", type=bounded_int("site-workers", 1, 8), default=4)
	parser.add_argument("--resource-workers", type=bounded_int("resource-workers", 1, 8), default=4)
	parser.add_argument("--resource-failure-ratio", type=bounded_float("resource-failure-ratio", 0.01, 1), default=0.25)
	parser.add_argument("--min-visible-chars", type=bounded_int("min-visible-chars", 1, 10_000), default=40)
	parser.add_argument("--confirmation-cycles", type=bounded_int("confirmation-cycles", 2, 10), default=2)
	parser.add_argument("--interval-seconds", type=bounded_int("interval-seconds", 3_600, 604_800), default=DEFAULT_INTERVAL_SECONDS)
	parser.add_argument("--user-agent", default="Rabbit Systems Site Integrity Checker/1.0")
	args = parser.parse_args(argv)
	if not args.user_agent or len(args.user_agent) > 200 or any(ord(char) < 32 for char in args.user_agent):
		parser.error("user-agent must be 1..200 visible characters")
	output = Path(args.output)
	args.self_output = args.self_output or str(output.with_name("site-integrity-checker-self.prom"))
	args.state = args.state or str(output.with_name("site-integrity-state.json"))
	return args


def acquire_lock(path: str | Path):
	lock_path = Path(path)
	lock_path.parent.mkdir(parents=True, exist_ok=True)
	handle = lock_path.open("w", encoding="utf-8")
	try:
		fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
	except BlockingIOError:
		handle.close()
		raise RuntimeError("integrity cycle already running")
	return handle


def main(argv: Sequence[str] | None = None) -> int:
	args = parse_args(argv)
	attempt = int(time.time())
	last_success = 0
	try:
		previous = load_state(args.state)
		last_success = int(previous.get("last_success_timestamp", 0))
		with acquire_lock(args.lock):
			targets = load_targets(args.catalog)
			with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.site_workers, max(1, len(targets)))) as pool:
				futures = [
					pool.submit(
						check_target, target, timeout=args.timeout, page_size_cap=args.page_size_cap,
						resource_size_cap=args.resource_size_cap, max_resources=args.max_resources,
						resource_workers=args.resource_workers,
						resource_failure_threshold=args.resource_failure_ratio,
						min_visible_chars=args.min_visible_chars, user_agent=args.user_agent,
					)
					for target in targets
				]
				results = [future.result() for future in futures]
			now = int(time.time())
			state, counts = update_state(previous, results, args.confirmation_cycles, now)
			atomic_write(args.state, json.dumps(state, indent=2, sort_keys=True) + "\n")
			atomic_write(args.output, render_metrics(results, counts, args.confirmation_cycles))
			atomic_write(
				args.self_output,
				render_self_metrics(
					True, True, attempt, now, len(targets), "none", args.interval_seconds
				),
			)
	except (CatalogValidationError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
		error = "catalog_invalid" if isinstance(exc, CatalogValidationError) else "runtime_error"
		try:
			atomic_write(
				args.self_output,
				render_self_metrics(
					False,
					not isinstance(exc, CatalogValidationError),
					attempt,
					last_success,
					0,
					error,
					args.interval_seconds,
				),
			)
		except OSError:
			pass
		print(f"site integrity checker failed ({error}): {exc}", file=sys.stderr)
		return 1
	print(f"checked {len(results)} integrity targets; current_problems={sum(result.bad for result in results)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
