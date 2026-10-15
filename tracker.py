#!/usr/bin/env python3
"""Trailing-stop watcher, generalising TrailingAlerts' WatchlistItem.UpdatePrice to both directions.
Each symbol can run any of three alerts, each with its own %. Each starts at the previous day's close:

  down  (stop)    anchor = highest price seen (only ratchets up),   level = anchor * (1 - pct/100), alert when price <= level
  up    (bounce)  anchor = lowest price seen  (only ratchets down), level = anchor * (1 + pct/100), alert when price >= level
  dip   (buy)     anchor = previous close (moves each day),         level = anchor * (1 - pct/100), alert when price <= level

A hit flips that alert to triggered and alerts the desktop and (if push_url is set) the phone, via an
ntfy server: the ntfy app subscribes to the same URL. Up/down stay triggered until reset; a dip
re-arms by itself once the previous close changes (the next trading day).

  tracker.py check [SYM=PRICE[,PREV] ...]   fetch prices from Google Finance (or use the given ones), update, notify
  tracker.py show                           print settings, rules and state as JSON (no network)
  tracker.py set SYM UP DOWN DIP            add a symbol or change its rule; each a % or "off"
  tracker.py remove SYM
  tracker.py reset SYM                      restart SYM's bounce and stop from the previous close
  tracker.py interval MIN                   how often Service.qml runs check
  tracker.py push URL                       phone alerts to this ntfy topic URL ("" turns them off)
  tracker.py test                           send a test push to the phone
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

CONFIG = os.environ.get("TRAILING_STOPS_CONFIG") or os.path.expanduser("~/.config/omarchy/trailing-stops.json")
STATE = os.environ.get("TRAILING_STOPS_STATE") or os.path.expanduser("~/.local/state/trailing-stops/state.json")
DEFAULT_CONFIG = {"interval_min": 5, "push_url": "",
                  "symbols": {"SNDK": {"up": 2.5}, "MU": {"up": 2.5}}}
DIRS = ("up", "down", "dip")  # also the argument order of `set`
SYMBOL = re.compile(r"^[A-Z0-9.\-]{1,12}(:[A-Z]{1,10})?$")


def load_config():
    if not os.path.exists(CONFIG):
        save_json(CONFIG, DEFAULT_CONFIG)
    with open(CONFIG) as f:
        return json.load(f)


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_json(path, data):
    # Bar widgets read these on a timer; replace atomically so they never see half a file.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def quote_url(symbol):
    """Symbols are "SYM" (NASDAQ assumed) or "SYM:EXCHANGE"."""
    ticker, exchange = (symbol.split(":", 1) + ["NASDAQ"])[:2]
    return ticker, exchange, f"https://www.google.com/finance/quote/{ticker}:{exchange}"


def fetch_page(symbol):
    ticker, exchange, url = quote_url(symbol)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return ticker, exchange, r.read().decode("utf-8", "replace")


def fetch_history(symbol):
    """The last month of daily closes as [(YYYY-MM-DD, close, volume)], oldest first, from the same page.
    The daily series is the block ["MU","NASDAQ"],"/m/…","USD",[[[1],[ rows ]]] (intraday ones start
    [[[1,[date…), each row [[y,m,d,hour,…],[close,change,pct,…],volume]."""
    ticker, exchange, html = fetch_page(symbol)
    block = re.search(rf'\["{re.escape(ticker)}","{re.escape(exchange)}"\],"[^"]*","[A-Z]+",\[\[\[1\],(\[.*?\])\]\]', html)
    if not block:
        raise ValueError("price history not found on Google Finance page")
    return [(f"{int(y):04d}-{int(m):02d}-{int(d):02d}", float(close), int(volume)) for y, m, d, close, volume
            in re.findall(r'\[\[(\d{4}),(\d+),(\d+),[^\]]*\]\],\[([0-9.]+),[^\]]*\],(\d+)\]', block.group(1))]


def fetch_price(symbol):
    """Returns (price, previous close), scraped from Google Finance. The quote page embeds
    ["SNDK","NASDAQ"],"SanDisk Corp",0,"USD",[price, change, pct, ...],null,prev_close."""
    ticker, exchange, html = fetch_page(symbol)
    m = re.search(rf'\["{re.escape(ticker)}","{re.escape(exchange)}"\],"[^"]*",\d+,"[A-Z]+",'
                  rf'\[([0-9.]+),[^\]]*\],null,([0-9.]+)', html)
    if not m:
        raise ValueError("price not found on Google Finance page")
    return float(m.group(1)), float(m.group(2))


def push(url, title, body, tags, click=None):
    """Phone alert: an ntfy server turns this POST into a push for every app subscribed to url.
    click: a link the phone opens when the notification is tapped."""
    headers = {"Title": title, "Priority": "urgent", "Tags": tags}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(url, data=body.encode(), headers=headers)
    urllib.request.urlopen(req, timeout=15).close()


LABELS = {"dip": "Buy dip", "up": "Buy bounce", "down": "Trailing stop loss"}  # leads every alert title


def notify(symbol, direction, trail, price, push_url):
    if direction == "dip":
        title = f"{symbol} is down {trail['pct']:g}% today"
        body = f"Price {price:.2f} ≤ {trail['level']:.2f}\nPrevious close {trail['anchor']:.2f}"
    elif direction == "down":
        title = f"{symbol} fell {trail['pct']:g}% from its high"
        body = f"Price {price:.2f} ≤ stop {trail['level']:.2f}\nHigh {trail['anchor']:.2f}"
    else:
        title = f"{symbol} rose {trail['pct']:g}% off its low"
        body = f"Price {price:.2f} ≥ trigger {trail['level']:.2f}\nLow {trail['anchor']:.2f}"
    title = f"{LABELS[direction]} · {title}"
    url = quote_url(symbol)[2]  # a click/tap on either alert opens the share's Google Finance page
    # No -a: Omarchy only lets critical alerts through Do Not Disturb when app_name is "notify-send".
    # omarchy-exec-argv is the Omarchy shell's click action (stays clickable after a shell restart).
    subprocess.run(["notify-send", "-u", "critical",
                    "-h", "string:omarchy-exec-argv:" + json.dumps(["xdg-open", url]), title, body], check=False)
    if push_url:
        try:
            push(push_url, title, body, "chart_with_upwards_trend" if direction == "up" else "chart_with_downwards_trend",
                 url)
        except Exception as e:
            print(f"phone push failed: {e}", file=sys.stderr)  # the desktop alert above still went out


def analyse(symbol, direction, trail, price, prev):
    """Buy dip / bounce follow-up: alert_report.py researches why and pushes a fact-checked note, which
    takes minutes. Detached, with its own log instead of our stdout, so this check returns at once
    (Service.qml waits for our stdout to close before the next check)."""
    alert = {"symbol": symbol, "direction": direction, "price": round(price, 2), "prev_close": prev, "pct": trail["pct"],
             "level": round(trail["level"], 2), "anchor": trail["anchor"], "triggered_at": trail["triggered_at"]}
    with open(os.path.join(os.path.dirname(STATE), "alert-analysis.log"), "a") as log:
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_report.py"),
                          json.dumps(alert)], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def update(trail, direction, price, prev, pct):
    """WatchlistItem.UpdatePrice for one trail. Returns True on the transition to triggered."""
    sign = 1 if direction == "up" else -1
    trail["pct"] = pct
    if direction == "dip":
        if trail["anchor"] != prev:  # a new trading day: measure from the new close, armed again
            trail.update(anchor=prev, status="active")
            trail.pop("triggered_at", None)
    elif trail["status"] == "active" and (price - trail["anchor"]) * sign < 0:
        trail["anchor"] = price  # new high (down) or new low (up)
    # Recomputed every time so a changed % applies to the existing anchor.
    trail["level"] = trail["anchor"] * (1 + sign * pct / 100)
    if trail["status"] == "active" and (price - trail["level"]) * sign >= 0:
        trail["status"] = "triggered"
        trail["triggered_at"] = datetime.now(timezone.utc).isoformat()
        return True
    return False


def check(state, config, overrides):
    now = datetime.now(timezone.utc).isoformat()
    for symbol, rule in config["symbols"].items():
        try:
            price, prev = overrides[symbol] if symbol in overrides else fetch_price(symbol)
            if not (price > 0 and prev > 0):
                raise ValueError(f"bad price {price!r}/{prev!r}")
        except Exception as e:
            # A failed fetch must never reach update(): a 0/None price would look like a move through the level.
            state.setdefault(symbol, {})["error"] = str(e)
            continue
        item = state.setdefault(symbol, {})
        item.pop("error", None)
        item["price"] = price  # keeps updating after a trigger, so you can judge a reset
        item["prev_close"] = prev
        item["checked_at"] = now
        for direction in (d for d in DIRS if d in rule):
            # A newly switched-on alert starts from yesterday's close.
            trail = item.setdefault(direction, {"anchor": prev, "status": "active"})
            if update(trail, direction, price, prev, rule[direction]):
                notify(symbol, direction, trail, price, config["push_url"])
                if direction != "down" and config.get("alert_analysis") and config["push_url"]:
                    analyse(symbol, direction, trail, price, prev)


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state, config = load_state(), load_config()
        if cmd == "check":
            overrides = {}
            for arg in sys.argv[2:]:
                symbol, values = arg.split("=", 1)
                price, prev = (values.split(",") + [values])[:2]
                overrides[symbol.upper()] = (float(price), float(prev))
            check(state, config, overrides)
        elif cmd == "set":
            symbol = sys.argv[2].strip().upper()
            if not SYMBOL.match(symbol):
                fail(f"'{symbol}' doesn't look like a ticker (use SYM or SYM:EXCHANGE)")
            rule = {}
            for direction, value in zip(DIRS, sys.argv[3:6]):
                if value.strip().lower() in ("", "off"):
                    continue
                try:
                    rule[direction] = float(value)
                except ValueError:
                    fail(f"'{value}' is not a number")
                if not 0 < rule[direction] < 100:
                    fail("% must be between 0 and 100")
            if not rule:
                fail("set a dip, bounce or stop % (or remove the ticker)")
            if symbol not in config["symbols"]:
                try:
                    fetch_price(symbol)  # refuse typos up front instead of tracking a permanent error row
                except Exception as e:
                    fail(f"{symbol}: {e}")
            config["symbols"][symbol] = rule
            save_json(CONFIG, config)
            check(state, config, {})
        elif cmd == "remove":
            config["symbols"].pop(sys.argv[2].upper(), None)
            save_json(CONFIG, config)
            state.pop(sys.argv[2].upper(), None)
        elif cmd == "reset":
            # Drop the trails so check() re-seeds them from the previous close. The dip keeps its
            # once-a-day state, or resetting a stop on a down day would re-send today's dip alert.
            item = state.get(sys.argv[2].upper(), {})
            item.pop("up", None)
            item.pop("down", None)
            check(state, config, {})
        elif cmd == "interval":
            try:
                minutes = float(sys.argv[2])
            except ValueError:
                fail(f"'{sys.argv[2]}' is not a number")
            if not 1 <= minutes <= 1440:
                fail("refresh must be between 1 and 1440 minutes")  # faster just gets Google to block the scrape
            config["interval_min"] = minutes
            save_json(CONFIG, config)
        elif cmd == "push":
            url = sys.argv[2].strip()
            if url and not re.match(r"^https?://[^/\s]+/\S+$", url):
                fail("phone URL should look like https://ntfy.sh/your-secret-topic")
            config["push_url"] = url
            save_json(CONFIG, config)
        elif cmd == "test":
            if not config["push_url"]:
                fail("set a phone URL first")
            try:
                push(config["push_url"], "Trailing Stops test", "Phone alerts are working.", "white_check_mark")
            except Exception as e:
                fail(f"phone push failed: {e}")
        if cmd != "show":
            # Drop removed symbols and switched-off sides, and keep the panel's rows in config order.
            state = {s: state[s] for s in config["symbols"] if s in state}
            for symbol, item in state.items():
                for direction in DIRS:
                    if direction not in config["symbols"][symbol]:
                        item.pop(direction, None)
            save_json(STATE, state)
    print(json.dumps({"settings": {"interval_min": config["interval_min"], "push_url": config["push_url"]},
                      "rules": config["symbols"], "stocks": state}))


if __name__ == "__main__":
    main()
