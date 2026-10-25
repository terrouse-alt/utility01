"""
NC ABC drop/raffle watcher (version 3 - Linux / Proxmox container, no iMessage).

Watches a list of ABC board web pages. When NEW text appears on a page that
mentions bourbon / allocated / lottery / raffle / drop keywords, it alerts you
by ntfy and email with the board name, the new text, and the page link.

Durham's /drops page keeps its special handling (store address + map link).
Facebook is NOT scraped (see notes in the chat) - turn on Facebook
notifications for those pages instead.

Runs hourly from a systemd timer (nc-abc-watcher.timer) on utility01. Settings
and the Gmail app password come from /etc/watchers/nc_abc_watcher.env, not this file.

Useful commands:
  python3 nc_abc_watcher.py --test     send a sample alert
  python3 nc_abc_watcher.py --boards   show which boards are active / missing a URL
"""
import hashlib, json, os, re, smtplib, sys, time
from email.message import EmailMessage
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

# =====================================================================
#   SETTINGS - notification settings are in /etc/watchers/nc_abc_watcher.env
#   Leave a value empty to turn that notification method off.
# =====================================================================
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")      # several allowed, separated by commas

# Words that make new page text worth an alert (case-insensitive)
KEYWORDS = [
    "bourbon", "allocated", "allocation", "lottery", "raffle", "drop", "dropped",
    "special product", "limited release", "pappy", "van winkle", "blanton",
    "buffalo trace", "eagle rare", "weller", "stagg", "btac", "e.h. taylor",
    "four roses", "birthday bourbon", "whiskey", "whisky",
]
# New text containing these is ignored (e.g. "no drop is scheduled")
IGNORE_PHRASES = ["no drop", "no active", "no raffle", "no lottery", "not currently"]

# ---- BOARDS ----------------------------------------------------------
# (name, url). One line per page - a board can have several lines. Set a url to ""
# to turn it off. Verified pages: Durham and Wake. Every other URL is a homepage
# GUESS - replace it with the board's news / lottery page once you find it.
# Boards with no website listed are skipped
# (those usually post on Facebook only). Websites come from the NC ABC
# Commission's board directory (abc2.nc.gov/StoresBoards/BoardList).
# Run  python3 nc_abc_watcher.py --boards  to see which are active.
# The Durham /drops page gets special handling (store address + map link).
_B = [
    # ---- Your boards ----
    ("Durham County ABC - weekly drops", "https://durhamabc.com/drops"),
    ("Durham County ABC - bourbon / special releases", "https://www.durhamabc.com/bourbon"),
    ("Wake County ABC - lottery page (incl. Rolesville)", "https://wakeabc.com/lottery/"),
    ("Wake County ABC - news & updates", "https://wakeabc.com/category/news-updates/"),
    ("Orange County ABC", "http://orangeabc.com"),
    ("Wilson County ABC", "http://wilson.ncabcboards.com"),
    ("Pitt County ABC", "http://pitt.ncabcboards.com"),
    ("Greene County ABC", ""),
    ("Nash County ABC", ""),
    ("Greensboro ABC (Guilford)", "http://www.greensboroabc.com"),
    ("High Point ABC (Guilford)", "http://www.highpointabc.com"),
    ("Gibsonville ABC", ""),
    ("Chatham County ABC", "http://chatham.ncabcboards.com"),
    ("Pittsboro ABC (Chatham)", ""),
    ("Siler City ABC (Chatham)", ""),
    ("Angier ABC", "http://www.angierabc.com"),
    ("Dunn ABC", ""),
    ("Mecklenburg County ABC", "http://www.meckabc.com"),
    # ---- Around Gibsonville ----
    ("Alamance Municipal ABC", ""),
    ("Reidsville ABC (Rockingham Co.)", ""),
    ("Eden ABC (Rockingham Co.)", ""),
    ("Madison ABC (Rockingham Co.)", ""),
    ("Caswell County ABC", ""),
    ("Liberty ABC (Randolph)", ""),
    ("Randleman ABC (Randolph)", ""),
    ("Ramseur ABC (Randolph)", ""),
    ("Asheboro ABC (Randolph)", ""),
    # ---- Roughly within 2 hours of Rolesville ----
    ("Bunn ABC (Franklin Co.)", ""),
    ("Franklinton ABC (Franklin Co.)", "http://www.franklintonabc.com"),
    ("Louisburg ABC (Franklin Co.)", "http://www.louisburg-abc.org"),
    ("Youngsville ABC (Franklin Co.)", "http://www.youngsvilleabc.com"),
    ("Granville County ABC", ""),
    ("Vance County ABC", ""),
    ("Warren County ABC", ""),
    ("Person County ABC", ""),
    ("Johnston County ABC", "http://johnstonabc.com"),
    ("Lillington ABC (Harnett)", ""),
    ("Sanford ABC (Lee)", ""),
    ("Moore County ABC", "http://www.moore-abc.com"),
    ("Cumberland County ABC", "http://cumberlandabc.com"),
    ("Hoke County ABC", ""),
    ("Wayne County ABC", "http://www.wayneabc.com"),
    ("Lenoir County ABC", "http://lenoir.ncabcboards.com"),
    ("Edgecombe County ABC", ""),
    ("Halifax County ABC", ""),
    ("Northampton County ABC", ""),
    ("Martin County ABC", ""),
    ("Clinton ABC (Sampson)", ""),
    ("Newton Grove ABC (Sampson)", ""),
    ("Roseboro ABC (Sampson)", ""),
    ("Kenansville ABC (Duplin)", ""),
    ("Warsaw ABC (Duplin)", ""),
    # ---- Borderline (about 2 hours - delete any you don't want) ----
    ("Craven County ABC", "http://craven.ncabcboards.com"),
    ("Jones County ABC", ""),
    ("Montgomery ABC", ""),
    ("Lexington ABC", ""),
    ("Thomasville ABC", ""),
    ("Scotland County ABC", ""),
    ("St. Pauls ABC (Robeson)", ""),
    ("Red Springs ABC (Robeson)", ""),
    ("Lumberton ABC (Robeson)", ""),
    ("Pembroke ABC (Robeson)", ""),
    ("Maxton ABC (Robeson)", ""),
]
BOARDS = [{"name": n, "url": u, "type": "durham" if "durhamabc.com/drops" in u else "page"}
          for n, u in _B]
# =====================================================================

# systemd sets STATE_DIRECTORY (/var/lib/nc-abc-watcher); fall back to the script folder
STATE_DIR = os.environ.get("STATE_DIRECTORY") or os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(STATE_DIR, "nc_abc_state.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal drop monitor)"}
KEYWORD_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.I)
IGNORE_RE = re.compile("|".join(re.escape(p) for p in IGNORE_PHRASES), re.I)

# Durham stores: number -> (address, optional "lat,lng")
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


# ------------------------- notifications -----------------------------
def send_ntfy(message):
    r = requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"),
                      headers={"Title": "ABC ALERT", "Priority": "urgent"}, timeout=15)
    r.raise_for_status()



def send_email(message):
    msg = EmailMessage()
    msg["Subject"] = message.splitlines()[0][:150]
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
        print("No notification method is configured - check nc_abc_watcher.env.", file=sys.stderr)
    for name, fn in methods:
        try:
            fn(message)
            print(f"{name} sent: {message.splitlines()[0][:150]}")
        except Exception as e:
            print(f"{name} failed:", e, file=sys.stderr)


# --------------------------- state -----------------------------------
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ------------------------- Durham /drops -----------------------------
def maps_url(num):
    address, coords = STORES[num]
    return f"https://www.google.com/maps/dir/?api=1&destination={coords or quote(address)}"


def check_durham(board, state):
    r = requests.get(board["url"], timeout=15, headers=HEADERS)
    r.raise_for_status()
    text = BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True)
    m = re.search(r"Happening now(.*?)Past drops", text, re.S | re.I)
    live = m.group(1).strip() if m else ""
    is_live = bool(live) and "no drop is active" not in live.lower()
    key = "durham_last_live"
    if is_live:
        if live != state.get(key):
            n = re.search(r"#\s*(\d+)", live)
            if n and n.group(1) in STORES:
                num = n.group(1)
                notify(f"DROP NOW at Durham ABC Store #{num}: {STORES[num][0]}\n{maps_url(num)}")
            else:
                notify(f"DROP NOW (Durham ABC): {re.sub(chr(10), ' ', live)[:300]}\n{board['url']}")
            state[key] = live
    else:
        state[key] = None


# ------------------------ generic page watcher -----------------------
def page_lines(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        t.decompose()
    lines = [re.sub(r"\s+", " ", l).strip() for l in soup.get_text("\n").splitlines()]
    return [l for l in lines if 8 <= len(l) <= 500]


def line_hash(line):
    return hashlib.md5(line.lower().encode()).hexdigest()[:12]


def check_page(board, state):
    r = requests.get(board["url"], timeout=20, headers=HEADERS)
    r.raise_for_status()
    lines = page_lines(r.text)
    seen = set(state.get("pages", {}).get(board["url"], []))
    hashes = [line_hash(l) for l in lines]

    if board["url"] not in state.get("pages", {}):
        print(f"{board['name']}: baseline saved ({len(lines)} lines).")
    else:
        new = [l for l, h in zip(lines, hashes) if h not in seen]
        hits = [l for l in new if KEYWORD_RE.search(l) and not IGNORE_RE.search(l)]
        if hits:
            snippet = " | ".join(hits[:3])[:400]
            notify(f"ABC ALERT - {board['name']}: {snippet}\n{board['url']}")

    state.setdefault("pages", {})[board["url"]] = list((seen | set(hashes)))[-3000:]


# ------------------------------ main ---------------------------------
def main():
    state = load_state()
    for board in BOARDS:
        if not board["url"]:
            continue
        try:
            (check_durham if board["type"] == "durham" else check_page)(board, state)
        except Exception as e:
            print(f"{board['name']} check failed:", e, file=sys.stderr)
        time.sleep(1)                      # be polite to the sites
    save_state(state)


if __name__ == "__main__":
    if "--test" in sys.argv:
        notify("ABC ALERT - Test Board: Bourbon lottery now open\nhttps://example.com")
    elif "--boards" in sys.argv:
        for b in BOARDS:
            print(("ACTIVE  " if b["url"] else "NO URL  ") + b["name"] + "  " + b["url"])
    else:
        main()
