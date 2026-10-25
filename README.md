# utility01

Always-on Debian 13 LXC container on Proxmox (`172.16.10.50`), CT **100**, hostname **utility01**,
IP **172.16.10.37** (DHCP — reserve it). 1 core, 512 MB RAM, 4 GB on `local-lvm`, starts on boot.
SSH: `ssh root@172.16.10.37` (Mac key installed).

## What runs here

| Unit | Schedule | What it does | Alerts |
|---|---|---|---|
| `drop-watcher.timer` | every minute | `watchers/drop_watcher.py` — durhamabc.com/drops, store address + map link | ntfy `DaBullShit` + email |
| `nc-abc-watcher.timer` | hourly | `watchers/nc_abc_watcher.py` — NC ABC board pages, keyword matches | ntfy `NC_DROP_ALERT` + email |
| `notify-failure@.service` | on failure | any watcher failing → phone alert (max 1/hour per unit) | ntfy `OLD_CLAUDY` |

systemd never starts a run while the previous one is still going, so runs can't pile up.

## Layout on the container

| Path | Contents |
|---|---|
| `/opt/watchers/` | the watcher scripts |
| `/etc/watchers/*.env` | ntfy topics + Gmail app password (root:watcher 640, **not in git**) |
| `/var/lib/drop-watcher/`, `/var/lib/nc-abc-watcher/` | saved state (what was already alerted) |
| `/etc/systemd/system/` | the units in `systemd/` |
| `/usr/local/bin/notify-claudy` | `notify-claudy "Title" "Message" [priority] [tags]` → OLD_CLAUDY |

## Everyday commands

```bash
ssh root@172.16.10.37 systemctl list-timers '*watcher*'
ssh root@172.16.10.37 journalctl -u drop-watcher -n 50
ssh root@172.16.10.37 journalctl -u nc-abc-watcher -n 50
```

Send a test alert with the real settings:

```bash
ssh root@172.16.10.37 systemd-run --wait --pipe --quiet -p User=watcher -p EnvironmentFile=/etc/watchers/drop_watcher.env /usr/bin/python3 /opt/watchers/drop_watcher.py --test
```

## Deploying a change

1. Edit the file here, commit.
2. `scp watchers/drop_watcher.py root@172.16.10.37:/opt/watchers/` (or the unit into `/etc/systemd/system/` then `systemctl daemon-reload`).

## Rebuilding from scratch

1. `pct create 100 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst --hostname utility01 --cores 1 --memory 512 --swap 512 --rootfs local-lvm:4 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1 --onboot 1 --ssh-public-keys ~/.ssh/id_ed25519.pub`
2. `apt-get install -y python3-requests python3-bs4 curl unattended-upgrades`
3. `useradd --system --no-create-home --shell /usr/sbin/nologin watcher`
4. Copy `watchers/` → `/opt/watchers/`, `bin/` → `/usr/local/bin/`, `systemd/` → `/etc/systemd/system/`.
5. Create `/etc/watchers/*.env` from `config/*.env.example` (fill in the Gmail app password), `chmod 640`, `chgrp watcher`.
6. `systemctl daemon-reload && systemctl enable --now drop-watcher.timer nc-abc-watcher.timer`

## Claude Code → OLD_CLAUDY (on the Mac)

`claude/old-claudy.sh` lives at `~/.claude/hooks/old-claudy.sh`; `claude/settings.json` is
`~/.claude/settings.json`. Hooks: `Notification` (Claude waiting on you), `Stop` (finished),
`StopFailure` (API error).

**Note:** ntfy.sh topics are public — anyone who guesses a topic name can read or post to it.
Don't send secrets through them.
