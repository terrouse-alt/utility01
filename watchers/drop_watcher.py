"""
Watches https://durhamabc.com/drops and, the moment a drop goes live, sends you
the store address + a tappable Google Maps link by ntfy and email.

Version 4: runs on Linux (Proxmox container), no iMessage. Settings come from
environment variables (loaded by systemd from /etc/watchers/drop_watcher.env),
so no passwords live in this file. A systemd timer runs it every minute and
never starts a new run while the previous one is still going.

Send yourself a sample alert (does not touch the saved state):
  python3 drop_watcher.py --test
"""
import json, os, re, smtplib, sys
from email.message import EmailMessage
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

# =====================================================================
#                SETTINGS - set in /etc/watchers/drop_watcher.env
#   Leave a value empty to turn that notification method off.
# =====================================================================

# ntfy push notification (must match the topic name in the ntfy app exactly)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# Email via Gmail (16-character app password, no spaces)
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")       # several allowed, separated by commas

# =====================================================================

URL = "https://durhamabc.com/drops"
# systemd sets STATE_DIRECTORY (/var/lib/drop-watcher); fall back to the script folder
STATE_DIR = os.environ.get("STATE_DIRECTORY") or os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(STATE_DIR, "drop_state.json")

# Store number -> (address, optional "lat,lng"). Addresses from durhamabc.com/stores
STORES = {
    "1":  ("1928 Holloway Street, Durham, NC 27703", None),
    "3":  ("2806 Hillsborough Road, Durham, NC 27705", None),
    "4":  ("2525 Page Rd, Morrisville, NC 27560", None),
    "5":  ("115 Sherron Road, Durham, NC 27703", None),
    "7":  ("1517 Glenn School Rd, Suite #8, Durham, NC 27704", None),
    "8":  ("5122 N. Roxboro Street, Unit 100, Durham, NC 27704", None),
    "10": ("5608 Hwy 55, Durham, NC 27713", None),
    "11": ("3620 Durham-Chapel Hill Blvd, Durham, NC 27707", "35.972142,-78.949554"),
    "12": ("1515 North Pointe Drive, Suite 101, Durham, NC 27705", "36.0277,-78.9149"),
    "14": ("1112 NC-54, Durham, NC 27707", None),
}


def maps_url(num):
    address, coords = STORES[num]
    dest = coords or quote(address)
    return f"https://www.google.com/maps/dir/?api=1&destination={dest}"


def build_message(live_text):
    m = re.search(r"#\s*(\d+)", live_text)
    if m and m.group(1) in STORES:
        n = m.group(1)
        return f"DROP NOW at Store #{n}: {STORES[n][0]}\n{maps_url(n)}"
    cleaned = re.sub(r"\s+", " ", live_text)   # unknown format: send the raw text
    return f"DROP NOW: {cleaned}\n{URL}"


def send_ntfy(message):
    r = requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"),
                      headers={"Title": "DROP NOW", "Priority": "urgent"}, timeout=15)
    r.raise_for_status()


def send_email(message):
    msg = EmailMessage()
    msg["Subject"] = message.splitlines()[0]
    msg["From"], msg["To"] = EMAIL_USER, EMAIL_TO
    msg.set_content(message)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        s.send_message(msg)


def notify(message):
    """Try every configured method; one failing never blocks the others."""
    methods = []
    if NTFY_TOPIC:
        methods.append(("ntfy", send_ntfy))
    if EMAIL_USER and EMAIL_APP_PASSWORD and EMAIL_TO:
        methods.append(("email", send_email))
    if not methods:
        print("No notification method is configured - check drop_watcher.env.", file=sys.stderr)
    for name, fn in methods:
        try:
            fn(message)
            print(f"{name} sent: {message.splitlines()[0]}")
        except Exception as e:
            print(f"{name} failed:", e, file=sys.stderr)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"last_live": None}


def main():
    r = requests.get(URL, timeout=15, headers={"User-Agent": "Mozilla/5.0 (personal drop monitor)"})
    r.raise_for_status()
    text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)

    # Everything between the "Happening now" and "Past drops" headings
    m = re.search(r"Happening now(.*?)Past drops", text, re.S | re.I)
    live = m.group(1).strip() if m else ""
    is_live = bool(live) and "no drop is active" not in live.lower()

    state = load_state()
    if is_live:
        if live != state.get("last_live"):       # only alert once per drop
            notify(build_message(live))
            state["last_live"] = live
    else:
        state["last_live"] = None                # reset so the next drop alerts again

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


if __name__ == "__main__":
    if "--test" in sys.argv:
        notify(build_message("Store #12"))
        sys.exit(0)
    try:
        main()
    except Exception as e:
        print("Check failed:", e, file=sys.stderr)
        sys.exit(1)
