from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CATALOG = ROOT / "monitoring" / "service-catalog.yml"
if str(SCRIPTS) not in sys.path:
	sys.path.insert(0, str(SCRIPTS))

from monitoring_catalog import load_catalog, validate_catalog  # noqa: E402


def load_script(filename: str, module_name: str):
	spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	assert spec.loader is not None
	spec.loader.exec_module(module)
	return module


availability = load_script("scheduled-public-site-checker.py", "scheduled_public_site_checker")
integrity = load_script("site-integrity-checker.py", "site_integrity_checker")
events = load_script("service-event-metrics.py", "service_event_metrics")
renderer = load_script("render-monitoring-config.py", "render_monitoring_config")


class CatalogTests(unittest.TestCase):
	def test_repository_catalog_is_strictly_valid_and_legacy_mapped(self):
		catalog = load_catalog(CATALOG)
		self.assertEqual(catalog["version"], 2)
		self.assertEqual(len(catalog["http_services"]), 13)
		self.assertEqual(validate_catalog(catalog), [])

	def test_runtime_inventory_is_active_and_planned_components_not_expected(self):
		catalog = load_catalog(CATALOG)
		companies = {company["id"]: company for company in catalog["companies"]}
		internal = companies["my-own"]
		con = next(server for server in internal["servers"] if server["id"] == "con")
		applications = {application["id"]: application for application in con["applications"]}
		self.assertEqual(applications["openclaw-stack"]["status"], "active")
		monitoring = {component["id"]: component for component in applications["monitoring"]["components"]}
		self.assertTrue(monitoring["prometheus"]["expected"])
		self.assertFalse(monitoring["alertmanager"]["expected"])
		self.assertFalse(monitoring["incident-gateway"]["expected"])

	def test_unknown_fields_are_rejected(self):
		catalog = copy.deepcopy(load_catalog(CATALOG))
		catalog["companies"][0]["mystery"] = True
		self.assertTrue(any("unknown field 'mystery'" in error for error in validate_catalog(catalog)))

	def test_unknown_event_date_requires_explicit_status(self):
		catalog = copy.deepcopy(load_catalog(CATALOG))
		event = {
			"id": "example-unknown",
			"type": "subscription",
			"title": "Example fixture",
			"company": "greenleaf",
			"server": "cloud",
			"due_at": None,
			"status": "date_unknown",
			"owners": ["rabbit-systems-ops"],
			"customer_visible": True,
			"repository": None,
			"runbook": None,
		}
		catalog["service_events"].append(event)
		self.assertEqual(validate_catalog(catalog), [])
		event["status"] = "active"
		self.assertTrue(any("missing due_at" in error for error in validate_catalog(catalog)))


class AvailabilityTests(unittest.TestCase):
	def target(self, url: str, bucket: int = 0):
		return availability.Target(url, {"site_instance": url}, bucket)

	def result(self, success: bool, checked_at: int = 100):
		return availability.ProbeResult(success, 200 if success else 0, 0.01, "" if success else "timeout", checked_at)

	def test_recovery_on_final_attempt_is_never_confirmed_down(self):
		state = availability.TargetState(self.target("https://example.com"), [self.result(False), self.result(False), self.result(True)])
		self.assertFalse(availability.is_confirmed_down(state, 2))
		state.attempts[-1] = self.result(False)
		self.assertTrue(availability.is_confirmed_down(state, 2))

	def test_queue_buckets_are_real_separate_batches(self):
		targets = [self.target("https://b.example", 2), self.target("https://a.example", 1), self.target("https://c.example", 2)]
		calls = []

		def fake_probe(batch, _timeout, _workers, _agent):
			batch = list(batch)
			calls.append([target.queue_bucket for target in batch])
			return {target.url: self.result(True) for target in batch}

		availability.probe_bucket_batches(targets, 1, 2, "agent", 0, probe=fake_probe)
		self.assertEqual(calls, [[1], [2, 2]])

	def test_retry_set_drops_successful_targets(self):
		a = self.target("https://a.example")
		b = self.target("https://b.example")
		calls = []

		def fake_buckets(batch, *_args):
			batch = list(batch)
			calls.append([target.url for target in batch])
			if len(calls) == 1:
				return {a.url: self.result(True), b.url: self.result(False)}
			return {b.url: self.result(True)}

		with tempfile.TemporaryDirectory() as directory:
			args = SimpleNamespace(
				catalog="unused", queue_buckets=4, retry_count=3, retry_interval=0,
				timeout=1, max_workers=2, user_agent="agent", bucket_pause=0,
				output=str(Path(directory) / "availability.prom"),
				state=str(Path(directory) / "state.json"), failure_threshold=2,
			)
			with mock.patch.object(availability, "load_targets", return_value=({}, [a, b])), mock.patch.object(
				availability, "probe_bucket_batches", side_effect=fake_buckets
			):
				states, _start, _finish = availability.run(args)
			self.assertEqual(calls, [[a.url, b.url], [b.url]])
			self.assertEqual([len(state.attempts) for state in states], [1, 2])
			self.assertTrue(json.loads(Path(args.state).read_text())["last_success_timestamp"] > 0)


class IntegrityTests(unittest.TestCase):
	def test_extracts_img_css_js_without_content_baseline(self):
		html = b"""<html><head><title>Normal page</title><link rel='stylesheet' href='/a.css'></head>
		<body><h1>Welcome</h1><p>This is a sufficiently complete public page.</p>
		<img src='/logo.png'><script src='https://cdn.example/app.js'></script></body></html>"""
		reasons, resources = integrity.inspect_html("https://example.com/", html, 20, 20)
		self.assertEqual(reasons, [])
		self.assertEqual(set(resources.values()), {"image", "css", "javascript"})

	def test_obvious_error_and_empty_pages_are_detected(self):
		reasons, _resources = integrity.inspect_html(
			"https://example.com/", b"<html><title>502 Bad Gateway</title></html>", 20, 40
		)
		self.assertIn("error_page", reasons)
		self.assertIn("empty_page", reasons)

	def test_second_bad_cycle_confirms_and_labels_avoid_node_exporter_collision(self):
		target = integrity.IntegrityTarget(
			"https://example.com", {"site_company": "greenleaf", "site_alias": "cloud", "stack": "site", "service": "app"}
		)
		result = integrity.IntegrityResult(target, True, ("error_page",), 200, 100, False, 1, 1, 1, 1.0, 100)
		first, first_counts = integrity.update_state({"targets": {}}, [result], 2, 100)
		_second, second_counts = integrity.update_state(first, [result], 2, 200)
		self.assertEqual(first_counts[target.url], 1)
		self.assertEqual(second_counts[target.url], 2)
		metrics = integrity.render_metrics([result], second_counts, 2)
		self.assertIn("site_integrity_confirmed_problem", metrics)
		self.assertIn('site_company="greenleaf"', metrics)
		self.assertIn('site_alias="cloud"', metrics)
		self.assertNotIn('{company="', metrics)
		self.assertNotIn(',company="', metrics)
		self.assertNotIn('{alias="', metrics)
		self.assertNotIn(',alias="', metrics)


class ServiceEventTests(unittest.TestCase):
	def test_due_unknown_skip_and_collision_safe_labels(self):
		catalog = copy.deepcopy(load_catalog(CATALOG))
		base = {
			"type": "domain", "title": "Test domain", "company": "greenleaf", "server": "cloud",
			"owners": ["rabbit-systems-ops"], "customer_visible": True,
			"repository": None, "runbook": None,
		}
		catalog["service_events"] = [
			base | {"id": "known", "due_at": "2030-01-02", "status": "active"},
			base | {"id": "unknown", "due_at": None, "status": "date_unknown"},
		]
		metrics = events.render_metrics(catalog, dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))
		self.assertEqual(metrics.count("service_event_due_timestamp_seconds{"), 1)
		self.assertEqual(metrics.count("service_event_days_remaining{"), 1)
		self.assertIn('service_event_error{', metrics)
		self.assertIn('error="date_unknown"', metrics)
		self.assertIn('event_company="greenleaf"', metrics)
		self.assertIn('event_alias="cloud"', metrics)
		self.assertIn("service_catalog_server_info{", metrics)
		self.assertIn("service_catalog_application_info{", metrics)
		self.assertIn("service_catalog_component_info{", metrics)
		self.assertIn('expected="true"', metrics)
		self.assertNotIn('{company="', metrics)
		self.assertNotIn(',company="', metrics)


class ConfigRendererTests(unittest.TestCase):
	def test_render_is_deterministic_and_has_legacy_and_canonical_labels(self):
		catalog = load_catalog(CATALOG)
		first = renderer.render_http_targets(catalog)
		second = renderer.render_http_targets(catalog)
		self.assertEqual(first, second)
		entries = __import__("yaml").safe_load(first)
		self.assertEqual(len(entries), len(catalog["http_services"]))
		for entry in entries:
			self.assertTrue({"company", "alias", "stack", "service", "criticality"} <= set(entry["labels"]))
			self.assertTrue({"company_id", "server_id", "application_id", "component_id"} <= set(entry["labels"]))

	def test_committed_generated_file_has_no_drift(self):
		expected = renderer.render_http_targets(load_catalog(CATALOG))
		actual = (ROOT / "monitoring/prometheus/file_sd/http_targets.yml").read_text(encoding="utf-8")
		self.assertEqual(actual, expected)


if __name__ == "__main__":
	unittest.main()
