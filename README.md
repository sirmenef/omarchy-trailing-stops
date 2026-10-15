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

## Where things are stored

| Path | What |
|---|---|
| `~/.config/omarchy/trailing-stops.json` | tickers, percentages, refresh interval, phone URL |
| `~/.local/state/trailing-stops/state.json` | trailing highs and lows, and which alerts have fired |

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

```bash
omarchy plugin remove io.github.sirmenef.trailing-stops
rm -f ~/.config/omarchy/trailing-stops.json
rm -rf ~/.local/state/trailing-stops
```

If you set up phone alerts, also unsubscribe from the topic in the ntfy app.

## License

[MIT](LICENSE)
