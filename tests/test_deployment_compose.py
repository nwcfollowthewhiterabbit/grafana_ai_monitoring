from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
INTEGRATED = ROOT / "deploy" / "con-monitoring-v2.override.yml"
LIVE = ROOT / "deploy" / "con-monitoring-v2.live.yml"
OPENCLAW_PAUSED = ROOT / "deploy" / "openclaw-grafana-paused.override.yml"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class IntegratedComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_yaml(INTEGRATED)
        self.services = self.config["services"]

    def test_override_adds_only_the_two_v2_services_without_builds(self) -> None:
        self.assertNotIn("name", self.config)
        self.assertEqual(set(self.services), {"alertmanager", "incident-gateway"})
        for service in self.services.values():
            self.assertNotIn("build", service)
            self.assertEqual(service["pull_policy"], "never")

    def test_shadow_is_fail_safe_default_and_live_requires_second_file(self) -> None:
        self.assertEqual(
            self.services["incident-gateway"]["environment"]["GATEWAY_MODE"],
            "shadow",
        )
        live = load_yaml(LIVE)
        self.assertEqual(set(live["services"]), {"incident-gateway"})
        self.assertEqual(
            live["services"]["incident-gateway"]["environment"],
            {"GATEWAY_MODE": "live"},
        )

    def test_mounts_are_absolute_bounded_and_do_not_use_existing_monitoring_state(self) -> None:
        expected_sources = {
            "/var/lib/rabbit-monitoring-v2/incident-gateway",
            "/var/lib/rabbit-monitoring-v2/alertmanager",
            "/opt/rabbit-monitoring-v2/monitoring/alertmanager/alertmanager.yml",
            "/opt/rabbit-monitoring-v2/monitoring/secrets/telegram_bot_token",
            "/opt/rabbit-monitoring-v2/monitoring/secrets/telegram_chat_id",
            "/opt/rabbit-monitoring-v2/monitoring/secrets/telegram_thread_id",
        }
        volumes = [
            volume
            for service in self.services.values()
            for volume in service.get("volumes", [])
        ]
        self.assertEqual({volume["source"] for volume in volumes}, expected_sources)
        for volume in volumes:
            self.assertTrue(Path(volume["source"]).is_absolute())
            self.assertFalse(volume["bind"]["create_host_path"])
            self.assertNotIn("/var/lib/monitoring", volume["source"])

    def test_ingress_is_loopback_only_and_containers_are_hardened(self) -> None:
        self.assertEqual(self.services["incident-gateway"]["ports"], ["127.0.0.1:8180:8080"])
        self.assertEqual(self.services["alertmanager"]["ports"], ["127.0.0.1:9093:9093"])
        for service in self.services.values():
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertIn("no-new-privileges:true", service["security_opt"])

    def test_only_exact_telegram_files_are_exposed_to_gateway(self) -> None:
        gateway = self.services["incident-gateway"]
        secret_volumes = [
            volume
            for volume in gateway["volumes"]
            if "/monitoring/secrets/" in volume["source"]
        ]
        self.assertEqual(len(secret_volumes), 3)
        self.assertTrue(all(volume["read_only"] for volume in secret_volumes))
        self.assertEqual(
            set(gateway["environment"]),
            {
                "GATEWAY_MODE",
                "GATEWAY_DATABASE_PATH",
                "TELEGRAM_BOT_TOKEN_FILE",
                "TELEGRAM_CHAT_ID_FILE",
                "TELEGRAM_MESSAGE_THREAD_ID_FILE",
            },
        )


class OpenClawPauseOverrideTests(unittest.TestCase):
    def test_override_changes_only_the_non_secret_processing_flag(self) -> None:
        config = load_yaml(OPENCLAW_PAUSED)
        self.assertEqual(
            config,
            {
                "services": {
                    "api": {
                        "environment": {
                            "GRAFANA_WEBHOOK_PROCESSING_ENABLED": "false",
                        }
                    }
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
