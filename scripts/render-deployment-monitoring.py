#!/usr/bin/env python3
"""Render deployment transport without changing existing scrape identities.

Run after privately preserving con's runtime config in the output directory.
Catalog/rules/dashboards come from the reviewed checkout; Loki/Blackbox runtime
configuration and Grafana encrypted settings are copied, never reconstructed.
"""
from pathlib import Path
import argparse
import re
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
RELAY = "172.23.0.1"
TRANSPORT = {
    "node-exporter-con2:9100": 19130,
    "node-exporter-voice:9100": 19131,
    "node-exporter-con:9100": 19110,
    "cadvisor-con:8080": 19111,
    "172.17.0.1:19100": 19100,
    "172.17.0.1:19101": 19101,
    "141.94.121.160:9100": 19120,
    "192.168.112.20:9182": 19182,
    "192.168.112.19:9182": 19183,
}

def render(config):
    for job in config["scrape_configs"]:
        name = job["job_name"]
        if name in {"alertmanager", "incident_gateway"}:
            for group in job["static_configs"]:
                group["labels"]["alias"] = "deployment"
        if name == "node_exporter_clients":
            job["static_configs"].append({"targets": ["node-exporter-deployment:9100"], "labels": {"company": "my own", "alias": "deployment"}})
        if name == "cadvisor_clients":
            job["static_configs"].append({"targets": ["cadvisor-deployment:8080"], "labels": {"company": "my own", "alias": "deployment"}})
        if name in {"node_exporter_clients", "cadvisor_clients", "windows_exporter_clients"}:
            relabel = job.setdefault("relabel_configs", [])
            relabel.insert(0, {"source_labels": ["__address__"], "target_label": "instance"})
            for target, port in TRANSPORT.items():
                relabel.append({"source_labels": ["__address__"], "regex": re.escape(target), "target_label": "__address__", "replacement": f"{RELAY}:{port}"})
        if name == "mikrotik_snmp":
            for rule in job["relabel_configs"]:
                if rule.get("target_label") == "__address__":
                    rule["replacement"] = f"{RELAY}:19116"
    return config

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/etc/rabbit-monitoring"))
    args = parser.parse_args()
    source = ROOT / "monitoring"
    output = args.output / "prometheus"
    output.mkdir(parents=True, exist_ok=True)
    config = render(yaml.safe_load((source / "prometheus/prometheus.yml").read_text()))
    (output / "prometheus.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    for name in ("rules", "file_sd"):
        shutil.copytree(source / "prometheus" / name, output / name, dirs_exist_ok=True)
    # Preserve existing datasource credentials/provisioning outside dashboards.
    for name in ("dashboards", "company-dashboards"):
        shutil.copytree(source / "grafana/provisioning" / name, args.output / "grafana/provisioning" / name, dirs_exist_ok=True)
    print("Rendered deployment scrape transport, reviewed rules and dashboards; credentials untouched")

if __name__ == "__main__":
    main()
