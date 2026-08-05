# BF6 Portal Code Monitor

[中文文档](README.md)

A real-time monitor for **Battlefield 6 Portal** XP-farm server codes. It scans
three community sources every 5 minutes, runs every newly discovered code
through three verification layers, and pushes it straight to your Feishu/Lark
chat — so you can join a fresh server before everyone else does.

## Why

DICE regularly bans Portal community servers that exist purely for weapon-XP
farming. A working code's shelf life is often **a few hours at best** — by the
time it reaches a forum thread or a Discord forward, the server is usually
already banned or full.

This tool exists to close that gap: the moment a new code appears in any of
the monitored sources, it lands in your chat within seconds, annotated with
how trustworthy it looks.

## How it works

```
  data sources (polled every 5 min)            verification                 notification
┌──────────────────────────────┐   ┌───────────────────────────────┐   ┌────────────────┐
│ bfportal.gg REST API         │   │ 1. known-code cross-check     │   │ Feishu / Lark  │
│   (structured, zero FPs)     │   │    (608-code index of the     │   │  via lark-cli  │
│                              │   │     full bfportal.gg catalog) │   │  or webhook    │
│ YouTube via yt-dlp           │──►│                               │──►│                │
│   (search → title/desc)      │   │ 2. comment feedback rating    │   │ ✅ likely works │
│                              │   │    (✅ / ⚠️ / ❌)             │   │ ⚠️ uncertain   │
│ Reddit via Arctic Shift      │   │                               │   │ ❌ likely dead  │
│   mirror (posts + comments)  │   │ 3. publish date attached      │   │                │
└──────────────────────────────┘   └───────────────────────────────┘   └────────────────┘
```

Single-file Python program, **standard library only** (no pip dependencies).
The only external tool is the `yt-dlp` binary for the YouTube source.

## Data sources

| Source | Mechanism | Characteristics |
|---|---|---|
| **bfportal.gg** (primary) | Official REST API; codes are structured fields | Most reliable, **zero false positives**; speed depends on player submissions |
| **YouTube** | `yt-dlp` searches XP-farm videos, extracts codes from titles/descriptions | **Fastest** — codes appear the moment a video is up; noisy, some false-positive risk |
| **Reddit** | Scans new posts + comments across 3 subreddits | Uses the [Arctic Shift](https://arctic-shift.photon-reddit.com) archive mirror (seconds-to-minutes sync delay). Reddit's official `.json`/`.rss` endpoints **block datacenter IPs**, so the mirror API is required |

### bfportal.gg

[bfportal.gg](https://bfportal.gg) is a community-maintained, open catalog of
Battlefield Portal experiences (codes, XP-farm flags, broken status) with a
public REST API.

- List: `GET https://bfportal.gg/api/experiences/?order=-id&limit=20`
  (`order=-id` is mandatory — without it the response is not newest-first;
  non-experience entries are filtered out by `meta.type == "core.ExperiencePage"`)
- Detail: `GET https://bfportal.gg/api/experiences/{id}/` — includes
  `code` / `xp_farm` / `broken` / `description` / `owner` / `meta.html_url`
- Entries with an empty/`None` code or `broken=true` are skipped;
  `xp_farm=true` servers get a 🔥 marker in the push

### YouTube

`yt-dlp` (subprocess) searches three keyword groups **in rotation** (one group
per poll round):

- `battlefield 6 portal code`
- `bf6 xp farm portal`
- `bf6 portal code bot lobby`

Each group runs `ytsearch15` with `--flat-playlist --print` to collect
id/title/channel/view count. New videos (deduped by video id) have codes
extracted from titles; up to **5** new videos per round additionally get their
descriptions fetched for more codes.

### Reddit (Arctic Shift mirror)

Reddit's official endpoints block this host's IP, so the tool uses the archive
mirror API `https://arctic-shift.photon-reddit.com/api`:

- `GET /api/posts/search?subreddit=<sub>&limit=50&sort=desc`
- `GET /api/comments/search?subreddit=<sub>&limit=50&sort=desc`

Subreddits: `BattlefieldPortal` / `Battlefield` / `battlefield6` — 6 streams
total (3 subs × posts/comments). Each stream keeps a `created_utc` watermark
for incremental reads; the first run backfills 1 hour to build a baseline.
Note: the mirror has archive lag, and late-archived old posts that predate the
watermark are missed — an accepted trade-off.

## Code extraction (YouTube / Reddit)

Codes are 4–6 alphanumeric characters, case-sensitive (pushed as-is).
Extraction is layered:

1. **Explicit lead-in** (high confidence): `code:` / `portal:` / `server code`
   style markers followed directly by a token — pure-letter codes allowed here
   (e.g. `portal: MPHD`)
2. **Loose context**: token adjacent to portal/experience/server/lobby/code
   keywords — must contain both letters and digits
3. **Colon/comma lead-in**: token preceded by `:` or `,` with mode/map/farm
   context words nearby (deathmatch, conquest, xp, farm, bot, …) — must contain
   both letters and digits
4. **Blacklist**: common English words, game names, and numeric units
   (`99ms`, `1080p`, `4GB`, `500XP`, …) are always filtered; URLs are stripped
   up front so Discord invite fragments and video ids are never mistaken for codes

Two field-tested heuristics: pure-digit strings are never treated as codes
(years/counts produce too many false positives), and **lowercase pure-letter
strings are never codes** (real letter-only codes are uppercase). See
`test_extract_codes.py` for real false-positive samples.

False positives are still possible (regex inference, not structured data) —
every push includes the source and surrounding context for a quick human check.

## Verification layers

### 1. Known-code cross-check (code index)

The full bfportal.gg catalog is mirrored locally into `code_index.json`
(608 codes at the time of writing) and every YouTube/Reddit candidate is
checked against it:

- **In the index** → high confidence, push annotated `Index: ✅ listed (<experience title>)`
- **Not in the index** → still pushed (genuinely new codes may not be listed
  yet), annotated `Index: ➖ not listed`

English-word false positives are never in the catalog, so they get exposed by
this check while real codes are unaffected — **no recall loss**. The index is
rebuilt automatically when older than 24 hours (~9 minutes, old index stays in
service meanwhile); `--rebuild-index` forces a manual rebuild. If the index is
completely unavailable, pushes simply omit the line — never blocked.

### 2. Comment feedback rating

For every new YouTube/Reddit code, the tool fetches up to **30 comments** from
the source video/post and counts positive/negative signal keywords:

- **Positive**: worked, works, still working, confirmed, valid, legit, thanks,
  got xp, leveling, fast, amazing, insane, love, great, perfect, awesome, …
- **Negative**: patched, banned, doesn't work, not working, dead, removed,
  nerfed, error, kicked, fixed, no longer, gone, invalid, broken, stopped
  working, …

Each comment contributes at most one signal (negative wins on conflict).
Rating:

| Rating | Condition |
|---|---|
| ✅ likely working | positive ≥ 2 and negative = 0 |
| ❌ likely dead | negative ≥ 1 and negative ≥ positive |
| ⚠️ uncertain | everything else; fewer than 3 comments → "insufficient sample" |

Budget: at most **5 codes** per round get comment verification; the rest are
pushed without a feedback line. Verification is stateless, best-effort, and
never blocks a push (failure degrades to `⚠️ uncertain (no comment data)`).
Skip it entirely with `--no-verify`. bfportal.gg has no comment section, so
its pushes carry no feedback line by design.

### 3. Publish date

Every push includes a `Published:` line so you can judge freshness at a glance:

| Source | Field | Format |
|---|---|---|
| YouTube | `upload_date` | `YYYY-MM-DD` (only for videos whose description was fetched, max 5/round) |
| Reddit | `created_utc` | `YYYY-MM-DD HH:MM UTC` |
| bfportal.gg | `meta.first_published_at` | `YYYY-MM-DD` |

## Quick start

Requirements: **Python 3.8+** (standard library only) and **yt-dlp** on PATH
(needed for the YouTube source; if missing, that source logs a warning and the
others keep running).

```bash
git clone https://github.com/goaltang/bf6-portal-monitor.git
cd bf6-portal-monitor

bash start.sh            # start in the background (logs to monitor.log)
bash start.sh status     # check status + recent log lines
bash start.sh log        # tail the log
bash start.sh stop       # stop the monitor
```

Or run it in the foreground:

```bash
python3 bf6_portal_monitor.py          # poll forever, 300 s per round
python3 bf6_portal_monitor.py --once   # single round, then exit
```

## Configuration (notifications)

**Zero config works out of the box** if an authenticated `lark-cli` is
installed on the machine — pushes go to the default Feishu group.

| Env var | Meaning |
|---|---|
| `FEISHU_TARGET` | Optional. lark-cli target: `chat:oc_xxx` (group) or `user:ou_xxx` (P2P). Bare values are treated as `chat:` |
| `FEISHU_WEBHOOK` | Optional. Custom Feishu bot webhook URL. **Takes precedence over lark-cli when set** |
| `FEISHU_SECRET` | Optional. HMAC-SHA256 signing secret for bots with signature verification (webhook path only) |

## Usage

```bash
python3 bf6_portal_monitor.py                            # all three sources, 300 s interval
python3 bf6_portal_monitor.py --interval 60              # custom interval (seconds, min 15)
python3 bf6_portal_monitor.py --sources youtube,reddit   # only selected sources (bfportal,youtube,reddit)
python3 bf6_portal_monitor.py --once --backfill 5        # bfportal: also push the 5 newest existing entries (demo)
python3 bf6_portal_monitor.py --once --no-verify         # skip comment feedback verification (debug)
python3 bf6_portal_monitor.py --rebuild-index            # force full code-index rebuild and exit (~9 min)
```

First-run behavior:

- **Code index** — built from scratch if missing (~9 minutes) before monitoring starts
- **bfportal** — baselines on the current max id; no historical pushes (unless `--backfill N`)
- **YouTube** — baselines on current search results; any code extracted is pushed immediately
- **Reddit** — each stream backfills 1 hour; codes inside that window are pushed

Per-source failures (network, yt-dlp errors) are logged and skipped — they
never affect other sources. Each source pushes at most 10 messages per round
to prevent first-run flooding.

## Push message format

New bfportal.gg experience:

```
🎯 New Portal experience: 030 Portal Lab
Code: 1ZC5T
🔥 XP-farm server        ← only when xp_farm=true
Players/Bots: 64/99
Author: xxx
Published: 2026-08-03
Description: <first 150 chars of the description>
https://bfportal.gg/experiences/xxx/
```

New YouTube code:

```
📺 New YouTube code: 1Y8CM
Video: NEW BF6 WEAPON XP FARM 2 V 64 BOTS //CODE 1Y8CM
Channel: Sensation
Published: 2026-08-03        ← only for videos whose description was fetched
Context: <sentence around the code>
Index: ➖ not listed          ← or: Index: ✅ listed (experience title)
Feedback: ✅ likely working (3 positive / 0 negative, 12 comments)
https://www.youtube.com/watch?v=<id>
```

New Reddit code:

```
💬 New Reddit code: ZS57D
Source: r/battlefield6 (post)
Title: <post title>          ← omitted for comments
Published: 2026-08-04 12:34 UTC
Context: <sentence around the code>
Index: ✅ listed (BLACKSITE: ASCENDANT)
Feedback: ❌ likely dead (0 positive / 2 negative, 8 comments)
https://www.reddit.com<permalink>
```

Feedback line variants: `✅ likely working (…)`, `❌ likely dead (…)`,
`⚠️ uncertain (…)`, `⚠️ uncertain (insufficient sample, K comments)`,
`⚠️ uncertain (no comment data)`. With `--no-verify` or once the per-round
verification budget is exhausted, the feedback line is omitted. The
`Index:` line is omitted when the code index is unavailable.

## State files

`state.json` (auto-created, delete it to fully reset all baselines):

```json
{
  "version": 3,
  "bfportal": { "max_seen_id": 1273 },
  "youtube":  { "keyword_index": 0, "seen_videos": ["..."] },
  "reddit":   { "watermarks": {"BattlefieldPortal:posts": 1785860145}, "seen_posts": ["posts:..."] }
}
```

`code_index.json` — the bfportal.gg code catalog mirror (~608 codes). Its
`built_at` timestamp drives the 24-hour auto-rebuild; old v2 state files are
upgraded automatically.

## Testing

```bash
python3 test_extract_codes.py   # 32 code-extraction cases incl. real false-positive samples
python3 test_feedback.py        # feedback rating logic / keywords / message format (no network)
python3 test_code_index.py      # index cross-check: listed/unlisted/case/expiry/degradation (no network)
```

`test_v4_push_format.py` / `test_v5_push_format.py` are live format checks —
they fetch real data and **send actual Feishu messages** marked as format
tests. The `manual_push_format_v*.py` scripts do the same and were renamed so
pytest doesn't collect them by accident.

## FAQ

- **Do codes get pushed twice?** No — each source dedupes independently
  (bfportal by id watermark, YouTube by video id, Reddit by `created_utc`
  watermark + seen ids). Identical codes within one round are pushed once.
- **What about false positives?** Three lines of defense: layered extraction
  rules + blacklist; the code-index cross-check (English-word false positives
  are never in the catalog and get marked `➖ not listed`); and source/context
  in every push for human review. The bfportal.gg source has zero false positives.
- **How fresh is the code index?** Auto-rebuilt when older than 24 h
  (~9 min, non-blocking, old index stays in service). Codes listed in the
  catalog after the last rebuild show as "not listed" until the next one —
  expected lag.
- **One source is down — do the others stop?** No. Every source runs in its
  own try/except; failures are only logged.
- **Can I trust the feedback rating?** It's a keyword heuristic — with few or
  off-topic comments it can be wrong (hence the "uncertain" tier). Top comment
  excerpts are written to the run log for manual review. Verification failure
  never blocks a push.

## Disclaimer

This is an **unofficial, fan-made player tool** with no affiliation to
Electronic Arts or DICE.

- Codes come from **public community sources** (bfportal.gg, YouTube, Reddit);
  nothing is scraped from behind a login.
- XP farming may violate the game's terms of service and **can lead to bans**.
  Use this tool at your own risk.
- The push format, keyword lists, and heuristics are tuned for the author's
  own setup; YMMV.
