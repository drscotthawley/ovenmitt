#!/usr/bin/env python3
# ovenmitt.py — usage: python ovenmitt.py [--email] [--imsg] [--auth]
# See README.md for setup instructions.
import os, re, sys, uuid, sqlite3, argparse, requests, msal
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
# ── Config ────────────────────────────────────────────────────────────────────
def _require(var):
    v = os.getenv(var)
    if not v: print(f"ERROR: ${var} not set. Add it to ~/.bashrc and re-source."); sys.exit(1)
    return v
TENANT_ID    = lambda: _require("OVENMITT_TENANT_ID")
EMAIL        = lambda: _require("OVENMITT_EMAIL")
CLIENT_ID    = os.getenv("OVENMITT_CLIENT_ID", "d3590ed6-52b3-4102-aeff-aad2292ab01c")
TOKEN_CACHE  = os.path.expanduser(os.getenv("OVENMITT_TOKEN_CACHE", "~/.ovenmitt_token_cache.json"))
OLLAMA_URL   = os.getenv("OVENMITT_OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OVENMITT_OLLAMA_MODEL", "qwen2.5:32b")
OUTPUT_DIR   = Path(os.path.expanduser(os.getenv("OVENMITT_OUTPUT_DIR", "~/ovenmitt_drafts")))
OLLAMA_TIMEOUT = 120; EXCHANGE_MAX_EMAILS = 10; EXCHANGE_FILTER_DOMAINS = []
IMESSAGE_DB  = os.path.expanduser("~/Library/Messages/chat.db")
IMESSAGE_DAYS_BACK = 7; IMESSAGE_CTX_MESSAGES = 20
MSG_START = "<<<OVENMITT_MSG_START:{uuid}>>>"; MSG_END = "<<<OVENMITT_MSG_END>>>"
_spf  = os.path.expanduser(os.getenv("OVENMITT_SYSTEM_PROMPT_FILE", "~/.ovenmitt_prompt.txt"))
_base = "You draft replies for a university professor. Professional, warm, concise.\nNo filler openers. Flag scheduling gaps with [VERIFY: <what>]. Reply body only."
SYSTEM_PROMPT = (open(_spf).read().strip() + "\n\n" if os.path.exists(_spf) else "") + _base
# ── Auth ──────────────────────────────────────────────────────────────────────
SCOPES = ["Mail.Read", "Mail.ReadWrite", "offline_access"]
def get_token():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE): cache.deserialize(open(TOKEN_CACHE).read())
    app = msal.PublicClientApplication(CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID()}", token_cache=cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if not result or "access_token" not in result:
        print("No cached token — opening browser for login...")
        result = app.acquire_token_interactive(scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error_description','unknown')}")
    if cache.has_state_changed:
        open(TOKEN_CACHE, "w").write(cache.serialize()); os.chmod(TOKEN_CACHE, 0o600)
    return result["access_token"]
# ── Exchange mail ─────────────────────────────────────────────────────────────
GRAPH = "https://graph.microsoft.com/v1.0"
@dataclass
class Email:
    id: str; subject: str; sender_name: str; sender_email: str
    received: str; body_text: str; conversation_id: str
    thread_context: List[dict] = field(default_factory=list)
def _gh(token):  return {"Authorization": f"Bearer {token}"}
def _txt(body):  return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body.get("content",""))).strip()
def get_emails(token):
    params = {"$filter": "isRead eq false", "$orderby": "receivedDateTime desc",
              "$top": EXCHANGE_MAX_EMAILS, "$select": "id,subject,sender,receivedDateTime,body,conversationId"}
    msgs = requests.get(f"{GRAPH}/me/mailFolders/inbox/messages", headers=_gh(token), params=params)
    msgs.raise_for_status()
    emails = []
    for m in msgs.json().get("value", []):
        addr = m["sender"]["emailAddress"]["address"]
        if EXCHANGE_FILTER_DOMAINS and addr.split("@")[-1] not in EXCHANGE_FILTER_DOMAINS: continue
        thread = requests.get(f"{GRAPH}/me/messages", headers=_gh(token), params={
            "$filter": f"conversationId eq '{m['conversationId']}'",
            "$orderby": "receivedDateTime desc", "$top": 5,
            "$select": "id,sender,receivedDateTime,bodyPreview"
        }).json().get("value", [])
        emails.append(Email(m["id"], m.get("subject","(no subject)"),
            m["sender"]["emailAddress"]["name"], addr, m["receivedDateTime"],
            _txt(m.get("body",{})), m["conversationId"],
            [x for x in thread if x["id"] != m["id"]]))
    return emails
# ── iMessage ──────────────────────────────────────────────────────────────────
APPLE_EPOCH = 978307200
@dataclass
class Thread:
    contact: str; display_name: str; messages: List[dict]; last_active: datetime
def _ts(t): return datetime.fromtimestamp(t / 1e9 + APPLE_EPOCH)
def get_imessage_threads():
    if not os.path.exists(IMESSAGE_DB):
        raise FileNotFoundError(f"DB not found: {IMESSAGE_DB}\nGrant Full Disk Access to Terminal.")
    conn = sqlite3.connect(f"file:{IMESSAGE_DB}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cutoff = int((datetime.now().timestamp() - timedelta(days=IMESSAGE_DAYS_BACK).total_seconds() - APPLE_EPOCH) * 1e9)
    cur.execute("""SELECT DISTINCT c.ROWID as chat_id, c.chat_identifier, c.display_name
        FROM chat c JOIN chat_message_join cmj ON c.ROWID=cmj.chat_id
        JOIN message m ON cmj.message_id=m.ROWID WHERE m.date>? ORDER BY m.date DESC""", (cutoff,))
    threads = []
    for chat in cur.fetchall():
        cur.execute("""SELECT m.text, m.date, m.is_from_me, h.id as handle_id
            FROM message m JOIN chat_message_join cmj ON m.ROWID=cmj.message_id
            LEFT JOIN handle h ON m.handle_id=h.ROWID
            WHERE cmj.chat_id=? ORDER BY m.date DESC LIMIT ?""", (chat["chat_id"], IMESSAGE_CTX_MESSAGES))
        rows = cur.fetchall()
        msgs = [{"sender": "me" if r["is_from_me"] else (r["handle_id"] or chat["chat_identifier"]),
                 "text": r["text"], "timestamp": _ts(r["date"]).isoformat()}
                for r in reversed(rows) if r["text"]]
        if msgs: threads.append(Thread(chat["chat_identifier"],
            chat["display_name"] or chat["chat_identifier"], msgs, _ts(rows[0]["date"])))
    conn.close()
    return threads
# ── LLM ───────────────────────────────────────────────────────────────────────
def draft(context, message):
    payload = {"model": OLLAMA_MODEL, "stream": False, "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": f"CONTEXT:\n{context}\n\n---\nMESSAGE:\n{message}\n\n---\nDraft a reply."}]}
    return requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT).json()["message"]["content"].strip()
def ollama_running():
    try:    return requests.get(OLLAMA_URL.replace("/api/chat","") + "/api/tags", timeout=5).ok
    except: return False
# ── Output ────────────────────────────────────────────────────────────────────
def _write(content):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_drafts.md"
    with open(fname, "a") as f: f.write(content)
    return fname
def write_email_draft(email, reply):
    uid = str(uuid.uuid4())[:8]
    ctx = "\n".join(f"[{m['receivedDateTime'][:10]}] {m['sender']['emailAddress']['name']}: {m['bodyPreview']}"
                    for m in email.thread_context)
    return _write(f"\n{MSG_START.format(uuid=uid)}\n"
        f"**Email** | {email.sender_name} <{email.sender_email}> | {email.subject}\n\n"
        f"### Original\n{email.body_text[:500]}{'...' if len(email.body_text)>500 else ''}\n\n"
        f"### Draft Reply\n{reply}\n{MSG_END}\n"), uid
def write_imessage_draft(thread, reply):
    uid = str(uuid.uuid4())[:8]
    ctx = "\n".join(f"[{m['timestamp'][:16]}] {m['sender']}: {m['text']}" for m in thread.messages[-5:])
    return _write(f"\n{MSG_START.format(uuid=uid)}\n"
        f"**iMessage** | {thread.display_name} | last active {thread.last_active.strftime('%m/%d %H:%M')}\n\n"
        f"### Thread\n{ctx}\n\n"
        f"### Draft Reply\n{reply}\n{MSG_END}\n"), uid
# ── Main ──────────────────────────────────────────────────────────────────────
def process_emails(token):
    print("\n📬 Fetching unread emails...")
    emails = get_emails(token); print(f"   {len(emails)} unread.")
    for e in emails:
        print(f"   → {e.sender_name}: {e.subject[:60]}")
        ctx = "\n".join(f"[{m['receivedDateTime'][:10]}] {m['sender']['emailAddress']['name']}: {m['bodyPreview']}"
                        for m in e.thread_context)
        path, uid = write_email_draft(e, draft(ctx, e.body_text)); print(f"   ✓ {path} [{uid}]")
def process_imessages():
    print("\n💬 Reading iMessage threads...")
    try:    threads = get_imessage_threads()
    except Exception as e: print(f"   ⚠️  {e}"); return
    needs_reply = [t for t in threads if t.messages and t.messages[-1]["sender"] != "me"]
    print(f"   {len(needs_reply)} thread(s) may need a reply.")
    for t in needs_reply:
        print(f"   → {t.display_name} ({t.last_active.strftime('%m/%d %H:%M')})")
        ctx = "\n".join(f"{m['sender']}: {m['text']}" for m in t.messages[:-1])
        path, uid = write_imessage_draft(t, draft(ctx, t.messages[-1]["text"])); print(f"   ✓ {path} [{uid}]")
def main():
    p = argparse.ArgumentParser(description="OvenMitt")
    p.add_argument("--email", action="store_true"); p.add_argument("--imsg", action="store_true")
    p.add_argument("--auth",  action="store_true")
    args = p.parse_args()
    do_email = args.email or not (args.email or args.imsg)
    do_imsg  = args.imsg  or not (args.email or args.imsg)
    print(f"\n🧤 OvenMitt — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if not args.auth and not ollama_running():
        print("⚠️  Ollama not running. Start with: ollama serve"); sys.exit(1)
    token = None
    if do_email or args.auth:
        print("\n🔑 Authenticating with Exchange...")
        token = get_token(); print("   ✓ Authenticated.")
        if args.auth: return
    if do_email and token: process_emails(token)
    if do_imsg:            process_imessages()
    print(f"\n✅ Done. Drafts in: {OUTPUT_DIR}\n")
if __name__ == "__main__": main()
