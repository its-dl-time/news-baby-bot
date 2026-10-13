"""Cloud news bot: 24/7 on Render/Railway free, NO opencode dependency.
- RSS news (Google News + VnExpress + CafeF ...) via stdlib only.
- Rule-based brief + impact (works with ZERO api keys).
- Optional: set GEMINI_API_KEY (free at aistudio.google.com) for AI impact lines.
- Bilingual VI (default, có dấu) / EN via /lang. Health endpoint for keepalive.
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (owner), optional GEMINI_API_KEY.
"""
import datetime
import html
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OWNER = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN env")
API = f"https://api.telegram.org/bot{TOKEN}"
SUBS = BASE / "subscribers.json"

FEEDS = [
    ("GoogleNews-VN-stock", "https://news.google.com/rss/search?q=VN-Index%20ch%E1%BB%A9ng%20kho%C3%A1n&hl=vi&gl=VN&ceid=VN%3Avi"),
    ("GoogleNews-VN-kinhte", "https://news.google.com/rss/search?q=kinh%20t%E1%BA%BF%20Vi%E1%BB%87t%20Nam&hl=vi&gl=VN&ceid=VN%3Avi"),
    ("GoogleNews-VN-vang", "https://news.google.com/rss/search?q=gi%C3%A1%20v%C3%A0ng%20t%E1%BB%B7%20gi%C3%A1%20USD&hl=vi&gl=VN&ceid=VN%3Avi"),
    ("GoogleNews-crypto", "https://news.google.com/rss/search?q=bitcoin%20crypto%20market&hl=en-US&gl=US&ceid=US%3Aen"),
    ("GoogleNews-AI", "https://news.google.com/rss/search?q=AI%20artificial%20intelligence%20OpenAI&hl=en-US&gl=US&ceid=US%3Aen"),
    ("GoogleNews-stocks", "https://news.google.com/rss/search?q=stock%20market%20S%26P%20500%20Fed&hl=en-US&gl=US&ceid=US%3Aen"),
    ("VnExpress-KD", "https://vnexpress.net/rss/kinh-doanh.rss"),
    ("VnExpress-CN", "https://vnexpress.net/rss/so-hoa.rss"),
    ("VnExpress-KH", "https://vnexpress.net/rss/khoa-hoc.rss"),
    ("TuoiTre-KT", "https://tuoitre.vn/rss/kinh-doanh.rss"),
]

BEAR = ["rate hike", "tăng lãi suất", "bán ròng", "sell-off", "bán tháo", "margin call", "lạm phát cao",
        "inflation", "giảm", "fall", "drop", "hack", "lừa đảo", "rug", " Fine ", "phạt"]
BULL = ["tăng trưởng", "growth", "kỷ lục", "record", "mua ròng", "inflow", "ETF inflow", "đột phá",
        "breakthrough", "nâng dự báo", "upgrade", "giảm lãi suất", "rate cut", "thoả thuận", "deal"]


def api(method, params=None, timeout=35):
    url = f"{API}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(chat, text):
    for i in range(0, max(len(text), 1), 4000):
        api("sendMessage", {"chat_id": chat, "text": text[i:i + 4000]})


def fetch_rss(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 newsbot"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_items(xml_bytes, source):
    out = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return out
    for it in root.iter("item"):
        def t(tag):
            el = it.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        out.append({"title": t("title"), "link": t("link"), "pub": t("pubDate"), "src": source})
    return out


def scan(window_from, window_to, keyword=""):
    wf = datetime.date.fromisoformat(window_from)
    wt = datetime.date.fromisoformat(window_to)
    items = []
    for name, url in FEEDS:
        try:
            items += parse_items(fetch_rss(url), name)
        except Exception:
            continue
    # dedupe by link
    seen, uniq = set(), []
    for it in items:
        if it["link"] and it["link"] not in seen:
            seen.add(it["link"])
            uniq.append(it)
    if keyword:
        kw = keyword.lower()
        uniq = [i for i in uniq if kw in (i["title"] + i["link"]).lower()]
    return uniq[:30]


def rule_impact(title):
    t = title.lower()
    if any(k.lower() in t for k in BEAR):
        return "Bearish ngắn hạn (rule-based, chưa có AI)"
    if any(k.lower() in t for k in BULL):
        return "Bullish ngắn hạn (rule-based, chưa có AI)"
    return "Neutral (rule-based, chưa có AI)"


def ai_impact(title):
    """Optional Gemini upgrade; fallback to rule-based."""
    if not GEMINI_KEY:
        return rule_impact(title)
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.5-flash:generateContent?key={GEMINI_KEY}")
        body = json.dumps({"contents": [{"parts": [
            {"text": f"1 dòng tiếng Việt: tin '{title}' tác động Bullish/Bearish/Neutral tới tài sản nào, ngắn hay dài hạn?"}]}]}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
        return j["candidates"][0]["content"]["parts"][0]["text"].strip()[:200]
    except Exception:
        return rule_impact(title) + " [AI lỗi, dùng rule]"


def lang_load():
    try:
        return json.loads((BASE / "user_lang.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_lang(chat):
    return lang_load().get(str(chat), "vi")


HELP_VI = """🤖 Bot tin tức 24/7 (bản cloud, không cần mở máy ở nhà):

🟢 /brief [hôm-nay|hôm-qua|YYYY-MM-DD] [từ-khóa] — vd /brief hôm-nay crypto
🔵 /date YYYY-MM-DD — vd /date 2026-10-10
🔵 /range A B — vd /range 2026-10-01 2026-10-10
🔵 /search <từ-khóa> — vd /search VN-Index
🟢 /market — giá BTC nhanh
🟢 /lang vi|en — đổi ngôn ngữ
🟢 /subscribe /unsubscribe — nhận tin 7h sáng
🟢 /ping /status /help

⚠️ Bản cloud dùng RSS + rule-based impact (chưa có AI nếu chưa gắn key). Không phải lời khuyên tài chính."""
HELP_EN = """🤖 24/7 news bot (cloud build, home PC can stay off):

🟢 /brief [today|yesterday|YYYY-MM-DD] [keyword]
🔵 /date, /range, /search, /market, /lang vi|en, /subscribe, /ping, /status, /help

⚠️ Cloud build uses RSS + rule-based impact (no AI key yet). Not financial advice."""


def briefing_text(wf, wt, keyword, lang):
    items = scan(wf, wt, keyword or "")
    head = (f"Bản tin {wf}..{wt}" + (f" — từ khóa: {keyword}" if keyword else "")) if lang == "vi" \
        else (f"Briefing {wf}..{wt}" + (f" — keyword: {keyword}" if keyword else ""))
    lines = [head, ""]
    for i, it in enumerate(items[:15], 1):
        lines.append(f"{i}. [{it['src']}] {html.unescape(it['title'])}")
        lines.append(f"   {it['link']}")
        lines.append(f"   → {ai_impact(it['title'])}")
    if not items:
        lines.append("Không tìm thấy tin trong khoảng này." if lang == "vi" else "No items in window.")
    lines.append("")
    lines.append("Nguồn: Google News RSS + VnExpress + Tuổi Trẻ (rule-based).")
    return "\n".join(lines)[:7500]


def handle(chat, text):
    lang = get_lang(chat)
    parts = text.strip().split()
    cmd = parts[0].split("@")[0].lower() if parts else ""
    args = parts[1:] if len(parts) > 1 else []
    if cmd == "/start":
        send(chat, ("Chào bạn! " if lang == "vi" else "Hi! ") + (HELP_VI if lang == "vi" else HELP_EN))
    elif cmd == "/help":
        send(chat, HELP_VI if lang == "vi" else HELP_EN)
    elif cmd == "/lang":
        d = lang_load()
        if args and args[0].lower() in ("vi", "en"):
            d[str(chat)] = args[0].lower()
            (BASE / "user_lang.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            send(chat, "Đã chuyển sang tiếng Việt." if args[0] == "vi" else "Switched to English.")
        else:
            send(chat, "Dùng: /lang vi|en")
    elif cmd == "/ping":
        send(chat, "pong cloud " + datetime.datetime.now().isoformat(timespec="seconds"))
    elif cmd == "/subscribe":
        s = set()
        try:
            s = set(json.loads(SUBS.read_text(encoding="utf-8")))
        except Exception:
            pass
        s.add(str(chat))
        SUBS.write_text(json.dumps(sorted(s)), encoding="utf-8")
        send(chat, f"Đã đăng ký 7h sáng. Tổng {len(s)}.")
    elif cmd == "/unsubscribe":
        s = set()
        try:
            s = set(json.loads(SUBS.read_text(encoding="utf-8")))
        except Exception:
            pass
        s.discard(str(chat))
        SUBS.write_text(json.dumps(sorted(s)), encoding="utf-8")
        send(chat, "Đã hủy.")
    elif cmd == "/status":
        send(chat, f"cloud bot ok, AI={'Gemini' if GEMINI_KEY else 'rule-based'}, subs={len(json.loads(SUBS.read_text())) if SUBS.exists() else 0}")
    elif cmd == "/market":
        try:
            with urllib.request.urlopen("https://data-api.coindesk.com/index/cc/v1/latest/tick?market=cdc&instruments=BTC-USD", timeout=15) as r:
                px = json.loads(r.read().decode())["Data"]["BTC-USD"]["VALUE_LAST_UPDATE"]
            send(chat, f"BTC: ${px:,.0f} (CoinDesk)")
        except Exception as e:
            send(chat, f"BTC: lỗi {type(e).__name__}")
    elif cmd in ("/brief", "/date", "/range", "/search"):
        kw = ""
        wf = wt = datetime.date.today().isoformat()
        if cmd == "/date" and args:
            wf = wt = args[0]
            kw = " ".join(args[1:])
        elif cmd == "/range" and len(args) >= 2:
            wf, wt = args[0], args[1]
            kw = " ".join(args[2:])
        elif cmd == "/search" and args:
            kw = " ".join(args)
            wf = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        elif cmd == "/brief" and args:
            kw = " ".join(a for a in args if not re.match(r"^\d", a))
            for a in args:
                if re.match(r"^\d{4}-\d{2}-\d{2}", a):
                    wf = wt = a
        send(chat, briefing_text(wf, wt, kw, lang))
    else:
        send(chat, "Gõ /help." if lang == "vi" else "Type /help.")


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"newsbot ok")
    def log_message(self, *a):
        pass


def daily_loop():
    sent = set()
    while True:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
        key = now.strftime("%Y-%m-%d")
        if now.hour == 7 and now.minute < 10 and key not in sent:
            sent.add(key)
            try:
                subs = set(json.loads(SUBS.read_text(encoding="utf-8"))) if SUBS.exists() else set()
                for c in list(subs | ({OWNER} if OWNER else set())):
                    try:
                        send(c, briefing_text(key, key, "", lang_load().get(str(c), "vi")))
                    except Exception:
                        continue
            except Exception:
                pass
        time.sleep(300)


def main():
    threading.Thread(target=daily_loop, daemon=True).start()
    port = int(os.environ.get("PORT", "10000"))
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), H).serve_forever(), daemon=True).start()
    print(f"cloud bot on :{port}, AI={'gemini' if GEMINI_KEY else 'rule'}", flush=True)
    off = 0
    while True:
        try:
            r = api("getUpdates", {"offset": off, "timeout": 30}, timeout=40)
            for u in r.get("result", []):
                off = u["update_id"] + 1
                m = u.get("message") or {}
                if m.get("chat", {}).get("id") and m.get("text"):
                    try:
                        handle(str(m["chat"]["id"]), m["text"])
                    except Exception as e:
                        print("handle:", e, flush=True)
        except Exception as e:
            print("poll:", e, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
