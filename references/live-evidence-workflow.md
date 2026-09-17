# Live Evidence Workflow

Read this file only when the user explicitly asks for current platform content,
recent enforcement cases, or live creator discussion. Live search is opt-in for
each request. An installed API key, browser session, plugin, or Skill is not
authorization to search.

## Channel Selection

Before searching, decide the channel WITH the user — never pick one
silently:

1. If the user names a provider or tool, use only that provider or tool. Do
   not silently substitute another source if it is unavailable.
2. Otherwise, list the channels actually available in this environment and
   ask the user to choose before any search runs. Check availability
   honestly: TikHub only if `TIKHUB_API_KEY` resolves; MediaCrawler only if
   `tools/mediacrawler_search.py --status` reports ok; browser plugins and
   Skills only if actually installed. Note the trade-off in one line each
   (TikHub consumes paid quota; MediaCrawler uses the user's own logged-in
   account and needs its one-time scan login). On a fresh install or the
   first live request, run this availability check as part of the
   confirmation and offer to run `--setup` if the user prefers the free
   route. If the user does not answer, continue the static compliance
   review and say that live search did not run.
3. TikHub is an optional REST adapter. Use only `tools/tikhub/bin/tikhub`,
   `tools/tikhub/lib/tikhub_client.py`, or `tools/xhs_dynamic_evidence.py`.
   They call documented `https://api.tikhub.io/api/v1/...` endpoints. Never use
   `mcp.tikhub.io`, a TikHub MCP server, or a TikHub MCP tool.
4. MediaCrawler is the free local-browser adapter for Xiaohongshu, Douyin,
   Kuaishou, Bilibili, Weibo, Tieba, and Zhihu. Use only
   `tools/mediacrawler_search.py` against a user-installed MediaCrawler
   checkout. It drives the user's own logged-in browser; never edit its
   config files, install proxy pools, or raise its rate limits. After
   `--setup`, confirm with the user which platform account to log in first.
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
