import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

# Isolate imports too: roundup loads tracker config at import time.
fixture = tempfile.TemporaryDirectory()
config = Path(fixture.name) / "config.json"
config.write_text(json.dumps({"symbols": {"MU": {}}, "push_url": ""}))
with patch.dict(os.environ, {"TRAILING_STOPS_CONFIG": str(config)}):
    import premarket


class PremarketTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.settings = {"symbols": {"MU": {}, "SNDK": {}}, "push_url": "https://push.invalid/topic",
                         "roundup_url": "https://reports.invalid/roundups/"}
        self.now = datetime(2026, 10, 19, 8, 30, tzinfo=premarket.roundup.NY)
        self.clock = patch.object(premarket, "datetime").start()
        self.clock.now.return_value = self.now
        self.clock.combine.side_effect = datetime.combine
        self.addCleanup(patch.stopall)
        patch.object(premarket.roundup, "CONFIG", self.settings).start()
        patch.object(premarket.roundup, "OUT", str(self.root)).start()
        self.push = patch.object(premarket.roundup, "push").start()
        self.article = ("# Premarket briefing — 2026-10-19\n\nNo verified activity figures.\n\n"
                        "## Market context\nUnavailable.\n\n"
                        "## Asian markets\nUnavailable.\n\n"
                        "## European markets\nUnavailable.\n\n"
                        "## MU\nUnavailable.\n\n## SNDK\nUnavailable.\n\n"
                        "## What to watch at the open\nUnavailable.\n\n"
                        "## Data limitations\nRegional snapshots unavailable.\n\n"
                        "## Sources\n[Calendar](https://www.nyse.com/markets/hours-calendars)\n")
        self.research = patch.object(premarket.roundup, "reviewed",
                                    return_value=(self.article, "Reviewed", "NO ISSUES")).start()

    def test_due_day_before_schedule_and_weekend(self):
        self.assertEqual(premarket.due_day(self.now.replace(hour=8, minute=29)), date(2026, 10, 16))
        self.assertEqual(premarket.due_day(self.now), date(2026, 10, 19))
        self.assertEqual(premarket.due_day(self.now.replace(day=18)), date(2026, 10, 16))

    def test_complete_report_links_and_single_delivery(self):
        premarket.main()
        out = self.root / "premarket"
        for suffix in ["md", "html", "review.md", "review.html", "sent"]:
            self.assertTrue((out / f"2026-10-19.{suffix}").exists())
        self.assertIn('premarket/2026-10-19.html', (self.root / "index.html").read_text())
        self.assertIn('2026-10-19.html', (out / "index.html").read_text())
        self.assertEqual(self.push.call_args.args[-1],
                         "https://reports.invalid/roundups/premarket/2026-10-19.html")
        premarket.main()
        self.assertEqual(self.research.call_count, 1)
        self.assertEqual(self.push.call_count, 1)
        data = json.loads(self.research.call_args.args[1])
        self.assertEqual(data["subscribed_symbols"], ["MU", "SNDK"])

    def test_failed_push_retries_saved_report(self):
        self.push.side_effect = OSError("network unavailable")
        with self.assertRaises(OSError):
            premarket.main()
        self.assertFalse((self.root / "premarket/2026-10-19.sent").exists())
        self.push.side_effect = None
        premarket.main()
        self.assertEqual(self.research.call_count, 1)
        self.assertTrue((self.root / "premarket/2026-10-19.sent").exists())

    def test_closed_market_does_not_publish(self):
        self.research.return_value = ("SKIP", None, "")
        premarket.main()
        self.assertFalse((self.root / "premarket/2026-10-19.md").exists())
        self.push.assert_not_called()

    def test_publication_after_open_is_labelled_late(self):
        self.clock.now.side_effect = [self.now, self.now.replace(hour=9, minute=30),
                                     self.now.replace(hour=9, minute=30), self.now.replace(hour=9, minute=30)]
        premarket.main()
        text = (self.root / "premarket/2026-10-19.md").read_text()
        self.assertTrue(text.startswith("# DELAYED"))
        self.push.assert_called_once()

    def test_restart_after_midnight_keeps_pending_date(self):
        self.research.return_value = (None, None, ["offline"])
        with self.assertRaises(RuntimeError):
            premarket.main()
        pending = self.root / "premarket/.pending.json"
        self.assertEqual(json.loads(pending.read_text())["day"], "2026-10-19")
        self.clock.now.return_value = self.now.replace(day=20, hour=7)
        self.research.return_value = (self.article, "Reviewed", "NO ISSUES")
        premarket.main()
        self.assertFalse(pending.exists())
        self.assertTrue((self.root / "premarket/2026-10-19.sent").exists())
        data = json.loads(self.research.call_args.args[1])
        self.assertEqual(data["information_cutoff"], "2026-10-19T09:29:59-04:00")
        self.assertEqual(data["session_date"], "2026-10-19")

    def test_empty_subscriptions_does_no_research(self):
        self.settings["symbols"] = {}
        premarket.main()
        self.research.assert_not_called()

    def test_holiday_is_not_researched_again(self):
        self.research.return_value = ("SKIP", None, "")
        premarket.main()
        premarket.main()
        self.research.assert_called_once()
        self.assertTrue((self.root / "premarket/2026-10-19.skipped").exists())

    def test_local_only_report_is_not_researched_again(self):
        self.settings["push_url"] = ""
        premarket.main()
        premarket.main()
        self.research.assert_called_once()
        self.push.assert_not_called()

    def test_interrupted_atomic_save_preserves_previous_content(self):
        path = self.root / "pending.json"
        path.write_text("previous")
        with patch.object(premarket.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                premarket.atomic_write(str(path), "new")
        self.assertEqual(path.read_text(), "previous")
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_killed_process_keeps_job_for_next_process(self):
        module_dir = str(Path(premarket.__file__).parent)
        env = dict(os.environ, TRAILING_STOPS_CONFIG=str(config), ROUNDUP_DIR=str(self.root),
                   PYTHONDONTWRITEBYTECODE="1")
        crash = ("import os,premarket; "
                 "premarket.roundup.reviewed=lambda *a: os._exit(143); premarket.main()")
        result = subprocess.run([sys.executable, "-c", crash], cwd=module_dir, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 143, result.stderr)
        pending = self.root / "premarket/.pending.json"
        saved_day = json.loads(pending.read_text())["day"]
        recovery = ("import premarket; "
                    "premarket.roundup.reviewed=lambda *a: ('# Recovery\\n\\n## MU\\nUnavailable.\\n\\n"
                    "## Data limitations\\nUnavailable.\\n\\n## Sources\\nhttps://www.nyse.com',"
                    "'Reviewed','NO ISSUES'); premarket.main()")
        result = subprocess.run([sys.executable, "-c", recovery], cwd=module_dir, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(pending.exists())
        self.assertTrue((self.root / f"premarket/{saved_day}.sent").exists())

    def test_validation_requires_regions_subscriptions_and_limitations(self):
        check = premarket.check_report(["MU", "SNDK"])
        self.assertEqual(check(self.article), self.article.strip())
        self.assertEqual(check("SKIP"), "SKIP")
        for heading in ["## Market context", "## Asian markets", "## European markets",
                        "## MU", "## SNDK", "## What to watch at the open",
                        "## Data limitations", "## Sources"]:
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                check(self.article.replace(heading, "## Other"))
        with self.assertRaises(ValueError):
            check("usage limit")

    def test_provider_failure_leaves_no_completed_report(self):
        self.research.return_value = (None, None, ["both unavailable"])
        with self.assertRaisesRegex(RuntimeError, "both unavailable"):
            premarket.main()
        self.push.assert_not_called()
        self.assertFalse((self.root / "premarket/2026-10-19.md").exists())


if __name__ == "__main__":
    unittest.main()
