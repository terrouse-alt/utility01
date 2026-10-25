#!/bin/sh
# Called by notify-failure@<unit>.service when a watcher fails.
# Sends at most one alert per unit per hour so a flaky site can't spam the phone.
UNIT="$1"
STAMP="/run/notify-failure/$(echo "$UNIT" | tr '/' '_')"
mkdir -p /run/notify-failure
if [ -f "$STAMP" ] && [ $(( $(date +%s) - $(stat -c %Y "$STAMP") )) -lt 3600 ]; then
  exit 0
fi
touch "$STAMP"
LOG=$(journalctl -u "$UNIT" -n 6 --no-pager -o cat 2>/dev/null | cut -c1-200)
/usr/local/bin/notify-claudy "utility01: $UNIT failed" "$LOG" high warning
