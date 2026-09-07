#!/usr/bin/env python3
"""Render deterministic Prometheus file_sd targets from the service catalog."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from monitoring_catalog import CatalogValidationError, iter_http_services, load_catalog


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPOSITORY_ROOT / "monitoring" / "service-catalog.yml"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "monitoring" / "prometheus" / "file_sd" / "http_targets.yml"


def canonical_index(catalog: Mapping) -> dict[tuple[str, str, str, str], tuple[Mapping, Mapping, Mapping, Mapping]]:
	index = {}
	for company in catalog["companies"]:
		for server in company["servers"]:
			for application in server["applications"]:
				for component in application["components"]:
					key = (
						str(company["label"]),
						str(server["alias"]),
						str(application["stack"]),
						str(component["service"]),
					)
					index[key] = (company, server, application, component)
	return index


def render_http_targets(catalog: Mapping) -> str:
	index = canonical_index(catalog)
	entries = []
	services = sorted(
		iter_http_services(catalog, "availability"),
		key=lambda item: (
			str(item["company"]),
			str(item["alias"]),
			str(item["stack"]),
			str(item["service"]),
			str(item["url"]),
		),
	)
	for item in services:
		key = (str(item["company"]), str(item["alias"]), str(item["stack"]), str(item["service"]))
		company, server, application, component = index[key]
		entries.append(
			{
				"targets": [str(item["url"])],
				"labels": {
					# Legacy labels are intentionally stable for existing rules/dashboards.
					"company": str(item["company"]),
					"alias": str(item["alias"]),
					"stack": str(item["stack"]),
					"service": str(item["service"]),
					"criticality": str(item["criticality"]),
					# Canonical IDs allow an unambiguous hierarchy during migration.
					"company_id": str(company["id"]),
					"server_id": str(server["id"]),
					"application_id": str(application["id"]),
					"component_id": str(component["id"]),
					"customer_visible": "true" if component["customer_visible"] else "false",
				},
			}
		)
	return yaml.safe_dump(
		entries,
		allow_unicode=True,
		default_flow_style=False,
		sort_keys=False,
		width=120,
	)


def atomic_write(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
	try:
		with os.fdopen(fd, "w", encoding="utf-8") as handle:
			handle.write(content)
			handle.flush()
			os.fsync(handle.fileno())
		os.chmod(temporary, 0o644)
		os.replace(temporary, path)
	except BaseException:
		try:
			os.unlink(temporary)
		except FileNotFoundError:
			pass
		raise


def main(argv: Sequence[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
	parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
	parser.add_argument("--check", action="store_true", help="fail if output is missing or differs")
	args = parser.parse_args(argv)
	try:
		catalog = load_catalog(args.catalog)
	except CatalogValidationError as exc:
		for error in exc.errors:
			print(f"ERROR: {error}", file=sys.stderr)
		return 1
	rendered = render_http_targets(catalog)
	output = Path(args.output)
	if args.check:
		try:
			current = output.read_text(encoding="utf-8")
		except OSError as exc:
			print(f"generated target file is unavailable: {exc}", file=sys.stderr)
			return 1
		if current != rendered:
			print(
				f"generated target file has drift: run {Path(__file__).name} --catalog {args.catalog} --output {args.output}",
				file=sys.stderr,
			)
			return 1
		print(f"generated target file is current: {output}")
		return 0
	atomic_write(output, rendered)
	print(f"rendered {len(list(iter_http_services(catalog, 'availability')))} HTTP targets to {output}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
