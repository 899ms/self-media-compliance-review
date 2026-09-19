# Live Evidence Workflow

Read this file only when the user explicitly asks for current platform content,
recent enforcement cases, or live creator discussion. Live search is opt-in for
each request. An installed API key, browser session, plugin, or Skill is not
authorization to search.

## Channel Selection

Live search runs only on an explicit user request. Within that request,
pick the channel by tier:

1. If the user names a provider or tool, use only that provider or tool. Do
   not silently substitute another source if it is unavailable.
2. Otherwise use the first tier that works, in this order:

   | Tier | Channel | Enablement |
   |---|---|---|
   | ① | The agent's built-in computer use (drives the screen like a human) | Self-check the host capability; when present, use it directly without asking the user again |
   | ② | The agent's built-in browser tools (browser use / MCP browser) | Same self-check; move here when ① is unavailable or the page cannot be read |
   | ③ | `opencli` (local site CLI adapters) | Only when the host has neither ① nor ②; the first option of the ask-the-user step |
   | ④ | TikHub (paid REST API; stable; five platforms incl. 视频号) | An option while asking the user; spending money requires explicit consent first |
   | ⑤ | MediaCrawler (last resort) | Only when ①-④ are all unavailable; on top of that, the frequency hard rules below bind every run |

   Tiers ①-② need no confirmation: check availability honestly and start,
   and stay human-paced (rule 5 below). Reaching tier ③ means entering the
   ask-the-user step — offer ③ first and ④ as the paid option. Tier ⑤
   additionally requires the user to accept the account risk: MediaCrawler
   drives the user's own logged-in account and platform anti-crawl has
   flagged this route in practice. If the user does not answer, continue
   the static compliance review and say that live search did not run.
3. TikHub is an optional REST adapter. Use only `tools/tikhub/bin/tikhub`,
   `tools/tikhub/lib/tikhub_client.py`, or `tools/xhs_dynamic_evidence.py`.
   They call documented `https://api.tikhub.io/api/v1/...` endpoints. Never use
   `mcp.tikhub.io`, a TikHub MCP server, or a TikHub MCP tool.
4. MediaCrawler is the tier-⑤ free local-browser adapter for Xiaohongshu,
   Douyin, Kuaishou, Bilibili, Weibo, Tieba, and Zhihu. It drives the
   user's own logged-in browser and is the channel most exposed to
   platform anti-crawl. Use only `tools/mediacrawler_search.py` against a
   user-installed MediaCrawler checkout. Never edit its config files,
   install proxy pools, or raise its rate limits. After `--setup`, confirm
   with the user which platform account to log in first.
5. Computer use, browser automation, and `opencli` all drive a real browser
   or the screen and may access public results. Respect login, CAPTCHA,
   rate-limit, access, and platform restrictions. Do not bypass them. If a
   channel shows anti-crawl signals (CAPTCHA walls, sudden empty results),
   stop that channel and say so in the report instead of pushing through.

A lookup may consume quota, incur fees, or access a logged-in session. If the
requested channel is unavailable or fails, continue the static compliance
review and say that live search did not complete. Search failure is not evidence
that no recent cases exist.

## Evidence Handling

Put live findings in a separate `实时平台证据（可选）` section. Record:

- provider and target platform;
- search terms and sample time;
- content IDs or URLs and publish dates when available;
- whether the source is official, media reporting, or creator discussion;
- access, sample-size, freshness, and verification limitations.

Creator posts and comments are discussion samples, not binding platform rules.
They may identify symptoms or disputed enforcement edges, but cannot determine
severity by themselves.

## Knowledge Deposition (opt-in)

Live findings can become permanent knowledge in this repository's case
files, but never automatically:

- After the review, if the user wants findings kept, propose converting the
  valuable records into case entries and wait for explicit confirmation
  before writing to any tracked file.
- Follow the established entry format of the target
  `references/cases/<platform>.md` — imitate its most recent
  `<!-- auto: scraped post <id> -->` blocks: a `类别:` label, the (masked)
  nickname, content id, title, interaction counts, sample date, a one-line
  summary of what the post reveals, and an explicit `Review use:` note.
  Creator posts and comments stay discussion samples, never rules.
- Appends must stay traceable: keep the content id and capture date so the
  entry can be re-verified or pruned later.
- Local installs of this repository also have an automatic loop: the
  MediaCrawler wrapper mirrors every run into
  `local/records-mc-<date>.json`, and the scheduled
  `collect.py` dedup → triage → `references/cases/` pipeline picks new ids
  up on the next collection day. Skill users without that pipeline should
  use the manual proposal flow above.

Keep API responses, downloaded media, signed URLs, model outputs, logs, and
reports in a gitignored local evidence directory. Never commit API keys,
cookies, authorization tokens, signed media URLs, raw creator data, account
security identifiers, or paid results.

## TikHub Configuration

Use `TIKHUB_API_KEY` from the process environment or a gitignored `.env`. China
mainland networks may explicitly set
`TIKHUB_API_BASE_URL=https://api.tikhub.dev`. Never print or place credentials
in commands, reports, fixtures, or commits.

## MediaCrawler Configuration (tier ⑤, last resort)

The free route uses a locally installed MediaCrawler checkout with one
manual QR-code login. It is tier ⑤ — the LAST channel, enabled only when
①-④ are all unavailable. It drives the user's own account, platform
anti-crawl has flagged this route in practice, and every run is bound by
the frequency hard rules (30-minute same-platform cooldown, 10-minute
failure backoff, machine-wide single-instance lock, per-run volume caps).
Install is automated: run
`python tools/mediacrawler_search.py --setup` (clones into gitignored
`vendor/`, builds a venv, installs chromium, patches the config for
standard Playwright mode), and check readiness with `--status`. Then run
keyword searches:

    python tools/mediacrawler_search.py --platform xiaohongshu \
      --keywords "小红书 限流 申诉,小红书 封号 经验" --max-notes 20

Use `--dry-run` to preview the command before any browser session starts.
The first run opens a visible browser window the user must unlock by
scanning; tell them before starting and warn that they should prefer a
throwaway account. Video Channels (视频号) is not supported on this route —
use TikHub or local video for it. Same-platform runs are cooldown-limited
(30 minutes by default, 10-minute backoff after a failure) to protect the
logged-in account; merge keywords into one `--keywords` (3 per run at
most) instead of looping, and never use `--force` without the user asking.
Treat the run like any other live channel: keep samples small, one
platform per invocation. The normalized `records.json`/`digest.md` land in
a gitignored `local/mc_output/` directory; never commit them, the login
cookies, or the MediaCrawler browser data. MediaCrawler's license is
non-commercial learning-only — say so when recommending the route.
