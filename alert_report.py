#!/usr/bin/env python3
"""Follow-up to a Buy dip or Buy bounce alert: why is it falling, or is the bounce a real turn? tracker.py
starts this in the background when one fires and config "alert_analysis" is true. It uses the roundup's
write → fact-check → revise loop with alert-prompt.md / alert-review-prompt.md, pushes the note to the
phone, and saves the full article with its review notes in <roundup dir>/alerts/, listed on the roundups
index. The push carries the article's summary and opens the article if "roundup_url" is set, else the
share's Google Finance page.

  alert_report.py '{"symbol": "MU", "direction": "up", "price": 885.0, "prev_close": 914.13,
                    "pct": 3.0, "level": 880.65, "anchor": 855.0, "triggered_at": "..."}'

Takes the same ROUNDUP_DIR / ROUNDUP_*_BIN overrides as roundup.py.
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roundup  # noqa: E402
import tracker  # noqa: E402

KIND = {"dip": "dip", "up": "bounce"}


def why_fired(a, at):
    """Written from the alert itself, not by the model: these numbers are known, so nothing to check."""
    pct, level, price = a["pct"], a["level"], a["price"]
    day_move = f"{(price / a['prev_close'] - 1) * 100:+.1f}% on the previous close of {a['prev_close']:,.2f}"
    if a["direction"] == "dip":
        rule = f"**Buy dip** fires {pct:g}% below the previous close: at {level:,.2f}."
        hit = f"At {at:%H:%M} New York time the price was {price:,.2f}, {day_move}."
    else:
        rule = (f"**Buy bounce** fires {pct:g}% above the lowest price the tracker saw since the alert started "
                f"({a['anchor']:,.2f}): at {level:,.2f}.")
        hit = (f"At {at:%H:%M} New York time the price was {price:,.2f}, "
               f"{(price / a['anchor'] - 1) * 100:+.1f}% off that low and {day_move}.")
    return f"## Why the alert fired\n\n{rule} {hit}\n"


def check_article(check):
    def wrapped(text):
        text = check(text)
        if "\n## " not in text:
            raise ValueError("article has no ## sections")
        return text
    return wrapped


def main():
    alert = json.loads(sys.argv[1])
    symbol, kind, price = alert["symbol"], KIND[alert["direction"]], alert["price"]
    at = datetime.fromisoformat(alert["triggered_at"]).astimezone(roundup.NY)
    day = at.date()
    data = {"alert": roundup.NAMES[alert["direction"]], **alert}
    try:
        data.update(roundup.recent(symbol, day, price))
    except Exception as e:  # the note can go out without it; the prompt says what to do
        data["recent_error"] = str(e)
    root = roundup.OUT
    out = os.path.join(root, "alerts")
    os.makedirs(out, exist_ok=True)
    roundup.OUT = out  # the providers run in here

    text, credit, notes = roundup.reviewed(
        "alert", f"Alert data (the only source for prices):\n{json.dumps(data, indent=2)}",
        check_article(roundup.check_post([{"symbol": symbol, "close": price, "fetch_error": None}])),
        f"{symbol} {kind}, {day:%A %d %B %Y}")
    push_url = roundup.CONFIG["push_url"]
    if text is None:
        print(f"{symbol} {kind} analysis failed:\n" + "\n".join(notes), file=sys.stderr)
        if push_url:
            roundup.push(push_url, f"{symbol} {kind} analysis failed", "\n".join(notes)[:300], "warning")
        sys.exit(1)

    name = f"{day}-{at:%H%M}-{symbol.replace(':', '-')}-{kind}"  # the time: a re-fired alert keeps its own page
    summary, sections = text.split("\n## ", 1)
    text = f"{summary.rstrip()}\n\n{why_fired(alert, at)}\n## {sections}"
    text += f"\n\n---\n\n*{credit} [Review notes]({name}.review.html)*\n"
    with open(os.path.join(out, f"{name}.md"), "w") as f:
        f.write(text)
    with open(os.path.join(out, f"{name}.review.md"), "w") as f:
        f.write(notes)
    title = text.splitlines()[0].lstrip("# ").strip()
    nav = '<a href="./">← all analyses</a>'
    roundup.render(os.path.join(out, f"{name}.html"), title, roundup.to_html(text), nav)
    roundup.render(os.path.join(out, f"{name}.review.html"), f"Review notes: {title}",
                   roundup.to_html(notes, "nl2br"), f'{nav} · <a href="{name}.html">the article</a>')
    roundup.rebuild_index(root)
    print(f"wrote {os.path.join(out, name)}.md")

    if push_url:
        # The phone shows plain text: just the summary above the sections, without the title (it's the
        # push title) or markdown bold. The article has the rest.
        base = roundup.CONFIG.get("roundup_url") or ""
        base += "" if not base or base.endswith("/") else "/"
        body = summary.split("\n", 1)[1].replace("**", "").strip()
        body += "\n\n" + ("Tap for the full analysis. " if base else "") + credit.replace("**", "")
        roundup.push(push_url, title, body[:3500], "mag",
                     f"{base}alerts/{name}.html" if base else tracker.quote_url(symbol)[2])


if __name__ == "__main__":
    main()
