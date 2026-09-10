"""Owner-confirmed inventory must not imply discovery or move existing workloads."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
	sys.path.insert(0, str(SCRIPTS))

from monitoring_catalog import load_catalog  # noqa: E402


def load_script(filename: str, name: str):
	spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
	module = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(module)
	return module


EVENTS = load_script("service-event-metrics.py", "ownership_service_events")
RENDERER = load_script("render-monitoring-config.py", "ownership_http_renderer")

CONFIRMED_OWNERS = {
	"cloud": "greenleaf",
	"testing": "greenleaf",
	"con": "my-own",
	"con2": "my-own",
	"deployment": "my-own",
	"voice": "my-own",
	"seedquest": "seedquest",
	"wherp": "mb-skolas",
	"howbot": "rentall",
	"payroll": "rentall",
}
UNDISCOVERED_SERVERS = {"seedquest", "wherp"}

# A future workload migration must deliberately update this expectation; declaring
# a destination for legacy sites is not evidence that they have moved there.
EXISTING_APPLICATIONS = {
	("greenleaf", "cloud"): {
		"nextcloud-docker", "greenleafpacificcom", "erpgreenleafpacificcom",
		"cgigreenleafpacificcom", "sggreenleafpacificcom", "spacomfj",
		"furniturecomfj", "pacificcleaning", "fijipacificcleaning",
		"testingerpgreenleafpacificcom", "testinggreenleafpacificcom",
		"testing2greenleafpacificcom", "bulataxicom", "beautylabspacomfj", "trexfijicom",
	},
	("greenleaf", "testing"): {"company-monitor", "pterodactyl", "wordpress"},
	("greenleaf", "new"): set(),
	("rentall", "payroll"): {"payrollbot21"},
	("rentall", "howbot"): {
		"howprod", "how-team", "how-team-monitoring", "receipt-paybot", "erpnext",
		"how-team-ocr-poc", "ovh-reboot-bot",
	},
	("my-own", "test"): {
		"erpnext3pl", "estimator-bot20", "kzpo-report-bot", "receipt-paybot",
		"report-service", "webtrees", "woocommerce",
	},
	("my-own", "deployment"): {"monitoring", "rabbit-platform"},
	("my-own", "con"): {
		"monitoring", "monitoring-promtail", "openclaw-stack", "my-erp",
		"rabbitsystems-mail", "monobank-balance-bot", "rabbitsystems-site", "quirky",
	},
}


class ServerOwnershipTests(unittest.TestCase):
	def setUp(self):
		self.catalog = load_catalog(ROOT / "monitoring/service-catalog.yml")
		self.companies = {company["id"]: company for company in self.catalog["companies"]}
		self.servers = {
			(company["id"], server["id"]): server
			for company in self.catalog["companies"] for server in company["servers"]
		}

	def test_confirmed_servers_belong_to_exactly_one_confirmed_company(self):
		for alias, owner in CONFIRMED_OWNERS.items():
			with self.subTest(alias=alias):
				matches = [
					(company_id, server_id) for (company_id, server_id), server in self.servers.items()
					if server["alias"] == alias
				]
				self.assertEqual(matches, [(owner, alias)])
		for alias in ("cloud", "seedquest", "wherp", "howbot", "payroll"):
			self.assertEqual(self.servers[(CONFIRMED_OWNERS[alias], alias)]["role"], "production")
		# Existing exporter metadata may retain the historical staging role.
		self.assertIn(self.servers[("greenleaf", "testing")]["role"], {"test", "testing", "staging"})

	def test_how_renames_presentation_without_renaming_legacy_identity(self):
		how = self.companies["rentall"]
		self.assertEqual(how["label"], "rentall")
		self.assertEqual(how["display_name"], "HOW Production")
		self.assertNotIn("how", self.companies)
		for alias in ("howbot", "payroll"):
			self.assertIn("HOW", self.servers[("rentall", alias)]["display_name"])
			legacy = next(node for node in self.catalog["nodes"] if node["alias"] == alias)
			self.assertEqual(legacy["company"], "rentall")
		self.assertEqual(self.companies["my-own"]["label"], "my own")

	def test_undiscovered_servers_have_no_invented_workloads_or_monitoring(self):
		for alias in UNDISCOVERED_SERVERS:
			with self.subTest(alias=alias):
				server = self.servers[(CONFIRMED_OWNERS[alias], alias)]
				self.assertEqual(server["status"], "pending_discovery")
				self.assertEqual(server["monitoring"], {"enabled": False, "signals": []})
				self.assertEqual(server["applications"], [])
				self.assertFalse(server["customer_visible"])
		# Visibility metadata is not permission to provision customer Grafana access.
		for company_id in ("seedquest", "mb-skolas"):
			self.assertFalse(self.companies[company_id]["customer_visible"])

	def test_prior_workload_placement_and_unconfirmed_legacy_servers_are_retained(self):
		for key, expected in EXISTING_APPLICATIONS.items():
			with self.subTest(server=key):
				actual = {app["id"] for app in self.servers[key]["applications"]}
				self.assertTrue(expected <= actual, f"workloads moved or removed: {expected - actual}")
		self.assertEqual(self.servers[("greenleaf", "new")]["status"], "pending_access")
		self.assertEqual(self.servers[("my-own", "test")]["role"], "lab")
		legacy = {(node["company"], node["alias"]): node for node in self.catalog["nodes"]}
		self.assertEqual(legacy[("greenleaf", "new")]["status"], "pending_access")
		self.assertEqual(legacy[("my own", "test")]["network"], "nat_reverse_tunnel")

	def test_metadata_update_creates_no_scrape_targets_and_preserves_generated_http_targets(self):
		expected = (ROOT / "monitoring/prometheus/file_sd/http_targets.yml").read_text(encoding="utf-8")
		self.assertEqual(RENDERER.render_http_targets(self.catalog), expected)
		self.assertEqual(len(self.catalog["http_services"]), 13)
		for service in self.catalog["http_services"]:
			self.assertEqual((service["company"], service["alias"]), ("greenleaf", "cloud"))
		prometheus = yaml.safe_load((ROOT / "monitoring/prometheus/prometheus.yml").read_text())
		configured_aliases = {
			config.get("labels", {}).get("alias")
			for job in prometheus["scrape_configs"] for config in job.get("static_configs", [])
		}
		self.assertFalse(UNDISCOVERED_SERVERS & configured_aliases)

	def test_undiscovered_inventory_is_explicit_without_application_metrics(self):
		metrics = EVENTS.render_metrics(self.catalog, dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))
		lines = metrics.splitlines()
		for alias in UNDISCOVERED_SERVERS:
			with self.subTest(alias=alias):
				matching = [line for line in lines if f'catalog_alias="{alias}"' in line]
				self.assertEqual(len(matching), 1)
				self.assertTrue(matching[0].startswith("service_catalog_server_info{"))
				self.assertIn('server_status="pending_discovery"', matching[0])
				self.assertIn(f'company_id="{CONFIRMED_OWNERS[alias]}"', matching[0])
		for alias in ("howbot", "payroll"):
			matching = next(
				line for line in lines if line.startswith("service_catalog_server_info{")
				and f'catalog_alias="{alias}"' in line
			)
			self.assertIn('catalog_company="rentall"', matching)
			self.assertIn('company_id="rentall"', matching)


if __name__ == "__main__":
	unittest.main()
