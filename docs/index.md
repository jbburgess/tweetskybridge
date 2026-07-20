---
layout: default
title: TweetSkyBridge - Twitter to Bluesky Repost Bot
permalink: /
---

A Python bot that mirrors tweets from a Twitter (X) account to a corresponding Bluesky account, with rich support for embedded media, quote tweets, reply threads, and more.

See the full source code and usage instructions on [GitHub](https://github.com/jbburgess/bskybot-sjearthquakes).

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

## Estimated Costs

### Twitter API v2

> There is **no free tier** available anymore for Twitter API calls, so any usage at all *will* incur at least minimal costs and you must have available funds or a paid subscription on your Twitter developer account for the bot to work.

Depending on how active the target Twitter account is, costs may vary significantly. Here are some ballpark estimates (these are *not* guaranteed and Twitter may change their pricing model at any time):

  | Activity | New tweets/day | Unique post reads/day | Daily | Monthly (~30 days) |
  |---|---|---|---|---|
  | **Quiet** | 0–10 | 5–15 | $0.035–$0.085 | ~$1.05–$2.55 |
  | **Moderate** | 20–30 | 25–35 | $0.135–$0.185 | ~$4.05–$5.55 |
  | **Active** | 50–100 | 55–105 | $0.285–$0.535 | ~$8.55–$16.05 |

The Twitter API only charges once per 24-hour UTC window for a given resource, meaning repeated retrievals of the same tweets within the same 24-hour period do *not* incur additional charges. By default, the bot retrieves the last five tweets from the target Twitter account each time it runs. Throughout the day, these repeated grabs will not incur any additional cost, but on the first run of each day (UTC), the retrieval of the last five tweets will incur cost for all five, even though those tweets were seen before the previous day. This can be seen reflected in the difference between the `New tweets/day` and `Unique post reads/day` columns in the cost table above.

Depending on how active the target account is and how often the bot is being executed, the number of tweets to retrieve each run can be tuned accordingly, affecting cost one direction or the other with that once-a-day charge for *n* number of old tweets (plus the actual new tweets that appear throughout the day). It's just a matter of comfort level with whether one thinks the configured number of tweets being retrieved will always exceed the number of the tweets the target account might make during the interval between each run.

### Bluesky (atproto API)

The `atproto` API is free to use at the current time and no costs are incurred.

---

## License

This project is open-source and available under the [MIT License](LICENSE).
