# OvenMitt

Async personal email/iMessage draft assistant. Uses a local LLM (via Ollama) to draft replies to your emails and messages. You always review before anything gets sent — OvenMitt never sends on your behalf.

---

## What you need before starting

- A Mac (iMessage integration is macOS-only)
- Python 3 (comes pre-installed on modern Macs — verify by opening Terminal and typing `python3 --version`)
- [Ollama](https://ollama.com) installed with a model downloaded
- A Microsoft 365 / Exchange email account

---

## Step 1 — Install Python packages

Open the Terminal app (search for it in Spotlight with Cmd+Space). Navigate to the folder where you put the OvenMitt files, then run:

```bash
pip3 install -r requirements.txt
```

If you get a permissions error, try:
```bash
pip3 install --user -r requirements.txt
```

---

## Step 2 — Install Ollama and download a model

1. Go to https://ollama.com and download the Mac app. Install it like any normal Mac app.
2. Once installed, open Terminal and run:

```bash
ollama pull qwen2.5:32b
```

This downloads the AI model (~20GB). It will take a while on a slow connection. If your machine has less than 32GB RAM, use a smaller model instead:

```bash
ollama pull qwen2.5:14b    # for 16GB RAM machines
ollama pull qwen2.5:7b     # for 8GB RAM machines
```

If you use a different model, update the `OVENMITT_OLLAMA_MODEL` environment variable (see Step 3).

---

## Step 3 — Set up environment variables

OvenMitt reads its configuration from environment variables so that no secrets ever end up in the code or on GitHub.

Open Terminal and run:
```bash
nano ~/.zshrc
```
(If you're on an older Mac using bash, use `~/.bashrc` instead.)

Scroll to the bottom of the file and add these lines:

```bash
# OvenMitt
export OVENMITT_TENANT_ID="your-azure-tenant-id"
export OVENMITT_EMAIL="you@youruniversity.edu"
```

Replace the values with your actual email address and tenant ID (see below for how to find the tenant ID). Save the file with Ctrl+O, then Enter, then Ctrl+X to exit.

Then reload your shell config:
```bash
source ~/.zshrc
```

### How to find your Microsoft Tenant ID

1. Go to https://portal.azure.com and sign in with your university account
2. In the search bar at the top, search for "Azure Active Directory"
3. On the overview page, you'll see "Tenant ID" — copy that value

If you can't access the Azure portal, ask your IT department for your "Microsoft 365 Tenant ID."

### Optional environment variables

You only need these if you want to change the defaults:

```bash
export OVENMITT_OLLAMA_MODEL="qwen2.5:32b"         # change if using a different model
export OVENMITT_OUTPUT_DIR="~/ovenmitt_drafts"      # where draft files are saved
export OVENMITT_TOKEN_CACHE="~/.ovenmitt_token_cache.json"  # where auth token is cached
export OVENMITT_SYSTEM_PROMPT_FILE="~/.ovenmitt_prompt.txt" # custom instructions for the LLM
```

---

## Step 4 — Set up your custom instructions (optional but recommended)

OvenMitt looks for a plain text file at `~/.ovenmitt_prompt.txt`. If it exists, its contents are prepended to the instructions sent to the LLM. This is where you tell it about your communication style, your name, your role, etc.

A starter file is included as `ovenmitt_prompt.txt`. Copy it to your home directory:

```bash
cp ovenmitt_prompt.txt ~/.ovenmitt_prompt.txt
```

Then edit it to your liking:
```bash
nano ~/.ovenmitt_prompt.txt
```

---

## Step 5 — Authenticate with Exchange (first time only)

Run this once to log in to your university email account:

```bash
python3 ovenmitt.py --auth
```

A browser window will open. Log in with your university SSO credentials and approve the MFA push notification on your phone, exactly as you normally would. Once done, the auth token is saved locally and silently refreshed for the next 30–90 days (depending on your university's IT policy). You may occasionally need to re-run `--auth` when the token expires.

---

## Step 6 — Grant iMessage access (optional)

For OvenMitt to read your iMessages, macOS needs to give Python permission to access the Messages database.

1. Open **System Settings** (the gear icon in your Dock)
2. Go to **Privacy & Security**
3. Scroll down and click **Full Disk Access**
4. Click the **+** button
5. Navigate to `/usr/bin/` and add `python3`
   - You may also need to add Terminal itself: go to `/Applications/Utilities/Terminal.app`

If you skip this step, OvenMitt will still work for email — it'll just warn you that iMessages are unavailable.

---

## Step 7 — Start Ollama

Before running OvenMitt, make sure Ollama is running. You can either:
- Open the Ollama app from your Applications folder, or
- Run in Terminal: `ollama serve`

OvenMitt will tell you if Ollama isn't running when you try to start it.

---

## Running OvenMitt

```bash
python3 ovenmitt.py           # process both email and iMessages
python3 ovenmitt.py --email   # email only
python3 ovenmitt.py --imsg    # iMessages only
python3 ovenmitt.py --auth    # re-authenticate Exchange and exit
```

---

## Reading your drafts

Drafts are saved to `~/ovenmitt_drafts/` as a markdown file named with today's date, e.g. `2026-02-23_drafts.md`. You can open this in any text editor. Each draft looks like this:

```
<<<OVENMITT_MSG_START:abc12345>>>
**Email** | Jane Student <jane@uni.edu> | Re: Project deadline

### Original
Hi Professor, I wanted to ask about...

### Draft Reply
Hi Jane, thanks for reaching out...
<<<OVENMITT_MSG_END>>>
```

Review the draft, copy the suggested reply, paste it into your email client, edit as needed, and send. OvenMitt never touches your sent mail.

---

## Running automatically every 15 minutes

To have OvenMitt check for new messages periodically, add it to your crontab.

Open Terminal and run:
```bash
crontab -e
```

This opens a text editor. Add this line (replacing the path with wherever you put ovenmitt.py):
```
*/15 * * * * /usr/bin/python3 /Users/yourname/ovenmitt/ovenmitt.py 2>>/tmp/ovenmitt.log
```

Save and exit. OvenMitt will now run every 15 minutes. To check if it's working, look at the log file:
```bash
cat /tmp/ovenmitt.log
```

If you only want it to run when your laptop is plugged into power, you can use a launchd plist instead of cron — search "launchd RequiresACPower" for instructions, or ask an AI assistant to generate the plist for you.

---

## Security notes

OvenMitt runs as your user account and has the same access to your files that you do. A few things worth knowing:

- **It never sends anything.** It only reads mail/messages and writes draft files. Sending is always manual.
- **No secrets in the code.** All credentials are environment variables. The code is safe to post on GitHub as-is.
- **The auth token** is stored in `~/.ovenmitt_token_cache.json` with permissions set so only you can read it.
- **iMessage access** requires Full Disk Access, which is broad. If that bothers you, run OvenMitt with `--email` only and skip iMessage.
- **The draft files** contain your email/message content in plain text. Store them somewhere sensible and don't sync them to a public cloud.

---

## Troubleshooting

**"ERROR: $OVENMITT_TENANT_ID not set"** — You haven't set the environment variables yet, or you need to run `source ~/.zshrc` to reload them.

**"Ollama not running"** — Open the Ollama app or run `ollama serve` in a separate Terminal window.

**"DB not found / Grant Full Disk Access"** — Follow Step 6 above to grant iMessage permissions.

**Auth browser doesn't open** — Try running `python3 ovenmitt.py --auth` directly in Terminal rather than from an IDE or script runner.

**Drafts look wrong / LLM is confused** — Edit your `~/.ovenmitt_prompt.txt` to give the model more context about who you are and how you like to communicate.
