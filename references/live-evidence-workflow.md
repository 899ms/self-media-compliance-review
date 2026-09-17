# Live Evidence Workflow

Read this file only when the user explicitly asks for current platform content,
recent enforcement cases, or live creator discussion. Live search is opt-in for
each request. An installed API key, browser session, plugin, or Skill is not
authorization to search.

## Channel Selection

Before searching, tell the user which channel will be used.

1. If the user names a provider or tool, use only that provider or tool. Do not
   silently substitute another source if it is unavailable.
2. Otherwise prefer a target-platform browser plugin or Skill when it can read
   the requested public content.
3. TikHub is an optional REST adapter. Use only `tools/tikhub/bin/tikhub`,
   `tools/tikhub/lib/tikhub_client.py`, or `tools/xhs_dynamic_evidence.py`.
   They call documented `https://api.tikhub.io/api/v1/...` endpoints. Never use
   `mcp.tikhub.io`, a TikHub MCP server, or a TikHub MCP tool.
4. MediaCrawler is the free local-browser adapter for Xiaohongshu, Douyin,
   Kuaishou, Bilibili, Weibo, Tieba, and Zhihu. Use only
   `tools/mediacrawler_search.py` against a user-installed MediaCrawler
   checkout. It drives the user's own logged-in browser; never edit its
   config files, install proxy pools, or raise its rate limits.
5. A real browser tool may access public results. Respect login, CAPTCHA,
   rate-limit, access, and platform restrictions. Do not bypass them.

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

Keep API responses, downloaded media, signed URLs, model outputs, logs, and
reports in a gitignored local evidence directory. Never commit API keys,
cookies, authorization tokens, signed media URLs, raw creator data, account
security identifiers, or paid results.

## TikHub Configuration

Use `TIKHUB_API_KEY` from the process environment or a gitignored `.env`. China
mainland networks may explicitly set
`TIKHUB_API_BASE_URL=https://api.tikhub.dev`. Never print or place credentials
in commands, reports, fixtures, or commits.

## MediaCrawler Configuration

The free route uses a locally installed MediaCrawler checkout with one
manual QR-code login. Install is automated: run
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
(five minutes by default) to protect the logged-in account; merge keywords
into one `--keywords` instead of looping, and never use `--force` without
the user asking. Treat the run like any other live channel: keep samples
small, one platform per invocation. The normalized `records.json`/
`digest.md` land in a gitignored `local/mc_output/` directory; never
commit them, the login cookies, or the MediaCrawler browser data.
MediaCrawler's license is non-commercial learning-only — say so when
recommending the route.
