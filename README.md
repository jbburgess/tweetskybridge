# TweetSkyBridge - Twitter to Bluesky Repost Bot

A Python bot that mirrors tweets from a Twitter (X) account to a corresponding Bluesky account, with rich support for embedded media, quote tweets, reply threads, and more.

---

## Features

- Monitors a target Twitter/X account and **reposts new tweets to Bluesky**
  - Fetches the latest tweets (excluding retweets and replies to other accounts) via the Twitter/X API v2
  - Reposts each new tweet to Bluesky using the AT Protocol SDK
- **Handles embedded media**, accounting for less flexible Bluesky media support
  - Downloads tweet media, uploads to Bluesky, and attaches to new Bluesky post, preserving order and alt text, and setting the proper aspect ratio for videos
  - For image-only galleries or single-video posts, mirrors to Bluesky unchanged
  - For mixed or multi-video galleries, posts all images or first video in the main post, then uploads each additional video as a separate reply post, as Bluesky only supports a single video per post and does not support mixed-media posts
- **Accommodates tweets exceeding Bluesky length limitations**
  - Splits tweets longer than 300 graphemes into a main post and threaded follow-up replies to accommodate Bluesky's character limit
  - Ensures that each segment of a split tweet maintains proper threading and media attachments on Bluesky
- Maintains a rolling map of source tweet IDs to the Bluesky posts they produced (capped at 100 entries), enabling:
  - **Cross-run reply threading** — self-reply tweets chain under the mapped Bluesky post even when the parent was posted in an earlier run
  - **Native quote embeds** — self-quote tweets embed the bot's existing Bluesky post (`app.bsky.embed.record`) instead of an external link card back to Twitter
  - **Mirrors the Twitter account's pinned tweet to Bluesky** once per day (first run after UTC midnight): pins the mapped post, replaces it when the pin changes, and unpins when Twitter has no pinned tweet (a pinned tweet older than the mapping is skipped with a warning). Disable with `PIN_SYNC_ENABLED=false`.
- **Rich text feature support**
  - Creates rich link-card embeds (`app.bsky.embed.external`) for tweets that contain URLs but no media (only one embed allowed)
  - Applies clickable link facets to URLs in post text
  - Resolves t.co short URLs to their expanded form, avoiding redirects through Twitter
- **API call efficiency and graceful degradation**
  - Leverages caching and state tracking to reduce unnecessary network requests
  - Graceful degradation for persistent Bluesky media upload errors, mirroring the tweet without media if uploads continue to fail beyond retry window
  - Supports Bluesky session-string reuse to minimize app password logins
- **Multiple deployment options** supported out of the box
  - Run via GitHub Actions, via either `schedule` or manual `workflow_dispatch` triggers
    - *Optional:* Use `scripts/trigger-mirror.sh` to trigger the Actions workflow from a local cron job. Provides more reliable execution than the native Actions `schedule` trigger, while still executing the workflow in GitHub
  - Fully local runs are also supported via `scripts/run_mirror_local.py`, bypassing GitHub Actions entirely.

> Note: If you want to run the bot in GitHub Actions, you will need to fork this repository to a personal repository that you control.

---

## Project Structure

```text
├── main.py                          # Thin orchestrator: loads config, runs the pipeline
├── pytest.ini                       # Pytest configuration
├── requirements.txt                 # Runtime dependencies
├── requirements-dev.txt             # Dev/test tooling dependencies
├── id_map.json                      # State file (auto-managed, committed by CI)
├── bot/
│   ├── __init__.py
│   ├── bluesky_client.py            # Bluesky posting client (text, embeds, media)
│   ├── config.py                    # Environment variable loading and validation
│   ├── media.py                     # Media downloading and Open Graph metadata extraction
│   ├── models.py                    # Typed models for internal tweet/post data
│   ├── state.py                     # Tweet→Bluesky mapping, pin state, and Twitter ID cache
│   ├── text.py                      # URL expansion, grapheme splitting, and TextBuilder
│   ├── twitter_client.py            # Twitter API v2 wrapper (tweepy)
│   └── urls.py                      # URL helpers and domain-specific parsing logic
├── scripts/
│   ├── run_mirror_local.py          # Local runner with optional commit/push workflow
│   └── trigger-mirror.sh            # Optional local cron trigger for Actions workflow_dispatch
├── tests/
│   ├── conftest.py
│   ├── test_bluesky_client.py
│   ├── test_config.py
│   ├── test_integration.py
│   ├── test_main.py
│   ├── test_media.py
│   ├── test_state.py
│   ├── test_text.py
│   └── test_twitter_client.py
└── .github/
    └── workflows/
        ├── ci.yml                   # Linting and test workflow
        └── run-mirror.yml           # Scheduled/manual execution workflow
```

---

## Tech Stack

| Layer | Tool |
| ----- | ---- |
| Language | Python 3.10+ |
| Twitter API | [tweepy](https://pypi.org/project/tweepy/) (v2 Client, Bearer Token auth) |
| Bluesky API | [atproto](https://pypi.org/project/atproto/) (AT Protocol SDK) |
| Link cards | [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) + [requests](https://pypi.org/project/requests/) for OG metadata |
| Image processing | [Pillow](https://pypi.org/project/Pillow/) |
| Local dev | [python-dotenv](https://pypi.org/project/python-dotenv/) (`.env` file support) |
| Testing | [pytest](https://pypi.org/project/pytest/) + [pytest-cov](https://pypi.org/project/pytest-cov/) |
| Linting / quality | [ruff](https://pypi.org/project/ruff/) + [yamllint](https://pypi.org/project/yamllint/) + [check-jsonschema](https://pypi.org/project/check-jsonschema/) |
| CI / Scheduling | GitHub Actions + cron |

---

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/jbburgess/tweetskybridge.git
cd tweetskybridge
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

If `id_map.json` doesn't already exist:

```bash
echo '{"posts": {}}' > id_map.json
```

> The state file maps each mirrored tweet ID to the Bluesky post(s) it produced.

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
| `PIN_SYNC_ENABLED` | No | Mirror the Twitter pinned tweet to the Bluesky pinned post (default `true`; set `false` to disable) |

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

## Running the Bot

With your environment activated and variables set, you could run the bot once using the following:

```bash
python main.py
```

Sample output:

```text
2026-04-09 12:00:00  INFO      bot.bluesky_client  Logged in to Bluesky as you.bsky.social
2026-04-09 12:00:01  INFO      bot.twitter_client  Fetched 3 tweets from @your_handle
2026-04-09 12:00:01  INFO      root  Reposting tweet 123456789012...: Check this out...
2026-04-09 12:00:02  INFO      bot.bluesky_client  Posted to Bluesky: Check this out...
2026-04-09 12:00:02  INFO      root  Done - 1 new post(s)
```

This is just a single, direct execution of the bot, though. For continuous operation, you'll can use `scripts/run_mirror_local.py` to either setup your own local cron job / scheduled task or use the built-in loop mode, or enable the GitHub Actions workflow's `schedule` trigger, with bot runs executing in GitHub.

### Fully local runs (`scripts/run_mirror_local.py`)

If you'd like to run the mirror on your own machine — including committing and pushing `id_map.json` updates to Git — use `scripts/run_mirror_local.py`. It's a simple wrapper that executes the same pipeline as `main.py` in-process and then performs the same git steps the workflow does, with some options built-in.

**Prerequisites:**

- Project dependencies installed in your active environment (`pip install -r requirements.txt`)
- A `.env` file (or exported environment variables) with the same credentials documented in [Configuration](#configuration)
- A working git remote with push credentials configured (SSH key or credential helper / PAT) if you intend to push

**Available flags:**

| Flag | Purpose |
| ---- | ------- |
| `--once` / `--loop` | Pick execution mode (default `--once`) |
| `--interval N` | Seconds between iterations in loop mode (default `600`) |
| `--no-commit` | Skip the git commit step |
| `--no-push` | Commit locally but don't push |
| `--commit-author "Name <email>"` | Override the commit author for this run only (does not modify your git config) |
| `--commit-message MSG` | Override the commit message |
| `--remote NAME` / `--branch NAME` | Override push target (defaults: `origin` / current branch) |
| `-v` / `--verbose` | DEBUG-level logging |

#### Examples

**One-shot (recommended for OS cron / Task Scheduler):**

```bash
python scripts/run_mirror_local.py            # run once, commit + push
python scripts/run_mirror_local.py --no-push  # run once, commit locally only
python scripts/run_mirror_local.py --once --no-commit --no-push -v   # dry-ish run
```

**Loop mode (runs continuously, sleeping between iterations):**

```bash
python scripts/run_mirror_local.py --loop                    # default --interval 600
python scripts/run_mirror_local.py --interval 1800 --loop    # every 30 minutes
python scripts/run_mirror_local.py --interval 300 --loop --no-commit --no-push   # every 5 minutes, don't commit or push tweet mapping to Git
```

**Cron example (Linux/macOS/WSL), every 10 minutes during 7–21:**

```bash
*/10 7-21 * * * cd /absolute/path/to/tweetskybridge && /absolute/path/to/.venv/bin/python scripts/run_mirror_local.py >> ~/mirror-local.log 2>&1
```

**Windows Task Scheduler:** create a Basic Task that runs `python.exe` (from your venv) with arguments `scripts\run_mirror_local.py` and "Start in" set to the repo root.

## GitHub Actions Deployment

The workflow at `.github/workflows/run-mirror.yml`:

- Triggered via `workflow_dispatch` (manual or automated) or `schedule` (automatic)
- Only commits `id_map.json` back to the repo **when it actually changes**
- Requires "Read and write repository contents" under **Settings > Actions > General**

Uncomment the `schedule` trigger in `.github/workflows/run-mirror.yml` if you want the bot to run automatically in GitHub Actions. Modify the cron expression as needed to fit your desired schedule.

```yaml
on:
  schedule:
    - cron: '0 0-6,15-23 * * *'
  workflow_dispatch:
```

### Local cron trigger

GitHub's built-in `schedule` event trigger is best-effort and *will* delay and drop runs.
For more reliable scheduling at short intervals, a local cron job can be used to execute `scripts/trigger-mirror.sh`, which dispatches the workflow via the `gh` CLI. This differs from (fully local runs)[#fully-local-runs-scriptsrun_mirror_localpy] in that the bot itself is still executed within GitHub Actions rather than on your local machine. This local script simply calls the `workflow_dispatch` event to manually trigger the Actions workflow at the specified intervals.

**Prerequisites:**

- `gh` CLI installed and authenticated (`gh auth login`) with permission to dispatch workflows — use the `workflow` scope for a classic PAT, or **Actions: Read and write** for a fine-grained PAT

**Setup (WSL / Linux / macOS):**

```bash
chmod +x scripts/trigger-mirror.sh
crontab -e
```

Add the following line to schedule runs every 10 minutes during hours 7–21 (7:00 to 21:50) local time or edit the schedule as desired:

```bash
*/10 7-21 * * * /absolute/path/to/scripts/trigger-mirror.sh >> ~/mirror-trigger.log 2>&1
```

---

## How It Works

1. **Startup and config load** — `main.py` initializes logging, loads `.env` (for local runs), and validates required settings in `bot/config.py`.
2. **State bootstrap** — `bot/state.py` loads `id_map.json` and normalizes legacy formats into the current tweet→post map (`posts`). This map stores both the first Bluesky post (`root`) and most recent post (`tip`) produced for each tweet, plus cached Twitter user ID and pin-sync metadata.
3. **Client auth** — `TwitterClient` and `BlueskyClient` are initialized. Bluesky login prefers `BLUESKY_SESSION` when present, then falls back to handle/password. Transient login failures are retried with backoff.
4. **Twitter fetch and enrichment** — `TwitterClient.fetch_recent_tweets()` resolves the account's numeric user ID (cached after first lookup), fetches recent tweets through API v2, excludes retweets and replies to other accounts by default, includes media expansions, and hydrates quote-tweet payloads when present.
5. **Chronological processing and dedupe** — Tweets are processed oldest→newest so reply chains remain ordered. Each tweet ID is checked against the persisted map; already-seen tweets are skipped.
6. **Thread context resolution** — For self-replies, the bot looks up the parent tweet in the persisted map and replies to that mapped Bluesky `tip`, while preserving the conversation `root`. If the parent is unmapped (for example, too old), the tweet is posted standalone with a warning.
7. **Quote behavior selection** — For self-quotes whose target tweet is already mapped, the bot uses a native Bluesky record embed (`app.bsky.embed.record`) instead of a link card (to the external quoted Tweet). Unmapped quotes fall back to external-card behavior.
8. **Text normalization and split logic** — `bot/text.py` expands t.co links, removes Twitter media/status links that would be redundant in Bluesky embeds, unescapes entities, and splits text that exceeds 300 graphemes into threaded chunks with ` (k/n)` suffixes.
9. **Embed and media strategy** — `BlueskyClient` builds the first post's embed with Bluesky constraints in mind:
  - Image tweets: uploads up to 4 photos, preserving alt text and aspect ratio.
  - Video/GIF tweets: attempts a native video post (with aspect ratio metadata).
  - Mixed media (images + videos): posts images on the main post, then uploads each video as follow-up replies.
  - URL-only tweets: builds one external link card from Open Graph metadata.
  - Video failure fallback: if video upload is rejected, the tweet can still publish with text/link-card fallback.
10. **Rich text facets and posting** — URL facets (and hashtag tag facets) are applied to the post text. Long tweets are published as a reply chain where only the first segment carries embeds/media; downstream segments continue the same Bluesky thread.
11. **Resilience and graceful degradation** — The pipeline tolerates partial failures: rate-limited Twitter fetches skip the run cleanly; individual image/video failures are logged and skipped; persistent media upload problems degrade to text/link-card posting when possible.
12. **Mapping persistence** — After successful posts, the tweet→post map is updated and saved back to `id_map.json`, capped to the newest 100 tweet IDs. This persisted mapping enables cross-run reply threading and native self-quote embeds.
13. **Daily pinned-post reconcile** — If `PIN_SYNC_ENABLED=true`, the bot runs pinned-post sync once per UTC day (first run after midnight): it mirrors Twitter's current pinned tweet to Bluesky using the mapping, replaces changed pins, unpins when Twitter has no pinned tweet, and skips unmapped pinned tweets with a warning.
14. **Commit/push behavior by runtime** — In GitHub Actions, updated `id_map.json` is committed only when changed. In fully local mode (`scripts/run_mirror_local.py`), the same commit/push behavior is available with flags to control commit, push, interval, and loop mode.

---

## API Credentials and Estimated Costs

### Generating Credentials

#### Twitter API v2

1. Sign up for a Developer account at [developer.x.com](https://developer.x.com/)
2. Create a new App within a Project
3. Copy your **Bearer Token** from the "Keys and tokens" page

#### Bluesky

1. Sign up at [bsky.app](https://bsky.app/)
2. Generate an **App Password** under Settings > Privacy and Security > App Passwords (recommended over your main password)

### Estimated Costs

#### Twitter API v2

> There is **no free tier** available anymore for Twitter API calls, so any usage at all *will* incur at least minimal costs and you must have available funds or a paid subscription on your Twitter developer account for the bot to work.

Depending on how active the target Twitter account is, costs may vary significantly. Here are some ballpark estimates (these are *not* guaranteed and Twitter may change their pricing model at any time):

  | Activity | New tweets/day | Unique post reads/day | Daily | Monthly (~30 days) |
  |---|---|---|---|---|
  | **Quiet** | 0–10 | 5–15 | $0.035–$0.085 | ~$1.05–$2.55 |
  | **Moderate** | 20–30 | 25–35 | $0.135–$0.185 | ~$4.05–$5.55 |
  | **Active** | 50–100 | 55–105 | $0.285–$0.535 | ~$8.55–$16.05 |

The Twitter API only charges once per 24-hour UTC window for a given resource, meaning repeated retrievals of the same tweets within the same 24-hour period do *not* incur additional charges. By default, the bot retrieves the last five tweets from the target Twitter account each time it runs. Throughout the day, these repeated grabs will not incur any additional cost, but on the first run of each day (UTC), the retrieval of the last five tweets will incur cost for all five, even though those tweets were seen before the previous day. This can be seen reflected in the difference between the `New tweets/day` and `Unique post reads/day` columns in the cost table above.

Depending on how active the target account is and how often the bot is being executed, the number of tweets to retrieve each run can be tuned accordingly (via the `TWITTER_MAX_RESULTS` configuration), affecting cost one direction or the other with that once-a-day charge for *n* number of old tweets (plus the actual new tweets that appear throughout the day). It's just a matter of comfort level with whether one thinks the configured number of tweets being retrieved will always exceed the number of the tweets the target account might make during the interval between each run.

#### Bluesky (atproto API)

The `atproto` API is free to use at the current time and no costs are incurred.

---

## License

This project is open-source and available under the [MIT License](LICENSE).
