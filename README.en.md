# RQrun MCP

[中文](README.md) | English

Connect **RQrun (rq.run)** training data to your AI assistant, so it can answer "how far did I run this year", "analyze yesterday's run", or "am I overtraining this week" — without exporting files or taking screenshots.

> Read-only. It never modifies or deletes your records, and **never touches your password**.

```
You:  How far have I run this year?
AI:   (calls get_period_stats) 471.3 km across 83 runs, average pace 6'58"/km…
```

---

## What it can do

| Ask like this | Tool used |
|---|---|
| How far did I run today / yesterday | `list_activities` |
| Analyze yesterday's run — was my pace steady? | `get_activity` |
| Chart my splits and heart rate | `render_chart` |
| How much did I run this month | `get_period_stats` |
| Am I overtraining this week | `get_training_status` |
| What marathon time am I currently capable of | `get_runlevel` |
| Am I doing too much easy volume or too little intensity | `get_intensity` |
| Which days did I run this month | `get_calendar` |
| My max HR, PBs, RQ coin balance | `get_profile` |

Charts are rendered as PNG inside the server — no browser automation or extra tooling on the user's machine.

---

## Supported clients

Same server, five clients — only the config file location differs.

| Client | Config location | Notes |
|---|---|---|
| **Claude Code** | `~/.claude.json` (user) or `.mcp.json` (project) | or `claude mcp add` |
| **Codex CLI** | `~/.codex/config.toml` → `[mcp_servers.rqrun]` | TOML format |
| **ZCode** | `~/.zcode/cli/config.json` (`mcp.servers`) | can also import from Claude Code / Codex |
| **WorkBuddy** | `~/.workbuddy/mcp.json` | paste JSON in the UI |
| **DeepSeek Harness** | profile's `cordis.patch.yml` | via `@deepseek-ai/dsh-mcp-client` |
| Universal | `~/.agents/mcp.json` | cross-tool convention |

Per-client walkthroughs: [`docs/`](docs/).

---

## Quick start

### Option 1 — one-shot installer (recommended)

```bash
git clone https://github.com/<your-username>/rqrun-mcp.git
cd rqrun-mcp
./install.sh
```

The script does four things:

```
[1/4] locate Python (3.11+)
[2/4] create .venv and install deps (mcp / websockets / pillow) — nothing system-wide
[3/4] open a login window; you sign in once
[4/4] detect installed clients and write their MCP config
```

Configure a single client:

```bash
./install.sh --client=claude      # claude / codex / zcode / workbuddy / dsh
```

On macOS you can also just double-click `install.command`.

### Option 2 — manual

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python rq_mcp.py login
```

Then add this to your client's MCP config (use absolute paths):

```json
{
  "mcpServers": {
    "rqrun": {
      "command": "/absolute/path/rqrun-mcp/.venv/bin/python",
      "args": ["/absolute/path/rqrun-mcp/rq_mcp.py"]
    }
  }
}
```

---

## How login works

`login` opens a **separate Chrome window** (your everyday browser is untouched):

1. Sign in to RQrun normally — password, SMS code, or WeChat QR
2. The window closes automatically and the session cookie is saved to `~/.rq-mcp/session.json` (mode 600)
3. Valid for ~30 days; when it expires just say "log in to RQrun" in chat

> Do not press F12 in that window. RQrun ships an anti-debugging script that blanks the page when DevTools opens. The login helper blocks that script; normal sign-in is unaffected.

**Your password only ever goes to RQrun's own login page.** The tool stores only the session cookie.

---

## Tools (10, all read-only)

| Tool | Purpose |
|---|---|
| `list_activities` | Activity list, filterable by date and sport |
| `get_activity` | One activity: splits, HR zones, optional per-second streams |
| `render_chart` | Chart images: per-km pace/HR, or weekly volume |
| `get_period_stats` | Year / month / week / custom / lifetime aggregates |
| `get_training_status` | Fitness, fatigue, form (≈CTL/ATL/TSB) and recovery time |
| `get_runlevel` | Current runlevel, percentile, race predictions |
| `get_intensity` | Time and load per intensity zone, cadence/stride/ground-contact |
| `get_calendar` | Daily summary for a given month |
| `get_profile` | Max/resting HR, zones, PBs, RQ coin balance |
| `login` | Open the login window |

Intentionally **not** exposed: sending SMS codes, deleting records, renaming, logging out, or any other write operation.

---

## Privacy

- All requests go from **your machine** directly to `rq.run`; no third-party server involved
- Credentials live only in `~/.rq-mcp/session.json` (mode 600) and are never committed
- The repo contains no user data; `.gitignore` excludes `.venv/`, `session.json`, `charts/`

---

## FAQ

**"Login expired"** — say "log in to RQrun" in chat, or re-run `./install.sh`.

**Windows / Linux?** — the automatic login window is macOS-only. Elsewhere use:

```bash
# macOS / Linux
./.venv/bin/python rq_mcp.py login --manual
# Windows (PowerShell)
.venv\Scripts\python.exe rq_mcp.py login --manual
```

Note the interpreter path differs per platform: `.venv/bin/python` on macOS/Linux, `.venv\Scripts\python.exe` on Windows. Use the matching path as `command` in your MCP config.

**Does it upload my data?** — The tool itself only talks to `rq.run`; there is no third-party relay. But the data it returns goes into **your AI client's conversation**, so a cloud model provider processes it under their terms — the same as pasting the numbers into the chat yourself.

**Where is data stored locally?** `~/.rq-mcp/session.json` (session cookie, mode 600) and `~/.rq-mcp/chrome-profile/` (a dedicated browser profile used only for login; delete the folder to remove all of it).

More: [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Layout

```
rqrun-mcp/
├── rq_mcp.py            # server: login + 10 tools + chart rendering
├── install.sh           # one-shot installer
├── install.command      # macOS double-click wrapper
├── requirements.txt
├── docs/                # per-client guides
├── examples/            # copy-paste config samples
└── dsh-bundle/          # DeepSeek Harness bundle form
```

---

## Disclaimer

An unofficial third-party tool, not affiliated with RQrun. It reads **your own account's** data through public web endpoints. Respect RQrun's terms of service; do not use it for bulk scraping or commercial purposes.

## License

MIT
