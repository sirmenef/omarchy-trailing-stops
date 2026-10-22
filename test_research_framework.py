"""Exercise prompt delivery and daily opening-report handoff without live providers."""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

fixture = tempfile.TemporaryDirectory()
config = Path(fixture.name) / "config.json"
config.write_text(json.dumps({"symbols": {"MU": {}}, "push_url": ""}))
with patch.dict(os.environ, {"TRAILING_STOPS_CONFIG": str(config)}):
    import roundup


class ResearchFrameworkTests(unittest.TestCase):
    def test_all_report_types_deliver_framework_to_writer_and_reviewer(self):
        framework = (Path(roundup.HERE) / "market-savant-research.md").read_text()
        for kind in ("premarket", "roundup", "alert"):
            with self.subTest(kind=kind), patch.object(
                    roundup, "run", side_effect=["# Draft", "NO ISSUES"]) as run:
                post, credit, _ = roundup.reviewed(kind, "session evidence", lambda x: x, "Test")
                self.assertEqual(post, "# Draft")
                self.assertIn("fact-checked by Codex", credit)
                self.assertEqual(run.call_count, 2)
                for call in run.call_args_list:
                    self.assertTrue(call.args[1].endswith(framework))
                    self.assertIn("session evidence", call.args[2])

    def test_revisions_keep_framework_and_original_cutoff_evidence(self):
        framework = (Path(roundup.HERE) / "market-savant-research.md").read_text()
        data = '{"information_cutoff": "2026-10-22T08:30:00-04:00"}'
        findings = "1. [major] Problem: unsupported outlook. Evidence: input. Fix: mark unknown."
        for kind in ("premarket", "roundup", "alert"):
            with self.subTest(kind=kind), patch.object(roundup, "run", side_effect=[
                    "# Draft", findings,
                    "# Revised\n===RESPONSES===\n1. Accepted: marked unknown."]) as run:
                post, _, notes = roundup.reviewed(kind, data, lambda x: x, "Test")
                self.assertEqual(post, "# Revised")
                self.assertIn("Accepted: marked unknown", notes)
                self.assertEqual(run.call_count, 3)
                for call in run.call_args_list:
                    self.assertTrue(call.args[1].endswith(framework))
                    self.assertIn(data, call.args[2])

    def test_provider_fallback_also_receives_framework(self):
        framework = (Path(roundup.HERE) / "market-savant-research.md").read_text()
        with patch.object(roundup, "run", side_effect=[
                OSError("claude unavailable"), "# Draft", "NO ISSUES"]) as run:
            post, credit, _ = roundup.reviewed("roundup", "evidence", lambda x: x, "Test")
        self.assertEqual(post, "# Draft")
        self.assertIn("self-review", credit)
        for call in run.call_args_list:
            self.assertTrue(call.args[1].endswith(framework))

    def test_daily_handoff_uses_only_matching_session_and_keeps_tracker_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "premarket").mkdir()
            (root / "premarket/2026-10-21.md").write_text("WRONG SESSION")
            (root / "premarket/2026-10-22.md").write_text("# Opening\nA conditional outlook.")
            stocks = [{"symbol": "MU", "close": 100.0, "fetch_error": None}]
            with patch.object(roundup, "OUT", folder), patch.object(roundup, "reviewed") as research:
                roundup.write_post(date(2026, 10, 22), stocks)
            kind, data, check, _ = research.call_args.args
            self.assertEqual(kind, "roundup")
            self.assertIn('"close": 100.0', data)
            self.assertIn("# Opening\nA conditional outlook.", data)
            self.assertIn("untrusted model commentary", data)
            self.assertNotIn("WRONG SESSION", data)
            self.assertEqual(check("# Close 100.00\nSources:"), "# Close 100.00\nSources:")
            with self.assertRaises(ValueError):
                check("# Close 99.00\nSources:")

    def test_daily_without_matching_opening_report_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "premarket").mkdir()
            (root / "premarket/2026-10-21.md").write_text("WRONG SESSION")
            with patch.object(roundup, "OUT", folder), patch.object(roundup, "reviewed") as research:
                roundup.write_post(date(2026, 10, 22), [])
            data = research.call_args.args[1]
            self.assertIn("No saved opening briefing for this session was supplied.", data)
            self.assertNotIn("WRONG SESSION", data)


if __name__ == "__main__":
    unittest.main()
