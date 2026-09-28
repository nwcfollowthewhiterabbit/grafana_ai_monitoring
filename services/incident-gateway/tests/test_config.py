from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import ConfigError, Settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_telegram_thread_id_can_be_read_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "telegram-thread-id"
            secret_path.write_text(" 42\n", encoding="utf-8")
            environment = {
                "TELEGRAM_MESSAGE_THREAD_ID_FILE": str(secret_path),
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = Settings.from_env()

        self.assertEqual(settings.telegram_message_thread_id, 42)

    def test_telegram_thread_id_rejects_value_and_file_together(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_MESSAGE_THREAD_ID": "42",
                "TELEGRAM_MESSAGE_THREAD_ID_FILE": "/run/secrets/telegram-thread-id",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ConfigError, "set only one"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
