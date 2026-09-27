import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from monitoring_catalog import load_catalog, validate_catalog


class HomeFPCMonitoring(unittest.TestCase):
    def test_enrollment_plan_only_appends_reviewed_target_and_relay(self):
        spec = importlib.util.spec_from_file_location("home_enrollment", ROOT / "scripts/enroll-home-fpc-monitoring.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        prom = {"global": {"scrape_interval": "15s"}, "scrape_configs": [
            {"job_name": "other", "static_configs": [{"targets": ["unrelated:9100"]}]},
            {"job_name": "windows_exporter_clients", "file_sd_configs": [{"files": ["/etc/prometheus/file_sd/windows_targets.yml"]}],
             "relabel_configs": [{"source_labels": ["__address__"], "target_label": "instance"}]}]}
        targets = [{"targets": ["existing:9182"], "labels": {"alias": "existing", "company": "other"}}]
        dashboard = (ROOT / "monitoring/grafana/provisioning/dashboards/managed-windows-host.json").read_bytes()
        files = module.candidates(yaml.safe_dump(prom).encode(), yaml.safe_dump(targets).encode(), dashboard)
        changed = yaml.safe_load(files[str(module.PROMETHEUS)])
        self.assertEqual(changed["global"], prom["global"])
        self.assertEqual(changed["scrape_configs"][0], prom["scrape_configs"][0])
        self.assertEqual(changed["scrape_configs"][1]["relabel_configs"][:-1], prom["scrape_configs"][1]["relabel_configs"])
        self.assertEqual(yaml.safe_load(files[str(module.TARGETS)])[:-1], targets)
        self.assertIn("PermitListen 172.23.0.1:19132", files[str(module.SSH_FRAGMENT)].decode())
        self.assertIn("MaxSessions 0", files[str(module.SSH_FRAGMENT)].decode())
        self.assertTrue(files[str(module.SSH_FRAGMENT)].endswith(b"Match all\n"))
        self.assertIn('permitopen="none"', module.AUTHORIZED_KEY)
        with self.assertRaises(RuntimeError):
            module.candidates(files[str(module.PROMETHEUS)], files[str(module.TARGETS)], dashboard)
        broken = copy.deepcopy(prom)
        broken["scrape_configs"][1]["relabel_configs"] = []
        with self.assertRaises(RuntimeError):
            module.candidates(yaml.safe_dump(broken).encode(), yaml.safe_dump(targets).encode(), dashboard)

    def test_catalog_is_physical_home_host_with_no_provider_or_guessed_apps(self):
        doc = load_catalog(ROOT / "monitoring/service-catalog.yml")
        company = next(c for c in doc["companies"] if c["id"] == "my-own")
        server = next(s for s in company["servers"] if s["id"] == "fpc")
        self.assertEqual(server["metrics_profile"], {"kind": "windows_exporter", "filesystem": "M:"})
        self.assertEqual(server["applications"], [])
        self.assertFalse(server["customer_visible"])
        self.assertNotIn("provider_binding", server)
        self.assertEqual(validate_catalog(doc), [])
        for profile in (None, {}, {"kind": "other", "filesystem": "M:"}, {"kind": "windows_exporter", "filesystem": "M:\\rs"}):
            changed = copy.deepcopy(doc)
            company = next(c for c in changed["companies"] if c["id"] == "my-own")
            next(s for s in company["servers"] if s["id"] == "fpc")["metrics_profile"] = profile
            self.assertTrue(validate_catalog(changed))

    def test_scrape_target_uses_dedicated_private_relay(self):
        groups = yaml.safe_load((ROOT / "monitoring/prometheus/file_sd/windows_targets.yml").read_text())
        fpc = [group for group in groups if group["labels"]["alias"] == "fpc"]
        self.assertEqual(fpc, [{"targets": ["windows-exporter-fpc:9182"], "labels": {"alias": "fpc", "company": "my own", "role": "development"}}])
        spec = importlib.util.spec_from_file_location("home_transport", ROOT / "scripts/render-deployment-monitoring.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.TRANSPORT["windows-exporter-fpc:9182"], 19132)

    def test_dashboard_uses_exact_windows_job_and_both_scope_variables(self):
        data = json.loads((ROOT / "monitoring/grafana/provisioning/dashboards/managed-windows-host.json").read_text())
        self.assertEqual(data["uid"], "managed-windows-host")
        expressions = [t["expr"] for p in data["panels"] for t in p.get("targets", [])]
        self.assertTrue(expressions)
        for expr in expressions:
            self.assertIn('job="windows_exporter_clients"', expr)
            self.assertIn('company=~"$company"', expr)
            self.assertIn('alias=~"$server"', expr)
            self.assertNotIn("node_", expr)
        self.assertTrue(any("10–15" in p.get("options", {}).get("content", "") for p in data["panels"]))


if __name__ == "__main__":
    unittest.main()
