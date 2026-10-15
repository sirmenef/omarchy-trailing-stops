# Trailing Stops for Omarchy

A bar widget that watches share prices and tells you when to look at buying or selling. Each ticker
can run three alerts, each with its own percentage:

| Alert | Fires when | Meaning |
|---|---|---|
| **Buy dip** | the price is X% below yesterday's close | it's cheap today; checked once a day |
| **Buy bounce** | the price rises X% off its lowest point since yesterday's close | it has stopped falling |
| **Sell stop** | the price falls X% from its highest point since yesterday's close | a trailing stop-loss |

Bounce and stop *trail*: the low only ratchets down and the high only ratchets up, so the trigger
level follows the price. They stay triggered until you press reset. A dip re-arms by itself on the
next trading day.

- **Bar icon:** red when any sell stop has fired, green when a buy alert has fired, and the
  theme colour when there is nothing to do. You can glance at it if you missed a notification.
- **Panel:** click the icon to add or remove tickers, set each alert's % (leave it blank to turn it
  off), reset a ticker, change the refresh interval and set up phone alerts. Triggered tickers and
  alert lines use the same red and green.
- **Notifications:** a critical desktop notification, which gets through Do Not Disturb. Clicking it
  opens the share on Google Finance. Phone push is optional (see below).
- **Daily roundup (optional):** after the US close, an AI agent writes a short blog post on how your
  shares behaved and why. A second agent fact-checks it before it is saved. When a Buy bounce has
  fired, the post also judges, from the last two weeks of prices, whether it looks like a real turn or
  a temporary rally. See [Daily roundup](#daily-roundup-optional-extra-setup).
- **Alert analysis (optional):** a few minutes after a Buy dip or Buy bounce fires, a second phone push
  sums it up and links to a short article: what is pushing the price down, or whether the bounce looks
  like a real turn or a temporary rally. It is written and fact-checked the same way. See
  [Alert analysis](#alert-analysis-optional).

Tickers are Google Finance symbols. A bare `MU` or `SNDK` is looked up on NASDAQ. For other
exchanges use `TICKER:EXCHANGE`, for example `BP:LON` or `WDC:NASDAQ`.

> Not financial advice. Prices come from Google Finance, may be delayed, and are read from the
> public quote page (there is no official API). If Google changes that page, the tracker shows an
> error rather than firing an alert.

## Install

```bash
omarchy plugin add https://github.com/sirmenef/omarchy-trailing-stops.git --enable
```

The widget lands in the right section of the bar. Move it with
`omarchy bar move io.github.sirmenef.trailing-stops --section left|center|right`.

On first run it starts tracking SNDK and MU with a 2.5% bounce alert, as an example. Change or remove
them in the panel.

### Dependencies

All of these come with Omarchy:

- `python3` (standard library only)
- `notify-send` (libnotify) for desktop alerts
- `xdg-open` to open Google Finance when you click an alert
- The optional daily roundup and alert analysis have extra requirements; see their sections below
- Network access to `www.google.com/finance` and, if you set it up, your ntfy server

## Phone notifications (optional extra setup)

Desktop alerts work without any setup. To also get alerts on your phone, the plugin posts each
alert to an [ntfy](https://ntfy.sh) topic, and the ntfy app on your phone subscribes to the same
topic. Tapping the phone notification opens the share on Google Finance.

1. Install the ntfy app on your phone
   ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) /
   [iOS](https://apps.apple.com/us/app/ntfy/id1625396347)).
2. Pick a long, random topic name. Anyone who knows or guesses a topic on the public ntfy.sh server
   can read it, so don't use something like `stocks`. To generate one:
   ```bash
   echo "trailing-stops-$(openssl rand -hex 8)"
   ```
3. In the ntfy app, tap **+** and subscribe to that topic on `https://ntfy.sh`.
4. Open the Trailing Stops panel, paste `https://ntfy.sh/<your-topic>` into the **Phone** field and
   press Enter.
5. Press **Test**. A test notification should arrive on your phone within a few seconds.

To turn phone alerts off, clear the **Phone** field and press Enter.

**Private alternative:** to keep your alerts off a public server, host ntfy yourself (see
[ntfy's self-hosting docs](https://docs.ntfy.sh/install/)) and paste your own server's topic URL
instead. If your server is only reachable on a private network such as a VPN, your phone needs to be
on that network too. On iOS, instant delivery from a self-hosted server also needs `upstream-base-url`
set; the ntfy docs explain it.

## Daily roundup (optional extra setup)

Each weekday, 30 minutes after the 16:00 New York close, `roundup.py` writes a post about your
tickers:
- a snapshot table with the day's alerts;
- how the shares behaved over the last two weeks;
- what moved them, with sources;
- what can be inferred, with guesses labelled as guesses;
- what to watch next.

For each ticker whose **Buy bounce** alert has fired, the post adds a **Bounce or rally?** section. It
looks at the last 10 sessions of daily closes and volume from Google Finance and judges whether the
rise looks like a genuine turn, a temporary rally or too early to tell. It also says which closing
prices would confirm or undo the bounce.

How a post is made:
- Prices come from the tracker and Google Finance only; the agents only research the news.
- One agent writes the post, the other fact-checks every claim against its sources and the price
  data, and the writer then accepts or rejects each finding and revises.
- With [Claude Code](https://claude.com/claude-code) and [Codex](https://developers.openai.com/codex/cli)
  both installed, Claude writes and Codex checks. If either is unavailable, the other fills in.
- Every post links to review notes showing who wrote and checked it and what changed.

**Requirements:**
- At least one of the `claude` or `codex` CLIs, installed and logged in. Each run uses your plan or API
  credit: a few minutes of agent time with web search.
- The Python Markdown package:
  ```bash
  omarchy pkg add python-markdown
  ```
- Your tickers and prices are sent to the AI provider(s) with the request.

**Set it up:** the timer ships with the plugin, but you copy it in and turn it on yourself:

```bash
cp ~/.config/omarchy/plugins/io.github.sirmenef.trailing-stops/share-roundup.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now share-roundup.timer
```

To write one straight away (after the US close), run
`python3 ~/.config/omarchy/plugins/io.github.sirmenef.trailing-stops/roundup.py`.

**Read the posts:** open `~/.local/share/trailing-stops/roundups/index.html` in a browser. It lists both
kinds of article; `daily/` lists only the daily roundups and `alerts/` only the alert analyses. If phone
alerts are set up, each post is announced on your phone too, along with a failure notice if no agent
could write it. To make tapping that notification open the post, serve the folder somewhere your phone
can reach, for example with `tailscale serve`. Then add its address to
`~/.config/omarchy/trailing-stops.json`:

```json
"roundup_url": "https://your-machine.your-tailnet.ts.net/roundups/"
```

Set `"roundup_dir"` in the same file to keep the posts somewhere else.

**Updating:** `omarchy plugin update` updates `roundup.py` and the prompts, but not your copied timer
files. If `share-roundup.service` or `.timer` change, copy them in again and run
`systemctl --user daemon-reload`.

## Alert analysis (optional)

When a **Buy dip** or **Buy bounce** fires, the usual alert goes out straight away. With alert analysis
on, a second push follows a few minutes later:

- **Buy dip:** what is pushing the price down. That could be the company's own news, the sector, the
  whole market, or no clear reason. It also says whether this is a one-off drop or part of a slide
  over the last two weeks.
- **Buy bounce:** the case for a genuine turn and the case for a temporary rally (a "dead-cat bounce").
  It gives a verdict labelled as judgement and the closing prices that would confirm or undo it.

The push carries a short summary. The full article adds why the alert fired, what is behind the move,
the case for and against, the last two weeks and what to watch, with its sources and review notes. It
is written, fact-checked and revised by the same Claude/Codex pair as the daily roundup.

Tapping the push opens the article if `roundup_url` is set (see above). Otherwise it opens the share on
Google Finance. The articles are saved in the roundup folder under `alerts/` and listed on its index
page and on `alerts/`. Sell stops don't get one.

**Requirements:** phone notifications set up, plus the same `claude`/`codex` CLI and `python-markdown`
as the daily roundup. You don't need the roundup timer. Each analysis is one AI run on your plan or
credit, and it sends the ticker and prices to the provider.

**Turn it on** by adding this to `~/.config/omarchy/trailing-stops.json`:

```json
"alert_analysis": true
```

If an analysis fails, the push says so. The log is `~/.local/state/trailing-stops/alert-analysis.log`.

## Where things are stored

| Path | What |
|---|---|
| `~/.config/omarchy/trailing-stops.json` | tickers, percentages, refresh interval, phone URL |
| `~/.local/state/trailing-stops/state.json` | trailing highs and lows, and which alerts have fired |
| `~/.local/share/trailing-stops/roundups/` | daily roundup posts, alert articles (`alerts/`) and their review notes (if you use them) |

The plugin writes only these (plus a lock file next to `state.json`). It never touches any other configuration.

## Command line

The panel drives `tracker.py`, which you can also run yourself:

```bash
cd ~/.config/omarchy/plugins/io.github.sirmenef.trailing-stops
python3 tracker.py show            # settings, rules and state as JSON
python3 tracker.py set MU 3 5 3    # MU: bounce 3%, stop 5%, dip 3% ("off" turns one off)
python3 tracker.py reset MU        # restart MU's bounce and stop from yesterday's close
python3 tracker.py push https://ntfy.sh/<your-topic>
python3 tracker.py test            # send a test push
```

## Remove

If you turned on the daily roundup, remove its timer first:

```bash
systemctl --user disable --now share-roundup.timer
rm -f ~/.config/systemd/user/share-roundup.{service,timer}
systemctl --user daemon-reload
rm -rf ~/.local/share/trailing-stops   # deletes the posts too
```

Then remove the plugin and its settings:

```bash
omarchy plugin remove io.github.sirmenef.trailing-stops
rm -f ~/.config/omarchy/trailing-stops.json
rm -rf ~/.local/state/trailing-stops
```

If you set up phone alerts, also unsubscribe from the topic in the ntfy app.

## License

[MIT](LICENSE)
