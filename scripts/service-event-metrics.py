#!/usr/bin/env python3
"""Render renewal/service-event deadlines from the validated catalog as Prometheus metrics."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

from monitoring_catalog import CatalogValidationError, load_catalog, parse_due_at


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


def hierarchy_index(catalog: Mapping) -> dict[tuple[str, str, str | None, str | None], dict[str, str]]:
	index = {}
	for company in catalog["companies"]:
		for server in company["servers"]:
			base = {
				"event_company": str(company["label"]),
				"event_alias": str(server["alias"]),
				"stack": "",
				"service": "",
			}
			index[(company["id"], server["id"], None, None)] = base
			for application in server["applications"]:
				app_labels = base | {"stack": str(application["stack"])}
				index[(company["id"], server["id"], application["id"], None)] = app_labels
				for component in application["components"]:
					index[(company["id"], server["id"], application["id"], component["id"])] = (
						app_labels | {"service": str(component["service"])}
					)
	return index


def event_labels(event: Mapping, index: Mapping) -> dict[str, str]:
	key = (
		event["company"],
		event["server"],
		event.get("application"),
		event.get("component"),
	)
	labels = dict(index[key])
	labels.update(
		{
			"event_id": str(event["id"]),
			"event_type": str(event["type"]),
			"event_title": str(event["title"]),
			"customer_visible": "true" if event["customer_visible"] else "false",
		}
	)
	return labels


def render_metrics(catalog: Mapping, now: dt.datetime) -> str:
	if now.tzinfo is None:
		raise ValueError("now must be timezone-aware")
	now = now.astimezone(dt.timezone.utc)
	index = hierarchy_index(catalog)
	lines = [
		"# HELP service_catalog_info Validated service catalog version loaded by the generator.",
		"# TYPE service_catalog_info gauge",
		metric_line("service_catalog_info", {"version": catalog["version"]}, 1),
		"# HELP service_catalog_company_count Canonical companies in the catalog.",
		"# TYPE service_catalog_company_count gauge",
		f"service_catalog_company_count {len(catalog['companies'])}",
		"# HELP service_catalog_server_info Server inventory declared in the validated catalog.",
		"# TYPE service_catalog_server_info gauge",
		"# HELP service_catalog_application_info Application inventory declared in the validated catalog.",
		"# TYPE service_catalog_application_info gauge",
		"# HELP service_catalog_component_info Component inventory and expected-running policy declared in the validated catalog.",
		"# TYPE service_catalog_component_info gauge",
		"# HELP service_event_due_timestamp_seconds Verified event due time in UTC epoch seconds.",
		"# TYPE service_event_due_timestamp_seconds gauge",
		"# HELP service_event_days_remaining Fractional days until the verified due time.",
		"# TYPE service_event_days_remaining gauge",
		"# HELP service_event_error Catalog event skipped because it cannot yield deadline metrics.",
		"# TYPE service_event_error gauge",
		"# HELP service_event_error_count Number of active event entries skipped in this render.",
		"# TYPE service_event_error_count gauge",
	]
	for company in catalog["companies"]:
		for server in company["servers"]:
			base_labels = {
				"catalog_company": str(company["label"]),
				"catalog_alias": str(server["alias"]),
				"company_id": str(company["id"]),
				"server_id": str(server["id"]),
				"server_status": str(server["status"]),
				"customer_visible": "true" if server["customer_visible"] else "false",
			}
			lines.append(metric_line("service_catalog_server_info", base_labels, 1))
			for application in server["applications"]:
				application_labels = base_labels | {
					"application_id": str(application["id"]),
					"stack": str(application["stack"]),
					"application_status": str(application["status"]),
					"customer_visible": "true" if application["customer_visible"] else "false",
				}
				lines.append(metric_line("service_catalog_application_info", application_labels, 1))
				for component in application["components"]:
					component_labels = application_labels | {
						"component_id": str(component["id"]),
						"service": str(component["service"]),
						"expected": "true" if component["expected"] else "false",
						"customer_visible": "true" if component["customer_visible"] else "false",
					}
					lines.append(metric_line("service_catalog_component_info", component_labels, 1))
	error_count = 0
	for event in sorted(catalog["service_events"], key=lambda item: str(item["id"])):
		if event["status"] in {"paused", "retired"}:
			continue
		labels = event_labels(event, index)
		due_at = parse_due_at(event.get("due_at"))
		if due_at is None:
			error_count += 1
			error_labels = dict(labels)
			error_labels["error"] = "date_unknown"
			lines.append(metric_line("service_event_error", error_labels, 1))
			continue
		due_timestamp = due_at.timestamp()
		days_remaining = (due_at - now).total_seconds() / 86_400
		lines.append(metric_line("service_event_due_timestamp_seconds", labels, f"{due_timestamp:.0f}"))
		lines.append(metric_line("service_event_days_remaining", labels, f"{days_remaining:.6f}"))
	lines.append(f"service_event_error_count {error_count}")
	return "\n".join(lines) + "\n"


def render_self_metrics(up: bool, catalog_valid: bool, attempt: int, last_success: int, error: str) -> str:
	return "\n".join(
		(
			"# HELP service_event_metrics_up Whether the latest service-event metrics render completed.",
			"# TYPE service_event_metrics_up gauge",
			f"service_event_metrics_up {int(up)}",
			"# HELP service_event_catalog_valid Whether strict service catalog validation succeeded.",
			"# TYPE service_event_catalog_valid gauge",
			f"service_event_catalog_valid {int(catalog_valid)}",
			"# HELP service_event_metrics_last_attempt_timestamp_seconds Latest generator invocation.",
			"# TYPE service_event_metrics_last_attempt_timestamp_seconds gauge",
			f"service_event_metrics_last_attempt_timestamp_seconds {attempt}",
			"# HELP service_event_metrics_last_success_timestamp_seconds Latest successful render; use time() minus this for staleness.",
			"# TYPE service_event_metrics_last_success_timestamp_seconds gauge",
			f"service_event_metrics_last_success_timestamp_seconds {last_success}",
			"# HELP service_event_metrics_error Latest bounded generator error category.",
			"# TYPE service_event_metrics_error gauge",
			metric_line("service_event_metrics_error", {"error": error}, 1),
		)
	) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--catalog", default="/root/monitoring/service-catalog.yml")
	parser.add_argument("--output", default="/var/lib/node-exporter-textfile/service-events.prom")
	parser.add_argument("--self-output")
	args = parser.parse_args(argv)
	args.self_output = args.self_output or str(
		Path(args.output).with_name("service-event-metrics-self.prom")
	)
	return args


def main(argv: Sequence[str] | None = None) -> int:
	args = parse_args(argv)
	attempt = int(time.time())
	try:
		catalog = load_catalog(args.catalog)
		now = dt.datetime.now(dt.timezone.utc)
		atomic_write(args.output, render_metrics(catalog, now))
		atomic_write(args.self_output, render_self_metrics(True, True, attempt, int(now.timestamp()), "none"))
	except (CatalogValidationError, OSError, ValueError, KeyError) as exc:
		error = "catalog_invalid" if isinstance(exc, CatalogValidationError) else "runtime_error"
		try:
			atomic_write(args.self_output, render_self_metrics(False, not isinstance(exc, CatalogValidationError), attempt, 0, error))
		except OSError:
			pass
		print(f"service event metrics failed ({error}): {exc}", file=sys.stderr)
		return 1
	print(f"rendered {len(catalog['service_events'])} service events")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
