"""News bot: long-polling Telegram bot, stdlib only (urllib, no pip deps).
Song ngữ Việt / English — mặc định tiếng Việt có dấu. /lang để đổi.

Basic: /start /help /lang /ping /latest /brief /topics /sources /subscribe /unsubscribe
Advanced: /date /range /filter /search /market /status

Heavy commands (/brief /date /range /filter /search) delegate to the
news-impact-scraper skill via `opencode run --auto`.
Light commands answer instantly from local reports / public APIs.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent


def load_dotenv(path: Path):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


load_dotenv(BASE / ".env")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN or "paste" in TOKEN.lower():
    sys.exit("Missing TELEGRAM_BOT_TOKEN in .env")

API = f"https://api.telegram.org/bot{TOKEN}"
SUBS = BASE / "subscribers.json"
LANGF = BASE / "user_lang.json"
REPORTS = BASE / "reports"
PROMPT_FILE = BASE / "daily_prompt.txt"

TOPICS = ["finance", "economy", "stock", "technology", "science", "crypto", "ai"]
SOURCES_VI = (
    "🌍 Toàn cầu: Reuters, Bloomberg, FT, WSJ, CNBC, MarketWatch, TechCrunch, "
    "MIT Tech Review, Nature, CoinDesk / The Block.\n"
    "🇻🇳 Việt Nam: VnExpress, Tuổi Trẻ, Thanh Niên, CafeF, VietStock, VnEconomy, SBV / GSO / HOSE."
)
SOURCES_EN = (
    "🌍 Global: Reuters, Bloomberg, FT, WSJ, CNBC, MarketWatch, TechCrunch, "
    "MIT Tech Review, Nature, CoinDesk / The Block.\n"
    "🇻🇳 Vietnam: VnExpress, Tuoi Tre, Thanh Nien, CafeF, VietStock, VnEconomy, SBV / GSO / HOSE."
)

HELP_VI = """Tôi làm được gì (cơ bản + nâng cao):

🟢 Cơ bản:
/brief [hôm-nay|hôm-qua|YYYY-MM-DD] [chủ-đề] — quét tin + dự báo tác động
  vd: /brief | /brief hôm-qua | /brief 2026-10-10 crypto,ai
/latest — gửi file báo cáo mới nhất
/topics — 7 chủ đề đang theo dõi
/sources — danh sách báo chi tiết
/lang vi|en — đổi ngôn ngữ
/subscribe — nhận briefing 7h sáng hằng ngày
/unsubscribe — hủy nhận tin
/ping — kiểm tra bot còn sống

🔵 Nâng cao:
/date YYYY-MM-DD [chủ-đề] — lọc tin đúng 1 ngày
  vd: /date 2026-10-10 chứng-khoán
/range YYYY-MM-DD YYYY-MM-DD [chủ-đề] — lọc 1 khoảng ngày
  vd: /range 2026-10-01 2026-10-10 vàng,tỷ-giá
/filter <stock|crypto|ai|tech|vang> [ngày] — lọc nhanh theo nhóm
  vd: /filter crypto | /filter stock 2026-10-10
/search <từ-khóa> — tìm tin theo từ khóa + tác động
  vd: /search VN-Index | /search bitcoin ETF
/market — snapshot nhanh BTC / VN-Index / vàng (không dùng LLM)
/status — trạng thái bot + báo cáo + subscriber

⚠️ Không phải lời khuyên tài chính. Mọi link đều đã verify qua webfetch."""

HELP_EN = """What I can do (basic + advanced):

🟢 Basic:
/brief [today|yesterday|YYYY-MM-DD] [topics] — scan news + impact forecast
  e.g. /brief | /brief yesterday | /brief 2026-10-10 crypto,ai
/latest — send the newest report file
/topics — 7 tracked topics
/sources — detailed outlet list
/lang vi|en — switch language
/subscribe — receive the 7AM daily briefing
/unsubscribe — stop notifications
/ping — liveness check

🔵 Advanced:
/date YYYY-MM-DD [topics] — filter exactly one day
/range YYYY-MM-DD YYYY-MM-DD [topics] — filter a date range
/filter <stock|crypto|ai|tech|vang> [date] — quick group filter
/search <keyword> — keyword search + impact
/market — quick BTC / VN-Index / gold snapshot (no LLM)
/status — bot + reports + subscriber status

⚠️ Not financial advice. All links verified via webfetch."""

COMMANDS_MENU = [
    ("brief", "Quét tin + dự báo tác động / Scan news + impact"),
    ("latest", "Báo cáo mới nhất / Newest report"),
    ("date", "Lọc tin 1 ngày / Filter one day"),
    ("range", "Lọc khoảng ngày / Date range"),
    ("filter", "Lọc nhanh stock/crypto/ai/tech/vàng"),
    ("search", "Tìm theo từ khóa / Keyword search"),
    ("market", "Snapshot BTC / VN-Index / vàng"),
    ("topics", "7 chủ đề / 7 topics"),
    ("sources", "Danh sách báo / Outlet list"),
    ("lang", "Đổi ngôn ngữ vi|en / Language"),
    ("subscribe", "Nhận tin 7h sáng / Daily 7AM"),
    ("unsubscribe", "Hủy nhận tin / Unsubscribe"),
    ("status", "Trạng thái / Status"),
    ("help", "Hướng dẫn / Help"),
]

STR = {
    "hello": {
        "vi": "Chào bạn! Tôi là bot tin tức Toàn cầu + Việt Nam (tài chính / chứng khoán / công nghệ / AI / crypto).\nDùng /lang en nếu bạn muốn tiếng Anh.\n\n",
        "en": "Hi! I'm your Global + Vietnam news bot (finance / stocks / tech / AI / crypto).\nUse /lang vi for Vietnamese.\n\n",
    },
    "lang_ok": {"vi": "Đã chuyển sang tiếng Việt có dấu. Gõ /help để xem lệnh.", "en": "Switched to English. Type /help to list commands."},
    "lang_use": {"vi": "Dùng: /lang vi|en", "en": "Usage: /lang vi|en"},
    "topics": {"vi": "7 chủ đề: ", "en": "7 topics: "},
    "sub_ok": {"vi": "Đã đăng ký nhận briefing 7h sáng. Tổng {n} người.", "en": "Subscribed to the 7AM briefing. Total {n}."},
    "unsub_ok": {"vi": "Đã hủy đăng ký.", "en": "Unsubscribed."},
    "no_report": {"vi": "Chưa có báo cáo nào. Dùng /brief để quét.", "en": "No reports yet. Use /brief to scan."},
    "sending": {"vi": "Đang gửi {n} ...", "en": "Sending {n} ..."},
    "file_err": {"vi": "Lỗi gửi file: {e}", "en": "File send error: {e}"},
    "unknown": {"vi": "Lệnh chưa hỗ trợ. Gõ /help.", "en": "Unknown command. Type /help."},
    "use_date": {"vi": "Dùng: /date YYYY-MM-DD [chủ-đề]\nvd: /date 2026-10-10 crypto", "en": "Usage: /date YYYY-MM-DD [topics]\ne.g. /date 2026-10-10 crypto"},
    "bad_day": {"vi": "Ngày không hợp lệ. vd: /date 2026-10-10", "en": "Invalid date. e.g. /date 2026-10-10"},
    "use_range": {"vi": "Dùng: /range YYYY-MM-DD YYYY-MM-DD [chủ-đề]", "en": "Usage: /range YYYY-MM-DD YYYY-MM-DD [topics]"},
    "use_search": {"vi": "Dùng: /search <từ-khóa>\nvd: /search VN-Index", "en": "Usage: /search <keyword>\ne.g. /search VN-Index"},
    "scanning": {"vi": "Đang quét tin {f}..{t} {x} (mất 1–3 phút, bot sẽ gửi kết quả) ...", "en": "Scanning {f}..{t} {x} (takes 1–3 min, results coming) ..."},
    "too_long": {"vi": "Quét tin quá lâu (>15p), thử lại với khoảng ngày hẹp hơn.", "en": "Scan timed out (>15 min), retry with a narrower range."},
    "err": {"vi": "Lỗi: {e}", "en": "Error: {e}"},
    "nofile": {"vi": "(không gửi được file: {e})", "en": "(file failed: {e})"},
}


def lang_load():
    try:
        return json.loads(LANGF.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_lang(chat):
    return lang_load().get(str(chat), "vi")


def set_lang(chat, lang):
    d = lang_load()
    d[str(chat)] = lang
    LANGF.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def T(chat, key, **kw):
    s = STR[key][get_lang(chat)]
    return s.format(**kw) if kw else s


def api(method, params=None, timeout=35):
    url = f"{API}/{method}"
    data = None
    if params:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(chat, text):
    for i in range(0, max(len(text), 1), 4000):
        api("sendMessage", {"chat_id": chat, "text": text[i:i + 4000]})


def send_file(chat, path: Path, caption=""):
    boundary = "----botfile1"
    body = bytearray()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat}\r\n'.encode()
    if caption:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption[:900]}\r\n'.encode("utf-8")
    data = path.read_bytes()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
             f'filename="{path.name}"\r\nContent-Type: text/markdown\r\n\r\n').encode()
    body += data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/sendDocument", data=bytes(body),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()[:200]


def subs_load():
    try:
        return set(json.loads(SUBS.read_text(encoding="utf-8")))
    except Exception:
        return set()


def subs_save(s):
    SUBS.write_text(json.dumps(sorted(s)), encoding="utf-8")


def latest_report():
    files = sorted(REPORTS.glob("briefing-*.md"))
    return files[-1] if files else None


def run_skill(window_from, window_to, extra="", lang="vi"):
    """Invoke opencode skill, return markdown text (may take minutes)."""
    base_prompt = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "@news-impact-scraper"
    lang_line = "Trả lời bằng tiếng Việt có dấu." if lang == "vi" else "Answer in English."
    prompt = (f"{base_prompt}\n\nContext: target date window = {window_from} to {window_to}. "
              f"Today is {datetime.date.today().isoformat()} ICT. HARD RULE: only news published "
              f"inside [{window_from}, {window_to}]. {lang_line} {extra}")
    p = subprocess.run(["opencode", "run", "--auto", prompt],
                       capture_output=True, text=True, timeout=900, cwd=str(BASE))
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    if p.returncode != 0:
        raise RuntimeError(f"opencode exit {p.returncode}: {out[-1000:]}")
    return out.strip() or "(empty output)"


def quick_market(lang):
    """Fast snapshot without LLM: BTC via CoinDesk data API, best-effort."""
    lines = []
    try:
        with urllib.request.urlopen("https://data-api.coindesk.com/index/cc/v1/latest/tick?market=cdc&instruments=BTC-USD",
                                    timeout=15) as r:
            j = json.loads(r.read().decode())
            px = j["Data"]["BTC-USD"]["VALUE_LAST_UPDATE"]
            lines.append(f"BTC: ${px:,.0f} (CoinDesk)")
    except Exception as e:
        lines.append(f"BTC: không lấy được ({type(e).__name__})" if lang == "vi"
                     else f"BTC: unavailable ({type(e).__name__})")
    rep = latest_report()
    if rep:
        lines.append(f"Báo cáo mới nhất: {rep.name}" if lang == "vi" else f"Newest report: {rep.name}")
        txt = rep.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"VN-Index[^\n]{0,120}", txt)
        if m:
            lines.append(m.group(0)[:160])
    else:
        lines.append("Chưa có báo cáo local. Dùng /brief để quét." if lang == "vi"
                     else "No local reports. Use /brief to scan.")
    lines.append("Vàng / USD chi tiết: dùng /filter vang hoặc /search giá vàng" if lang == "vi"
                 else "Gold / USD detail: use /filter vang or /search gold price")
    return "\n".join(lines)


def parse_day(s):
    s = s.strip().lower()
    today = datetime.date.today()
    if s in ("hôm-nay", "hom-nay", "today", "hn"):
        return today.isoformat()
    if s in ("hôm-qua", "hom-qua", "yesterday", "hq"):
        return (today - datetime.timedelta(days=1)).isoformat()
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
    if m:
        d, mo, y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    return None


def handle(chat, text):
    lang = get_lang(chat)
    parts = text.strip().split()
    if not parts:
        return
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    if cmd == "/start":
        send(chat, T(chat, "hello") + (HELP_VI if lang == "vi" else HELP_EN))
    elif cmd == "/help":
        send(chat, HELP_VI if lang == "vi" else HELP_EN)
    elif cmd == "/lang":
        if args and args[0].lower() in ("vi", "en"):
            set_lang(chat, args[0].lower())
            send(chat, STR["lang_ok"][args[0].lower()])
        else:
            send(chat, T(chat, "lang_use"))
    elif cmd == "/ping":
        send(chat, f"pong {datetime.datetime.now().isoformat(timespec='seconds')}")
    elif cmd == "/topics":
        send(chat, T(chat, "topics") + ", ".join(TOPICS))
    elif cmd == "/sources":
        send(chat, SOURCES_VI if lang == "vi" else SOURCES_EN)
    elif cmd == "/subscribe":
        s = subs_load()
        s.add(str(chat))
        subs_save(s)
        send(chat, T(chat, "sub_ok", n=len(s)))
    elif cmd == "/unsubscribe":
        s = subs_load()
        s.discard(str(chat))
        subs_save(s)
        send(chat, T(chat, "unsub_ok"))
    elif cmd == "/status":
        rep = latest_report()
        n = len(list(REPORTS.glob("*.md"))) if REPORTS.exists() else 0
        if lang == "vi":
            send(chat, f"bot: ok\nngôn ngữ: {lang}\nbáo cáo: {n} file\nmới nhất: {rep.name if rep else 'chưa có'}\nsub: {len(subs_load())}")
        else:
            send(chat, f"bot: ok\nlang: {lang}\nreports: {n} files\nlatest: {rep.name if rep else 'none'}\nsubs: {len(subs_load())}")
    elif cmd == "/latest":
        rep = latest_report()
        if not rep:
            send(chat, T(chat, "no_report"))
        else:
            send(chat, T(chat, "sending", n=rep.name))
            try:
                send_file(chat, rep, rep.name)
            except Exception as e:
                send(chat, T(chat, "file_err", e=e))
    elif cmd == "/market":
        send(chat, quick_market(lang))
    elif cmd in ("/brief", "/search", "/date", "/range", "/filter",
                 "/crypto", "/vnecon"):
        try:
            if cmd == "/brief":
                wf = wt = extra = None
                rest = " ".join(args)
                m = re.search(r"\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|hôm-qua|hom-qua|hôm-nay|hom-nay|today|yesterday", rest.lower())
                if m:
                    d = parse_day(m.group(0))
                    wf = wt = d
                    rest = rest.replace(m.group(0), "")
                wf = wf or datetime.date.today().isoformat()
                wt = wt or wf
                extra = f"Focus topics: {rest.strip()}" if rest.strip() else ""
            elif cmd == "/date":
                if not args:
                    send(chat, T(chat, "use_date"))
                    return
                d = parse_day(args[0])
                if not d:
                    send(chat, T(chat, "bad_day"))
                    return
                wf = wt = d
                extra = f"Focus: {' '.join(args[1:])}" if len(args) > 1 else ""
            elif cmd == "/range":
                if len(args) < 2:
                    send(chat, T(chat, "use_range"))
                    return
                wf, wt = parse_day(args[0]), parse_day(args[1])
                if not wf or not wt:
                    send(chat, T(chat, "bad_day"))
                    return
                extra = f"Focus: {' '.join(args[2:])}" if len(args) > 2 else ""
            elif cmd == "/filter":
                grp = (args[0].lower() if args else "stock")
                mapping = {"stock": "stock market, VN-Index, chứng khoán",
                           "crypto": "crypto, bitcoin, ETF",
                           "ai": "AI, OpenAI, agents",
                           "tech": "technology, chips, startups",
                           "vang": "giá vàng, tỷ giá USD, gold"}
                extra = f"Focus ONLY: {mapping.get(grp, grp)}"
                d = parse_day(args[1]) if len(args) > 1 else datetime.date.today().isoformat()
                wf = wt = d
            elif cmd == "/search":
                if not args:
                    send(chat, T(chat, "use_search"))
                    return
                kw = " ".join(args)
                wf = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
                wt = datetime.date.today().isoformat()
                extra = f"Keyword bắt buộc: {kw}. Ưu tiên tin chứa từ khóa trong 7 ngày qua."
            else:
                wf = wt = datetime.date.today().isoformat()
                extra = ""
            send(chat, T(chat, "scanning", f=wf, t=wt, x=extra[:120]))
            out = run_skill(wf, wt, extra, lang)
            stamp = wf if wf == wt else f"{wf}_to_{wt}"
            rep_path = REPORTS / f"briefing-{stamp}.md"
            REPORTS.mkdir(exist_ok=True)
            rep_path.write_text(out, encoding="utf-8")
            send(chat, out[:3800])
            if len(out) > 3800:
                send(chat, out[3800:7600])
            try:
                send_file(chat, rep_path, rep_path.name)
            except Exception as e:
                send(chat, T(chat, "nofile", e=e))
        except subprocess.TimeoutExpired:
            send(chat, T(chat, "too_long"))
        except Exception as e:
            send(chat, T(chat, "err", e=str(e)[:500]))
    else:
        send(chat, T(chat, "unknown"))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--register-commands", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        print("commands:", ", ".join(c for c, _ in COMMANDS_MENU))
        print("help_vi chars:", len(HELP_VI))
        print("help_en chars:", len(HELP_EN))
        print("reports:", len(list(REPORTS.glob("*.md"))) if REPORTS.exists() else 0)
        return
    if args.register_commands:
        cmds = [{"command": c, "description": d} for c, d in COMMANDS_MENU]
        data = json.dumps({"commands": cmds}).encode()
        req = urllib.request.Request(f"{API}/setMyCommands", data=data,
                                     headers={"Content-Type": "application/json"})
        print(urllib.request.urlopen(req, timeout=20).read().decode()[:300])
        return
    print("polling...", flush=True)
    offset = 0
    while True:
        try:
            res = api("getUpdates", {"offset": offset, "timeout": 30}, timeout=40)
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message") or {}
                chat = (msg.get("chat") or {}).get("id")
                text = msg.get("text", "")
                if chat and text:
                    print(f"<- {chat}: {text[:80]}", flush=True)
                    try:
                        handle(str(chat), text)
                    except Exception as e:
                        print("handle err:", e, flush=True)
        except Exception as e:
            print("poll err:", e, flush=True)
            import time
            time.sleep(5)


if __name__ == "__main__":
    main()
