"""MB Skolas Live/Test identities and private host telemetry stay aligned."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class MBSkolasMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = yaml.safe_load((ROOT / "monitoring/service-catalog.yml").read_text())
        cls.company = next(item for item in cls.catalog["companies"] if item["id"] == "mb-skolas")
        cls.server = next(item for item in cls.company["servers"] if item["alias"] == "wherp")

    def test_one_host_contains_distinct_live_and_test_applications(self):
        self.assertEqual(self.server["status"], "active")
        self.assertEqual(self.server["role"], "production")
        self.assertEqual(self.server["monitoring"]["signals"], ["node", "containers", "availability"])
        self.assertFalse(self.company["customer_visible"])
        self.assertFalse(self.server["customer_visible"])
        apps = {app["stack"]: app for app in self.server["applications"]}
        self.assertEqual(set(apps), {"erpnext3pl", "erpnext3plstg"})
        services = {"backend", "db", "frontend", "queue-long", "queue-short", "redis-cache", "redis-queue", "scheduler", "websocket"}
        for stack, app in apps.items():
            with self.subTest(stack=stack):
                self.assertEqual(app["status"], "active")
                self.assertEqual(app["monitoring"]["signals"], ["containers", "availability"])
                self.assertFalse(app["customer_visible"])
                self.assertEqual({component["service"] for component in app["components"]}, services)
                self.assertTrue(all(component["expected"] for component in app["components"]))
                self.assertTrue(all(not component["customer_visible"] for component in app["components"]))

    def test_http_probes_keep_environments_separate_without_backup_or_integrity_claims(self):
        probes = {item["stack"]: item for item in self.catalog["http_services"] if item["company"] == "mb-skolas"}
        self.assertEqual({stack: item["url"] for stack, item in probes.items()}, {
            "erpnext3pl": "https://erpnext.77.237.244.169.sslip.io",
            "erpnext3plstg": "https://erpnext-staging.77.237.244.169.sslip.io",
        })
        self.assertEqual({stack: item["criticality"] for stack, item in probes.items()}, {"erpnext3pl": "high", "erpnext3plstg": "medium"})
        self.assertTrue(all(item["alias"] == "wherp" and item["service"] == "frontend" for item in probes.values()))
        self.assertTrue(all(item["monitoring"] == {"enabled": True, "availability": True, "integrity": False} for item in probes.values()))
        self.assertTrue(all(signal not in self.server["monitoring"]["signals"] for signal in ("backups", "logs", "integrity")))

    def test_exporter_and_relay_have_one_private_scoped_path(self):
        compose = yaml.safe_load((ROOT / "deploy/mb-skolas-host-metrics.compose.yml").read_text())
        exporter = compose["services"]["node-exporter"]
        self.assertEqual(exporter["network_mode"], "host")
        self.assertNotIn("ports", exporter)
        self.assertIn("--web.listen-address=127.0.0.1:19100", exporter["command"])
        self.assertIn("--collector.textfile.directory=/textfile", exporter["command"])
        self.assertIn("/var/lib/node-exporter-textfile:/textfile:ro", exporter["volumes"])
        self.assertFalse(any("docker.sock" in volume for volume in exporter["volumes"]))
        self.assertTrue(exporter["read_only"])
        self.assertEqual(exporter["cap_drop"], ["ALL"])

        sshd = (ROOT / "deploy/host-metrics-sshd.conf").read_text()
        wherp_section = sshd.split("Match User monitoring-wherp\n", 1)[1].split("Match ", 1)[0]
        self.assertIn("PermitListen 172.23.0.1:19133", wherp_section)
        self.assertIn("PasswordAuthentication no", wherp_section)
        self.assertIn("PermitOpen none", wherp_section)
        self.assertIn("MaxSessions 0", wherp_section)

        spec = importlib.util.spec_from_file_location("deployment_transport_mb", ROOT / "scripts/render-deployment-monitoring.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.TRANSPORT["windows-exporter-fpc:9182"], 19132)
        self.assertEqual(module.TRANSPORT["node-exporter-wherp:9100"], 19133)
        self.assertEqual(len(module.TRANSPORT.values()), len(set(module.TRANSPORT.values())))
        rendered = module.render(yaml.safe_load((ROOT / "monitoring/prometheus/prometheus.yml").read_text()))
        job = next(item for item in rendered["scrape_configs"] if item["job_name"] == "node_exporter_clients")
        target = next(item for item in job["static_configs"] if item["labels"].get("alias") == "wherp")
        self.assertEqual(target, {"targets": ["node-exporter-wherp:9100"], "labels": {"alias": "wherp", "company": "mb-skolas"}})
        self.assertIn({"source_labels": ["__address__"], "regex": "node\\-exporter\\-wherp:9100", "target_label": "__address__", "replacement": "172.23.0.1:19133"}, job["relabel_configs"])

    def test_docker_inventory_timer_uses_reviewed_script(self):
        service = (ROOT / "deploy/mb-skolas-docker-stack-metrics.service").read_text()
        timer = (ROOT / "deploy/mb-skolas-docker-stack-metrics.timer").read_text()
        self.assertIn("/opt/rabbit-host-metrics/docker-stack-metrics.sh", service)
        self.assertIn("UMask=0022", service)
        self.assertIn("OnUnitInactiveSec=180s", timer)
        self.assertTrue((ROOT / "scripts/docker-stack-metrics.sh").is_file())


if __name__ == "__main__":
    unittest.main()
