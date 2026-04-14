# Twitter to Bluesky Repost Bot

Automatically mirror tweets from a Twitter (X) account to Bluesky — including images, alt text, and link-card previews.

---

## Features

- Fetches the latest tweets (excluding retweets and replies) via the Twitter API v2
- Reposts each new tweet to Bluesky using the AT Protocol SDK
- Downloads and re-uploads tweet images (up to 4 per post) with alt text preserved
- Resolves t.co short URLs to their expanded form
- Creates rich link-card embeds (`app.bsky.embed.external`) for tweets that contain URLs but no images
- Applies clickable link facets to URLs in post text
- Truncates posts that exceed Bluesky's 300-grapheme limit with an ellipsis
- Tracks previously reposted tweet IDs in a JSON state file (capped at 100 entries)
- Caches the Twitter numeric user ID to avoid redundant API lookups
- Supports Bluesky session-string reuse to reduce password-based logins
- Runs via GitHub Actions, triggered either by schedule or by `workflow_dispatch`
  - Optional: Use `scripts/trigger-mirror.sh` to trigger from a local cron job for more reliable scheduling

---

## Project Structure

```text
├── main.py                          # Thin orchestrator: loads config, runs the pipeline
├── bot/
│   ├── __init__.py
│   ├── config.py                    # Environment variable loading and validation
│   ├── state.py                     # Seen-ID persistence and Twitter user-ID cache
│   ├── twitter_client.py            # TwitterClient: wraps tweepy for API v2
│   ├── bluesky_client.py            # BlueskyClient: posting with images, link cards, facets
│   ├── media.py                     # Image downloading and Open Graph metadata extraction
│   └── text.py                      # URL resolution, grapheme-aware truncation, TextBuilder
├── requirements.txt                 # Pinned Python dependencies
├── seen_ids.json                    # State file (auto-managed, committed by CI)
├── scripts/
│   └── trigger-mirror.sh            # Optional: Local cron script to dispatch the workflow more reliably than GitHub's schedule event
└── .github/
    └── workflows/
        ├── ci.yml                   # Runs linters and unit tests on push and PR
        └── run-mirror.yml           # GitHub Actions workflow
```

---

## Tech Stack

| Layer | Tool |
| ----- | ---- |
| Language | Python 3.10+ |
| Twitter API | [tweepy](https://pypi.org/project/tweepy/) (v2 Client, Bearer Token auth) |
| Bluesky API | [atproto](https://pypi.org/project/atproto/) (AT Protocol SDK) |
| Link cards | [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) + [requests](https://pypi.org/project/requests/) for OG metadata |
| Local dev | [python-dotenv](https://pypi.org/project/python-dotenv/) (`.env` file support) |
| CI / Scheduling | GitHub Actions |

---

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/bskybot-sjearthquakes.git
cd bskybot-sjearthquakes
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Initialize the state file

If `seen_ids.json` doesn't already exist:

```bash
echo '{"seen_ids": []}' > seen_ids.json
```

---

## Configuration

The bot reads credentials from environment variables. For local development, create a `.env` file in the project root (loaded automatically via `python-dotenv`).

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `TWITTER_HANDLE` | Yes | X/Twitter username to mirror (without `@`) |
| `TWITTER_BEARER_TOKEN` | Yes | Twitter API v2 Bearer Token |
| `BLUESKY_HANDLE` | Yes | Bluesky handle (e.g. `you.bsky.social`) |
| `BLUESKY_PASSWORD` | Yes | Bluesky App Password (recommended) or account password |
| `BLUESKY_SESSION` | No | Exported session string for token-based re-auth |

### Local `.env` example

```bash
TWITTER_HANDLE=your_handle
TWITTER_BEARER_TOKEN=AAAAAAAA...
BLUESKY_HANDLE=you.bsky.social
BLUESKY_PASSWORD=your_app_password
```

### GitHub Actions

Add each variable as a **repository secret** under **Settings > Secrets and variables > Actions**.

---

## Running Locally

With your environment activated and variables set:

```bash
python main.py
```

Sample output:

```text
2026-04-09 12:00:00  INFO      bot.twitter_client  Fetched 3 tweets from @your_handle
2026-04-09 12:00:01  INFO      bot.bluesky_client  Logged in to Bluesky as you.bsky.social
2026-04-09 12:00:01  INFO      root  Reposting tweet 192463010857...: Check out our latest match recap...
2026-04-09 12:00:02  INFO      bot.bluesky_client  Posted to Bluesky: Check out our latest match recap...
2026-04-09 12:00:02  INFO      root  Done - 1 new post(s)
```

---

## GitHub Actions Deployment

The workflow at `.github/workflows/run-mirror.yml`:

- Triggered via `workflow_dispatch` (manual or automated) or `schedule` (automatic)
- Only commits `seen_ids.json` back to the repo **when it actually changes**
- Requires "Read and write repository contents" under **Settings > Actions > General**

### Local cron trigger

GitHub's built-in `schedule` event trigger is best-effort and *will* delay and drop runs.
For more reliable scheduling at short intervals, a local cron job can be used to execute `scripts/trigger-mirror.sh`, which dispatches the workflow via the `gh` CLI.

**Prerequisites:**

- `gh` CLI installed and authenticated (`gh auth login`) with `actions:write` scope

**Setup (WSL / Linux / macOS):**

```bash
chmod +x scripts/trigger-mirror.sh
crontab -e
```

Add the following line (runs every 10 minutes at `:00, :10, …, :50` during hours 0–5 and 16–23 UTC) or edit the schedule as desired:

```bash
*/10 0-5,16-23 * * * /absolute/path/to/scripts/trigger-mirror.sh >> ~/mirror-trigger.log 2>&1
```

---

## How It Works

1. **Config** — `bot/config.py` loads and validates environment variables
2. **Twitter fetch** — `TwitterClient` resolves the username to a numeric ID (cached after first lookup), then fetches recent tweets with media expansions and URL entities via `tweepy`
3. **Deduplication** — Each tweet ID is checked against `seen_ids.json`; already-posted tweets are skipped
4. **Text processing** — `bot/text.py` expands t.co URLs, strips media-only links, and truncates to 300 graphemes if needed
5. **Media pipeline** — `bot/media.py` downloads tweet images and extracts Open Graph metadata for link cards
6. **Bluesky post** — `BlueskyClient` builds the appropriate embed (images or external link card), constructs rich-text facets for URLs, and posts via the AT Protocol SDK
7. **State persistence** — Updated seen IDs are saved (capped at 100) and committed to the repo by CI

---

## Obtaining API Credentials

### Twitter API v2

1. Sign up for a Developer account at [developer.x.com](https://developer.x.com/)
2. Create a new App within a Project
3. Copy your **Bearer Token** from the "Keys and tokens" page

### Bluesky

1. Sign up at [bsky.app](https://bsky.app/)
2. Generate an **App Password** under Settings > Privacy and Security > App Passwords (recommended over your main password)

---

## Future Enhancements

- Video and GIF media support
- Threading for tweets that exceed Bluesky's character limit
- Persisting the Bluesky session string across CI runs

---

## License

This project is open-source and available under the [MIT License](LICENSE).
