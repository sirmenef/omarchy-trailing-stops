#!/usr/bin/env python3
"""Daily roundup: after the US close, a headless Claude researches the day's news for every tracked
ticker and writes a short blog post; Codex fact-checks it, and Claude answers each finding and revises.
If either provider is unavailable the other fills in (at worst one provider reviews its own draft in a
fresh session). This script saves the post and the review notes as markdown + HTML, rebuilds the index
and pushes the headline to the phone with a link to the post.

  roundup.py                 write the post for the latest completed session (skips if it exists)

  ROUNDUP_DATE=YYYY-MM-DD    force the session date (and overwrite); for re-runs and tests
  ROUNDUP_DIR=PATH           where posts go (else config "roundup_dir", else ~/.local/share/trailing-stops/roundups)
  ROUNDUP_PRICES="SYM=PRICE,PREV ..."   use these closes instead of fetching (tests)
  ROUNDUP_CLAUDE_BIN=PATH    use another binary for a provider (tests: a fake that fails)
  ROUNDUP_CODEX_BIN=PATH

The models only get web search and return text; prices come from the tracker, never the web, and the
recent daily closes from the same Google Finance page. If config "roundup_url" says where the folder is
served, the phone push links to the post.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tracker  # noqa: E402

CONFIG = tracker.load_config()
OUT = os.path.expanduser(os.environ.get("ROUNDUP_DIR") or CONFIG.get("roundup_dir")
                         or "~/.local/share/trailing-stops/roundups")
SESSIONS = 10  # two weeks of daily closes before the trading date, for "bounce or rally?"
NY = ZoneInfo("America/New_York")
NAMES = {"dip": "Buy dip", "up": "Buy bounce", "down": "Sell stop"}
PROVIDERS = ("claude", "codex")  # the first writes and the other fact-checks; each fills in for the other
# systemd's PATH lacks mise; ROUNDUP_<NAME>_BIN swaps in a fake for tests.
BIN = {"claude": os.environ.get("ROUNDUP_CLAUDE_BIN") or shutil.which("claude")
                 or os.path.expanduser("~/.local/share/mise/installs/claude/latest/claude"),
       "codex": os.environ.get("ROUNDUP_CODEX_BIN") or shutil.which("codex")
                or os.path.expanduser("~/.local/share/mise/installs/codex/latest/bin/codex")}


def push(url, title, body, tags, click=None):
    """Same ntfy POST as tracker.py's, but normal priority and optionally a link to open on tap."""
    headers = {"Title": title, "Tags": tags}
    if click:
        headers["Click"] = click
    urllib.request.urlopen(urllib.request.Request(url, data=body.encode(), headers=headers), timeout=15).close()


def session_date(now):
    """The NY trading date whose close the tracker's prices describe. None while the market is open."""
    d = now.date()
    if d.weekday() < 5 and time(9, 30) <= now.time() < time(16, 0):
        return None
    if d.weekday() >= 5 or now.time() < time(9, 30):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def snapshot(day):
    """Closing prices and alert states, in the shape the prompt describes."""
    out = subprocess.run([sys.executable, os.path.join(HERE, "tracker.py"), "check",
                          *os.environ.get("ROUNDUP_PRICES", "").split()],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    stocks = []
    for symbol, rule in data["rules"].items():
        item = data["stocks"].get(symbol, {})
        alerts = []
        for key in ("dip", "up", "down"):
            trail = item.get(key)
            if not trail:
                continue
            fired = trail.get("triggered_at")
            fired = datetime.fromisoformat(fired) if fired else None
            alerts.append({
                "alert": NAMES[key], "pct": rule[key], "level": round(trail["level"], 2),
                "status": trail["status"],
                # Bounce/stop stay triggered for days; only today's firing is news.
                "fired_today_at": fired.astimezone().strftime("%H:%M %Z")
                if fired and fired.astimezone(NY).date() == day else None,
                "fired_on": fired.astimezone(NY).date().isoformat() if fired else None,
            })
            if key != "dip":  # the trail's turning point: the bounce rises off it, the stop falls from it
                alerts[-1]["lowest_seen" if key == "up" else "highest_seen"] = round(trail["anchor"], 2)
        price, prev = item.get("price"), item.get("prev_close")
        price = round(price, 2) if price else price  # Google sometimes quotes 3 decimals; posts quote cents
        stock = {
            "symbol": symbol, "close": price, "previous_close": prev,
            "change_pct": round((price - prev) / prev * 100, 2) if price and prev else None,
            "fetch_error": item.get("error"), "alerts": alerts,
        }
        if price and not item.get("error"):
            try:
                stock.update(recent(symbol, day, price))
            except Exception as e:  # the post can go out without it; the prompt says what to do
                stock["recent_error"] = str(e)
        stocks.append(stock)
    return data["settings"], stocks


def recent(symbol, day, close):
    """The SESSIONS daily closes before `day` plus the trading date's close, and the numbers a
    "bounce or rally?" judgement needs, worked out here so the models don't do the arithmetic."""
    rows = [r for r in tracker.fetch_history(symbol) if r[0] < day.isoformat()][-SESSIONS:]
    sessions = [{"date": d, "close": c, "volume": v} for d, c, v in rows]
    sessions.append({"date": day.isoformat(), "close": close, "volume": None})
    low = min(sessions, key=lambda s: s["close"])
    high = max(sessions, key=lambda s: s["close"])
    return {"recent_sessions": sessions, "recent_summary": {
        "sessions": len(sessions),
        "lowest_close": {"date": low["date"], "close": low["close"]},
        "highest_close": {"date": high["date"], "close": high["close"]},
        "close_vs_lowest_pct": round((close - low["close"]) / low["close"] * 100, 2),
        "close_vs_highest_pct": round((close - high["close"]) / high["close"] * 100, 2),
        "change_over_window_pct": round((close - sessions[0]["close"]) / sessions[0]["close"] * 100, 2),
        "average_volume": round(sum(s["volume"] for s in sessions[:-1]) / max(len(sessions) - 1, 1)),
    }}


def run(provider, instructions, message):
    """One headless, tool-limited, sessionless call. Raises if the provider is missing, fails or times out."""
    if provider == "claude":
        r = subprocess.run([BIN["claude"], "-p", "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch",
                            "--setting-sources", "project", "--strict-mcp-config", "--no-session-persistence",
                            "--system-prompt", instructions, message],
                           cwd=OUT, capture_output=True, text=True, timeout=900)
        out = r.stdout
    else:  # codex has no system-prompt flag; its stdout repeats the answer among logs, so read -o
        with tempfile.NamedTemporaryFile("r", suffix=".txt") as last:
            r = subprocess.run([BIN["codex"], "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
                                "-s", "read-only", "-c", "web_search=live", "--color", "never", "-o", last.name, "-"],
                               input=f"{instructions}\n\n---\n\n{message}",
                               cwd=OUT, capture_output=True, text=True, timeout=900)
            out = last.read()
    if r.returncode:
        raise RuntimeError(f"exited {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
    return out.strip()


def attempt(order, role, instructions, message, check, down, log):
    """Try each provider not yet down, in order; the first whose output passes check() does the job.
    A failure marks the provider down for the rest of the run. Returns (provider, checked output)."""
    for provider in order:
        if provider in down:
            continue
        try:
            return provider, check(run(provider, instructions, message))
        except Exception as e:  # missing binary, exit code, timeout, or output that isn't a post/review
            down.add(provider)
            log.append(f"{provider.title()} couldn't {role}: {e}"[:400])
    return None, None


def check_post(stocks):
    def check(text):
        if text == "SKIP":
            return text
        start = text.find("# ")  # drop any chatter before the title
        if start < 0 or "Sources" not in text:  # e.g. a usage-limit message on exit 0
            raise ValueError(f"output isn't a post: {text[:200]!r}")
        text = text[start:]
        for s in stocks:  # the one fact we know for sure
            if s["close"] and not s["fetch_error"] and f"{s['close']:,.2f}" not in text:
                raise ValueError(f"post doesn't quote the tracker's {s['symbol']} close {s['close']:,.2f}")
        return text
    return check


def check_review(text):
    if text == "NO ISSUES":
        return text
    m = re.search(r"^1\. \[", text, re.M)
    if not m:
        raise ValueError(f"output isn't a review: {text[:200]!r}")
    return text[m.start():]


def check_revision(check_text):
    def check(text):
        post, sep, responses = text.partition("===RESPONSES===")
        if not sep or not responses.strip():
            raise ValueError(f"no ===RESPONSES=== section: {text[-200:]!r}")
        return check_text(post.strip()), responses.strip()
    return check


def write_post(day, stocks):
    data = (f"Trading date: {day:%A %d %B %Y} (New York).\n"
            f"Tracker data at the close (the only source for prices):\n{json.dumps(stocks, indent=2)}")
    return reviewed("roundup", data, check_post(stocks), f"{day:%A %d %B %Y}")


def reviewed(kind, data, check, heading):
    """Writer drafts from <kind>-prompt.md, the other provider fact-checks with <kind>-review-prompt.md,
    the writer answers each point and revises. Returns (text or "SKIP", footer credit, review notes
    markdown); text is None if nobody could write (the notes are then the failure log)."""
    with open(os.path.join(HERE, f"{kind}-prompt.md")) as f:
        writer_prompt = f.read()
    with open(os.path.join(HERE, f"{kind}-review-prompt.md")) as f:
        review_prompt = f.read()
    down, log = set(), []

    writer, draft = attempt(PROVIDERS, "write the post", writer_prompt, data, check, down, log)
    if writer is None:
        return None, None, log
    if draft == "SKIP":
        return draft, None, log
    # The other provider checks; if it's down, the writer's provider checks in a fresh, separate session.
    others = [p for p in PROVIDERS if p != writer] + [writer]
    reviewer, review = attempt(others, "fact-check", review_prompt, f"{data}\n\nDraft post:\n\n{draft}",
                               check_review, down, log)
    reviser, post, responses = writer, draft, None
    if review and review != "NO ISSUES":
        reviser, revised = attempt([writer] + others[:-1], "revise", writer_prompt,
                                   f"{data}\n\nYour draft post:\n\n{draft}\n\nA fact-checker's findings:\n\n{review}\n\n"
                                   "Go through every finding. Fix the post where the evidence supports the finding; "
                                   "reject it, with a reason, where it doesn't. Change only what the findings require, "
                                   "and give a source in Sources for anything new. Keep every rule and the structure. "
                                   "Output the full revised post, then a line `===RESPONSES===`, then one line per "
                                   "finding: `N. Accepted: <what you changed>` or `N. Rejected: <why>`.",
                                   check_revision(check), down, log)
        if reviser:
            post, responses = revised
    name = str.title
    if not reviewer:
        credit = f"Written by {name(writer)}. **Not fact-checked:** no reviewer was available."
    elif reviser is None:
        credit = (f"Written by {name(writer)} and fact-checked by {name(reviewer)}, but **the corrections couldn't "
                  "be applied**: see the review notes.")
    else:
        credit = f"Written by {name(writer)}, fact-checked by {name(reviewer)}"
        credit += " (self-review: the other provider was unavailable)" if reviewer == writer else ""
        credit += f", revised by {name(reviser)}." if responses else ". No issues found."
    notes = [f"# Review notes: {heading}", "", credit]
    if log:
        notes += ["", "## What went wrong", ""] + [f"- {line}" for line in log]
    if review:
        notes += ["", f"## Fact-check by {name(reviewer)}", "", review]
    if responses:
        notes += ["", f"## Responses by {name(reviser)}", "", responses, "", "## First draft", ""] + [f"> {line}" for line in draft.splitlines()]
    return post, credit, "\n".join(notes) + "\n"


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>{title}</title>
<style>
:root {{ --bg: #fbfaf7; --fg: #1d1d1b; --dim: #6b6a65; --rule: #e2dfd6; --link: #1f5fbf; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #16171a; --fg: #e8e6e1; --dim: #9a988f; --rule: #2c2e33; --link: #7aaaf0; }} }}
body {{ background: var(--bg); color: var(--fg); font: 17px/1.6 Georgia, "Iowan Old Style", serif;
       max-width: 42rem; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 1.6rem; line-height: 1.25; }}
h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
a {{ color: var(--link); }}
em, nav {{ color: var(--dim); }}
nav {{ font: 14px system-ui, sans-serif; }}
table {{ border-collapse: collapse; width: 100%; font: 14px/1.4 system-ui, sans-serif; display: block; overflow-x: auto; }}
th, td {{ border-bottom: 1px solid var(--rule); padding: 6px 8px; text-align: left; vertical-align: top; }}
hr {{ border: 0; border-top: 1px solid var(--rule); }}
li {{ margin: .3rem 0; }}
</style></head>
<body><nav>{nav}</nav>
{body}
</body></html>
"""


def to_html(text, *extensions):
    # The text is model output built from web pages, served next to the ntfy server: never let it be HTML.
    # Escaping < turns any tag into text (markdown syntax doesn't need it); the page's CSP blocks scripts too.
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    # Python-Markdown only starts a list after a blank line; models write "**Sources:**" then "- ..." directly.
    text = re.sub(r"(?m)^((?:> )?)(?![ \t]*(?:[-*] |\d+\. )).*\S.*\n(?=\1(?:[-*] |\d+\. ))", r"\g<0>\1\n", text)
    out = markdown.markdown(text, extensions=["tables", *extensions])
    return re.sub(r'(href|src)="(?!https?://)[^"]*:[^"]*"', r'\1="#"', out)  # only web links and relative paths


def render(path, title, body, nav):
    with open(path, "w") as f:
        f.write(PAGE.format(title=html.escape(title), body=body, nav=nav))


def rebuild_index():
    posts = []
    for name in sorted(os.listdir(OUT), reverse=True):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name):
            with open(os.path.join(OUT, name)) as f:
                title = f.readline().lstrip("# ").strip()
            posts.append(f'<li><a href="{name[:-3]}.html">{html.escape(title)}</a> '
                         f'<em>{datetime.strptime(name[:10], "%Y-%m-%d"):%a %d %b %Y}</em></li>')
    render(os.path.join(OUT, "index.html"), "Share roundups",
           "<h1>Share roundups</h1>\n<ul>\n" + "\n".join(posts) + "\n</ul>", "")


def main():
    forced = os.environ.get("ROUNDUP_DATE")
    day = date.fromisoformat(forced) if forced else session_date(datetime.now(NY))
    if day is None:
        sys.exit("the US market is open; the roundup runs after the 16:00 New York close")
    md_path = os.path.join(OUT, f"{day}.md")
    if os.path.exists(md_path) and not forced:
        print(f"{md_path} already written")
        return
    os.makedirs(OUT, exist_ok=True)
    settings, stocks = snapshot(day)
    push_url = settings["push_url"]
    base = CONFIG.get("roundup_url") or ""  # where OUT is served, if anywhere; a phone can't open a local file
    base += "" if not base or base.endswith("/") else "/"

    text, credit, notes = write_post(day, stocks)
    if text is None:
        print("roundup failed:\n" + "\n".join(notes), file=sys.stderr)
        if push_url:
            push(push_url, "Daily roundup failed", "\n".join(notes)[:300], "warning")
        sys.exit(1)
    if text == "SKIP":
        print(f"{day}: US market closed, no post")
        return

    text += f"\n\n---\n\n*{credit} [Review notes]({day}.review.html)*\n"
    title = text.splitlines()[0].lstrip("# ").strip()
    with open(md_path, "w") as f:
        f.write(text)
    with open(os.path.join(OUT, f"{day}.review.md"), "w") as f:
        f.write(notes)
    nav = '<a href="./">← all roundups</a>'
    render(os.path.join(OUT, f"{day}.html"), title, to_html(text), nav)
    # nl2br keeps each finding's Problem/Evidence/Fix lines apart; posts don't get it (wrapped prose).
    render(os.path.join(OUT, f"{day}.review.html"), f"Review notes {day}", to_html(notes, "nl2br"),
           f'{nav} · <a href="{day}.html">the post</a>')
    rebuild_index()
    print(f"wrote {md_path}")
    if push_url:
        moves = " · ".join(f"{s['symbol']} {s['close']:,.2f} ({s['change_pct']:+.1f}%)"
                           for s in stocks if s["change_pct"] is not None)
        push(push_url, title, moves + ("\nTap to read the roundup." if base else ""), "newspaper",
             base + f"{day}.html" if base else None)


if __name__ == "__main__":
    main()
