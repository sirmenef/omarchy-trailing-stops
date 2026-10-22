#!/usr/bin/env python3
"""Research tracked shares before the US open; save under <roundup_dir>/premarket.

Uses the existing roundup providers, review loop and phone delivery. Reads subscriptions
without running tracker.check or changing alert state. Pending jobs survive restarts.
"""
import fcntl
import json
import os
import tempfile
from datetime import date, datetime, time, timedelta

import roundup


def due_day(now):
    """Latest weekday whose 08:30 New York schedule has elapsed."""
    day = now.date()
    if now.time() < time(8, 30):
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def atomic_write(path, text):
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def check_report(symbols):
    def check(text):
        if text.strip() == "SKIP":
            return "SKIP"
        start = text.find("# ")
        if start < 0:
            raise ValueError("premarket report has no title")
        text = text[start:].strip()
        for heading in ["## Market context", "## Asian markets", "## European markets",
                        *(f"## {s}" for s in symbols), "## What to watch at the open",
                        "## Sources", "## Data limitations"]:
            if heading not in text.splitlines():
                raise ValueError(f"premarket report missing {heading}")
        if "https://" not in text:
            raise ValueError("premarket report has no source links")
        return text
    return check


def deliver(out, day, text):
    """A failed push leaves the saved article available for a delivery retry."""
    marker = os.path.join(out, f"{day}.sent")
    if os.path.exists(marker):
        return
    if not roundup.CONFIG.get("push_url"):
        atomic_write(marker, "saved locally; phone delivery not configured\n")
        return
    base = (roundup.CONFIG.get("roundup_url") or "").rstrip("/")
    title, _, body = text.partition("\n")
    summary = body.split("\n## ", 1)[0].strip().replace("**", "")
    if datetime.now(roundup.NY) >= datetime.combine(date.fromisoformat(str(day)), time(9, 30), roundup.NY):
        if "DELAYED" not in title:
            title = "# DELAYED — " + title.lstrip("# ")
    roundup.push(roundup.CONFIG["push_url"], title.lstrip("# ").replace("—", "-"), summary[:800], "newspaper",
                 f"{base}/premarket/{day}.html" if base else None)
    atomic_write(marker, datetime.now(roundup.NY).isoformat() + "\n")


def main():
    symbols = list(roundup.CONFIG["symbols"])
    if not symbols:
        print("no subscribed shares; skipped")
        return
    root = roundup.OUT
    out = os.path.join(root, "premarket")
    os.makedirs(out, exist_ok=True)
    pending = os.path.join(out, ".pending.json")
    with open(os.path.join(out, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = datetime.now(roundup.NY)
        if os.path.exists(pending):
            with open(pending) as f:
                day = date.fromisoformat(json.load(f)["day"])
        else:
            day = due_day(now)
            if any(os.path.exists(os.path.join(out, f"{day}.{suffix}")) for suffix in ("sent", "skipped")):
                print(f"{day}: already complete")
                return
            atomic_write(pending, json.dumps({"day": day.isoformat()}))
        path = os.path.join(out, f"{day}.md")
        if os.path.exists(path):
            roundup.rebuild_index(root)
            with open(path) as f:
                deliver(out, day, f.read())
            os.unlink(pending)
            print(f"{path} already written; delivery complete")
            return
        cutoff = min(now, datetime.combine(day, time(9, 29, 59), roundup.NY))
        data = json.dumps({"session_date": day.isoformat(), "research_started_at": now.isoformat(),
                           "information_cutoff": cutoff.isoformat(), "subscribed_symbols": symbols}, indent=2)
        # Keep roundup.OUT stable so recovery is also safe in repeated in-process runs.
        try:
            roundup.OUT = out
            text, credit, notes = roundup.reviewed("premarket", data, check_report(symbols),
                                                   f"Premarket {day}")
        finally:
            roundup.OUT = root
        if text is None:
            raise RuntimeError("premarket research failed: " + "\n".join(notes))
        if text == "SKIP":
            atomic_write(os.path.join(out, f"{day}.skipped"), "US market holiday\n")
            os.unlink(pending)
            print(f"{day}: research reports US market holiday; skipped")
            return
        finished = datetime.now(roundup.NY)
        if finished >= datetime.combine(day, time(9, 30), roundup.NY):
            title, _, body = text.partition("\n")
            text = (f"# DELAYED — {title.lstrip('# ')}\n\n"
                    f"> Delayed report for {day}; prepared {finished:%Y-%m-%d %H:%M %Z}. "
                    f"Information cutoff: {cutoff:%Y-%m-%d %H:%M:%S %Z}. "
                    "This is not a live premarket snapshot.\n" + body)
        text += (f"\n\n---\n\nResearch started {now:%Y-%m-%d %H:%M %Z}; "
                 f"completed {finished:%Y-%m-%d %H:%M %Z}. "
                 "Quotes may be delayed; see each source's observation time.\n\n"
                 f"*{credit} [Review notes]({day}.review.html)*\n")
        title = text.splitlines()[0].lstrip("# ")
        atomic_write(os.path.join(out, f"{day}.review.md"), notes)
        nav = '<a href="./">← premarket reports</a>'
        roundup.render(os.path.join(out, f"{day}.html"), title, roundup.to_html(text), nav)
        roundup.render(os.path.join(out, f"{day}.review.html"), f"Review notes: {title}",
                       roundup.to_html(notes, "nl2br"), f'{nav} · <a href="{day}.html">the report</a>')
        # Atomic Markdown marks completion only after both HTML pages exist.
        atomic_write(path, text)
        roundup.rebuild_index(root)
        deliver(out, day, text)
        os.unlink(pending)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
