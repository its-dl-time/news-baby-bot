"""Send briefing to Telegram via Bot API. Zero third-party deps (urllib only)."""
import argparse
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def md_table_to_text(md: str, max_rows: int = 30) -> str:
    """Compact the markdown table into short lines for Telegram (4096 char limit)."""
    lines = []
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            # skip header row, keep data rows compact: # | cat | title | impact
            if cells[0].lower() in ("#", "stt"):
                continue
            if len(cells) >= 7:
                try:
                    lines.append(f"{cells[0]}. [{cells[1]}] {cells[3]} — {cells[6]}")
                except IndexError:
                    lines.append(" | ".join(cells))
            else:
                lines.append(" | ".join(cells))
            if len(lines) >= max_rows:
                break
    return "\n".join(lines)


def split_msg(text: str, limit: int = 4000):
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 0:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def api_get(token: str, method: str, params: dict) -> str:
    url = f"https://api.telegram.org/bot{token}/{method}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def api_post_multipart(token: str, method: str, fields: dict, file_field: str, file_path: Path):
    boundary = "----briefing1234"
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    data = file_path.read_bytes()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_path.name}"\r\nContent-Type: text/markdown\r\n\r\n'
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--env", default="")
    ap.add_argument("--mode", default="summary+file",
                    help="summary+file | summary | file")
    args = ap.parse_args()

    base = Path(__file__).resolve().parent
    load_dotenv(Path(args.env) if args.env else base / ".env")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or "paste" in token.lower():
        sys.exit(
            "Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env.\n"
            "1) Chat @BotFather on Telegram -> /newbot -> copy token.\n"
            "2) Chat @userinfobot to get your chat id (or send a msg to your bot then open "
            "https://api.telegram.org/bot<TOKEN>/getUpdates to read chat.id).\n"
            "3) Fill .env and retry."
        )
    # broadcast to owner + all /subscribe users
    targets = [chat_id]
    try:
        subs = base / "subscribers.json"
        if subs.exists():
            import json as _json
            for s in _json.loads(subs.read_text(encoding="utf-8")):
                if str(s) not in targets:
                    targets.append(str(s))
    except Exception as e:
        print(f"subs load skip: {e}")

    report = Path(args.report)
    md = report.read_text(encoding="utf-8")
    date = report.stem.replace("briefing-", "")

    # 1) summary message(s)
    if args.mode in ("summary+file", "summary"):
        # top section = everything before first table row, plus compact rows
        rows = md_table_to_text(md)
        summary = f"Daily Briefing {date} (Global+VN: finance/stocks/tech/AI/crypto)\n\n{rows[:3000]}"
        # append Top 3 if present
        m = re.search(r"(Top 3.*$)", md, re.S | re.I)
        if m:
            extra = m.group(1)[:1000]
            summary += f"\n\nTop: {extra}"
        summary += "\n\nFull file attached below. Not financial advice."
        for tgt in targets:
            for part in split_msg(summary):
                print(api_get(token, "sendMessage", {"chat_id": tgt, "text": part})[:200])

    # 2) full markdown as document
    if args.mode in ("summary+file", "file"):
        for tgt in targets:
            print(api_post_multipart(
                token, "sendDocument",
                {"chat_id": tgt, "caption": f"Full briefing {date}"},
                "document", report,
            )[:200])

    print(f"Sent {report.name} to {len(targets)} chat(s)")


if __name__ == "__main__":
    main()
