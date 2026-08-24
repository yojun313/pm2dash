import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.services.ai_usage_service import AIUsageService


class AIUsageServiceTests(unittest.TestCase):
    def setUp(self):
        AIUsageService._cache.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.claude_root = self.root / "claude"
        self.codex_root = self.root / "codex"

    def tearDown(self):
        self.temp_dir.cleanup()
        AIUsageService._cache.clear()

    def _write_jsonl(self, path: Path, records: list[dict]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(json.dumps(record) for record in records),
            encoding="utf-8",
        )

    def _get_usage(self):
        with patch.dict(
            os.environ,
            {
                "CLAUDE_DATA_DIR": str(self.claude_root),
                "CODEX_DATA_DIR": str(self.codex_root),
            },
            clear=False,
        ):
            return AIUsageService.get_usage(days=7)

    def test_collects_claude_message_usage(self):
        (self.claude_root / ".credentials.json").parent.mkdir(parents=True)
        (self.claude_root / ".credentials.json").write_text("{}", encoding="utf-8")
        timestamp = datetime.now(timezone.utc).isoformat()
        self._write_jsonl(
            self.claude_root / "projects" / "project-a" / "session.jsonl",
            [
                {
                    "timestamp": timestamp,
                    "sessionId": "claude-session",
                    "message": {
                        "role": "assistant",
                        "model": "claude-test",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 20,
                            "cache_creation_input_tokens": 10,
                            "cache_read_input_tokens": 5,
                        },
                    },
                }
            ],
        )

        claude = self._get_usage()["providers"][0]

        self.assertTrue(claude["connected"])
        self.assertTrue(claude["has_data"])
        self.assertEqual(claude["total_tokens"], 135)
        self.assertEqual(claude["cache_tokens"], 15)
        self.assertEqual(claude["sessions"], 1)
        self.assertEqual(claude["model"], "claude-test")

    def test_codex_uses_cumulative_token_deltas(self):
        self.codex_root.mkdir(parents=True)
        (self.codex_root / "auth.json").write_text("{}", encoding="utf-8")
        timestamp = datetime.now(timezone.utc).isoformat()
        self._write_jsonl(
            self.codex_root / "sessions" / "2026" / "session.jsonl",
            [
                {"timestamp": timestamp, "type": "session_meta", "payload": {"id": "codex-session"}},
                {"timestamp": timestamp, "type": "turn_context", "payload": {"model": "gpt-test"}},
                {
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 100,
                                "output_tokens": 20,
                                "cached_input_tokens": 40,
                                "total_tokens": 120,
                            }
                        },
                    },
                },
                {
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 180,
                                "output_tokens": 40,
                                "cached_input_tokens": 70,
                                "total_tokens": 220,
                            }
                        },
                    },
                },
            ],
        )

        codex = self._get_usage()["providers"][1]

        self.assertTrue(codex["connected"])
        self.assertTrue(codex["has_data"])
        self.assertEqual(codex["total_tokens"], 220)
        self.assertEqual(codex["input_tokens"], 180)
        self.assertEqual(codex["output_tokens"], 40)
        self.assertEqual(codex["cache_tokens"], 70)
        self.assertEqual(codex["sessions"], 1)
        self.assertEqual(codex["model"], "gpt-test")


if __name__ == "__main__":
    unittest.main()
