#!/usr/bin/env python3
"""Validate the canonical managed-monitoring service catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from monitoring_catalog import CatalogValidationError, load_catalog


DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "monitoring" / "service-catalog.yml"


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("catalog", nargs="?", default=str(DEFAULT_CATALOG))
	args = parser.parse_args()
	try:
		catalog = load_catalog(args.catalog)
	except CatalogValidationError as exc:
		for error in exc.errors:
			print(f"ERROR: {error}", file=sys.stderr)
		return 1
	company_count = len(catalog["companies"])
	server_count = sum(len(company["servers"]) for company in catalog["companies"])
	application_count = sum(
		len(server["applications"])
		for company in catalog["companies"]
		for server in company["servers"]
	)
	component_count = sum(
		len(application["components"])
		for company in catalog["companies"]
		for server in company["servers"]
		for application in server["applications"]
	)
	print(
		"service catalog valid: "
		f"companies={company_count} servers={server_count} "
		f"applications={application_count} components={component_count} "
		f"http_services={len(catalog['http_services'])} "
		f"service_events={len(catalog['service_events'])}"
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
