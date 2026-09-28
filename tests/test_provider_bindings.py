import copy
import sys
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from monitoring_catalog import validate_catalog


class ProviderBindings(unittest.TestCase):
    def test_exact_bindings_and_invalid_variants(self):
        document = yaml.safe_load((ROOT / "monitoring/service-catalog.yml").read_text())
        self.assertEqual(validate_catalog(document), [])
        for value in [None, {}, {"account_ref": "other", "instance_id": "12"},
                      {"account_ref": "contabo-primary", "instance_id": 12},
                      {"account_ref": "contabo-primary", "instance_id": "0"}]:
            changed = copy.deepcopy(document)
            changed["companies"][2]["servers"][0]["provider_binding"] = value
            self.assertTrue(validate_catalog(changed))
        changed = copy.deepcopy(document)
        servers = changed["companies"][2]["servers"]
        servers[1]["provider_binding"] = servers[0]["provider_binding"]
        self.assertTrue(any("duplicate Contabo" in e for e in validate_catalog(changed)))
