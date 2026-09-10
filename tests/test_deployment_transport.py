import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deployment_transport", ROOT / "scripts/render-deployment-monitoring.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeploymentTransportTests(unittest.TestCase):
    def test_collectors_preserve_original_instance_before_transport_rewrite(self):
        original = yaml.safe_load((ROOT / "monitoring/prometheus/prometheus.yml").read_text())
        result = MODULE.render(original)
        by_name = {job["job_name"]: job for job in result["scrape_configs"]}
        for name in ("node_exporter_clients", "cadvisor_clients", "windows_exporter_clients"):
            rules = by_name[name]["relabel_configs"]
            self.assertEqual(rules[0], {"source_labels": ["__address__"], "target_label": "instance"})
            self.assertTrue(all(rule["replacement"].startswith("172.23.0.1:") for rule in rules[1:]))
        self.assertEqual(by_name["mikrotik_snmp"]["relabel_configs"][-1]["replacement"], "172.23.0.1:19116")

    def test_central_plane_moves_but_source_exporter_identity_remains(self):
        result = MODULE.render(yaml.safe_load((ROOT / "monitoring/prometheus/prometheus.yml").read_text()))
        by_name = {job["job_name"]: job for job in result["scrape_configs"]}
        for name in ("alertmanager", "incident_gateway"):
            self.assertEqual(by_name[name]["static_configs"][0]["labels"]["alias"], "deployment")
        nodes = {item["labels"]["alias"]: item["targets"] for item in by_name["node_exporter_clients"]["static_configs"]}
        self.assertEqual(nodes["con"], ["node-exporter-con:9100"])
        self.assertEqual(nodes["deployment"], ["node-exporter-deployment:9100"])

    def test_private_plane_exposes_no_public_service_ports(self):
        config = yaml.safe_load((ROOT / "deploy/deployment-monitoring-compose.yml").read_text())
        for service in config["services"].values():
            for port in service.get("ports", []):
                self.assertTrue(port.startswith("127.0.0.1:"), port)
        self.assertEqual(config["networks"]["default"]["name"], "monitoring_default")


if __name__ == "__main__":
    unittest.main()
