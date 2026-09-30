# yt-limit

Daily YouTube time limiter for Linux desktops. Runs as a user-level background service. Counts only seconds during which a YouTube video is actually playing, as reported by the browser over MPRIS (D-Bus). When the daily limit is reached it pauses the player through D-Bus and shows a short on-screen notice on every play attempt. Resets at local midnight.

- Language: Python 3.10+. No pip dependencies. Uses system PyGObject (GTK 3, Gio, GLib).
- Tested: Ubuntu 26.04, GNOME 50 on Wayland, Firefox 156 (snap). Should work on any Linux session with a D-Bus session bus.
- Repository: https://github.com/luiz-nast/yt-limit
- License: MIT

## Behavior

| Situation | Counted | On-screen pill |
|---|---|---|
| YouTube tab open, video paused | no | hidden |
| YouTube video playing, tab visible or in background | yes, 1 s per second | visible: `▶ MM:SS / MM:SS` |
| Video stops or is paused | no | stays 2 s, then hides |
| Playing, 5 min or less left | yes | visible, yellow |
| Limit reached, user presses play | no; player is paused within 1 s | `⛔ Tempo esgotado, volte amanhã` for 2 s |
| Other site playing media (Pinterest, Spotify Web, etc.) | no | hidden |
| YouTube in a private/incognito window | yes (see Detection layers) | as above |
| Two YouTube tabs playing in the same Firefox process | counted once (Firefox exposes one player per process) | as above |
| Reboot, logout, service restart | state persists; only a date change resets the counter | — |

Notifications (via `notify-send`): one when `warn_minutes_left` minutes remain, one when the limit is reached.

## Detection layers

Every second the app lists `org.mpris.MediaPlayer2.*` names on the session bus and reads `PlaybackStatus` and `Metadata` from each. A player counts as YouTube if any layer says yes:

1. **MPRIS metadata.** `xesam:url` (Firefox) or `mpris:artUrl` (Chrome) matches `youtube.com`, `youtu.be`, `youtube-nocookie.com`, `ytimg.com` or `googlevideo.com`. Exact.
2. **Accessibility tree (AT-SPI).** Used only when the player belongs to a browser and has no URL and no art URL, which is what Firefox and Chrome do in private/incognito windows (Firefox reports the title as "O Firefox está reproduzindo mídia"). The app walks the browser's AT-SPI tree and looks for a document whose name ends with `- YouTube` or whose `DocURL` contains `youtube.com`. Exact, but requires the browser to be registered on the accessibility bus. On GNOME that requires `toolkit-accessibility` to be enabled before the browser starts:

   ```bash
   gsettings set org.gnome.desktop.interface toolkit-accessibility true
   ```

   then close and reopen the browser. Results are cached for 5 s.
3. **Fallback.** If the browser is not on the accessibility bus, a browser player with hidden metadata is counted as YouTube when `count_private_media` is `true` (default). This can overcount media from other sites played in a private window. Set `count_private_media` to `false` to never count hidden-metadata media.

Run `yt-limit --check` to see which layer applies right now.

## Install

Requirements: `python3-gi` and `gir1.2-gtk-3.0` (Debian/Ubuntu package names), `notify-send` optional.

```bash
sudo apt install python3-gi gir1.2-gtk-3.0
git clone https://github.com/luiz-nast/yt-limit.git ~/yt-limit
cd ~/yt-limit
./install.sh
```

`install.sh` does the following:

- copies `yt_limit/` to `~/.local/lib/yt-limit/`
- writes the wrapper `~/.local/bin/yt-limit`
- writes `~/.config/systemd/user/yt-limit.service` with `GDK_BACKEND=x11`
- runs `systemctl --user enable --now yt-limit.service`

Re-run `./install.sh` after pulling updates, then `systemctl --user restart yt-limit`.

`./uninstall.sh` stops and disables the service and removes the copied files. It keeps config and state.

Do not start the daemon from a process confined by AppArmor (for example from inside another snap): the Firefox snap rejects D-Bus calls from confined peers with `Access denied`. The systemd user service and a normal terminal are unconfined.

## CLI

```
yt-limit                 run the daemon in the foreground
yt-limit --status        print today's total and the top 10 videos by seconds
yt-limit --check         print MPRIS players, their classification and accessibility-bus status
yt-limit --limit N       set the daily limit to N minutes and exit (restart the service to apply)
yt-limit --reset         set today's counter to zero and exit
yt-limit --debug         run in the foreground and log every player every second
yt-limit --no-overlay    run without any window (count and pause only)
```

Service management:

```bash
systemctl --user status yt-limit
systemctl --user restart yt-limit
journalctl --user -u yt-limit -f
```

## Configuration

File: `~/.config/yt-limit/config.json`. Created on first `--limit`. Missing keys use defaults.

```json
{
  "limit_minutes": 30,
  "hide_after_seconds": 2,
  "warn_minutes_left": 5,
  "count_private_media": true
}
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `limit_minutes` | int | 30 | Daily limit in minutes |
| `hide_after_seconds` | int | 2 | How long the pill stays visible after playback stops, and how long the "time's up" notice shows |
| `warn_minutes_left` | int | 5 | Remaining minutes at which the warning notification fires and the pill turns yellow |
| `count_private_media` | bool | true | Count hidden-metadata browser media as YouTube when the accessibility tree cannot confirm |

State file: `~/.local/share/yt-limit/state.json`. Written every 5 s while running and on SIGTERM/SIGINT/SIGHUP.

```json
{
  "day": "2026-09-30",
  "seconds": 1800,
  "per_video": { "<xesam:title>": 1046 }
}
```

`day` is the local date. On start and on every tick the app compares it with today; a mismatch resets `seconds` and `per_video`.

## Files

```
yt_limit/__main__.py   argument parsing, --status, --check, --limit, --reset
yt_limit/app.py        1 s tick: classify players, add time, warn, pause, drive the overlay
yt_limit/mpris.py      list MPRIS players, read PlaybackStatus/Metadata, Pause()
yt_limit/a11y.py       AT-SPI walk to find YouTube documents in browsers
yt_limit/overlay.py    GTK 3 always-on-top pill (forces GDK_BACKEND=x11)
yt_limit/store.py      Config and State dataclasses, JSON persistence, fmt()
install.sh             user service installer
uninstall.sh
```

## Overlay details

- GTK 3 undecorated window, type hint DOCK, keep-above, sticky, no focus, skip taskbar.
- GNOME on Wayland ignores keep-above for native Wayland windows, so `overlay.py` sets `GDK_BACKEND=x11` and runs through XWayland, where Mutter honors `_NET_WM_STATE_ABOVE`.
- Positioned at the top-right of the primary monitor's work area (excludes the GNOME top bar and dock), 12 px margin.
- Fullscreen windows cover the pill. Counting and pausing continue.

## Known limitations

- Chrome/Chromium does not publish the page URL over MPRIS; detection there relies on the thumbnail host `i.ytimg.com`. Shorts without artwork may be missed (layer 2 or 3 may still catch them).
- YouTube Music is counted: same domains, same artwork host.
- YouTube ads are counted while they play; the browser reports them as playing media with the ad's title.
- Layer 2 has been implemented against the AT-SPI protocol and tested for connectivity and traversal on GNOME Shell, but not yet against a live Firefox with accessibility enabled.
- Only media the browser exposes as a media session is seen. A browser with MPRIS disabled (Firefox `media.hardwaremediakeys.enabled = false`) is invisible to the app.

## Troubleshooting

| Symptom | Check |
|---|---|
| Pill never appears | `yt-limit --check` shows a `Playing` YouTube player? If not, the browser is not exposing MPRIS. |
| Private window not counted | `yt-limit --check`: player shown as `privado/sem metadados`? Then layer 3 applies unless `count_private_media` is false. Enable `toolkit-accessibility` for layer 2. |
| `Access denied` in logs | Daemon started from an AppArmor-confined process. Use the systemd service. |
| Pill hidden behind the top bar | Fixed in 5b5d087; run `./install.sh` and restart the service. |
| Counter did not reset | It resets on local date change only. Check `day` in `state.json`. |
