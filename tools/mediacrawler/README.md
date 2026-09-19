# MediaCrawler 免费采集路线

> **定位（2026-09 起）：第 ⑤ 档，最后手段。** 维护者实测本路线已被平台
> 反爬识别。实时检索按档位顺位启用：① agent 自带 computer use →
> ② agent 自带浏览器工具（browser use / MCP 浏览器）→ ③ `opencli` →
> ④ TikHub → ⑤ 本路线（仅当 ①-④ 都不可用，且启用前受频率铁律硬约束：
> 30 分钟冷却、失败退避、全机单实例锁、体量上限）。

本仓库的实时平台证据按上述档位选择数据源，下表对比其中两个自动化适配器
路线（④ TikHub 与 ⑤ MediaCrawler）：

| | TikHub（`tools/tikhub/`） | MediaCrawler（本路线） |
|---|---|---|
| 费用 | 付费 API，按调用计费 | 免费，用自己账号登录采集 |
| 原理 | 官方文档化 REST 端点 | Playwright 驱动本机已登录浏览器 |
| 平台 | 20+ 平台 | 小红书、抖音、快手、B站、微博、贴吧、知乎（视频号不支持，走 TikHub） |
| 风险 | 消耗额度 | 账号风控/处置风险（本项目记录的正是这类案例，务必小号、低频） |
| 适用 | 需要 API 级稳定和结构化数据 | 个人学习研究、小样本、偶尔取证 |

MediaCrawler 不随本仓库分发（其许可为 NON-COMMERCIAL LEARNING
LICENSE，且与商业使用不兼容），但安装是全自动的。

## 安装（一条命令）

前置：git、Python ≥ 3.10（抖音/知乎签名还需要本机 Node.js ≥ 16）。

```bash
python tools/mediacrawler_search.py --setup
```

它会自动：克隆 MediaCrawler 到仓库内被 git 忽略的 `vendor/MediaCrawler`
（优先钉在已验证的 commit）→ 建独立虚拟环境 `vendor/mc-venv` → 安装依赖和
Playwright chromium → 把 `ENABLE_CDP_MODE` 补丁为 `False`（CDP 模式要求
手动配置本机 Chrome 远程调试，自动化不可控；标准 Playwright 模式的登录态
落在 `browser_data/`，扫码一次长期复用）→ 给请求节奏打随机抖动补丁（见下）
→ `main.py --help` 自检。

**下载源自动择优**（慢网/中国大陆直连明显更快）：pip 在官方 PyPI、清华、
阿里三源里并发探测选最快；Playwright chromium（约 200MB）在官方 CDN 与
npmmirror 之间选（镜像明显更快才启用）；git 克隆在 github 直连不可达时
自动走 gh 代理镜像。依赖优先装精简版 `requirements-lean.txt`（比上游全量
少装 webui/Excel/数据库驱动等，装完自检失败会自动回退全量）。已设
`PIP_INDEX_URL`、`PLAYWRIGHT_DOWNLOAD_HOST`、`MC_GIT_URL` 时以环境变量为
准；`--no-mirror` 或 `MC_NO_MIRROR=1` 可整体禁用镜像。安装日志逐行转发到
stderr，stdout 始终是纯 JSON。

随时用 `--status` 检查安装与登录态（JSON 输出，含已登录平台列表与
`pacing_patched` 抖动补丁状态）。

也可以把已有克隆通过 `MEDIACRAWLER_HOME` 环境变量或 `--mc-dir` 指进来
（此时不强制 vendor 布局，但 venv 仍按 `<mc-dir>/../mc-venv` 查找）。

## 使用

首次运行会弹出浏览器窗口，用你的账号扫码登录；登录态保存后不再需要扫码。
**开始前和用户确认**：用哪个平台、抓哪些关键词、抓多少条（`--max-notes`
保持小值）。

```bash
# 先预览实际命令
python tools/mediacrawler_search.py --platform xiaohongshu \
  --keywords "小红书 限流 申诉,小红书 封号 经验" --dry-run

# 正式运行
python tools/mediacrawler_search.py --platform xiaohongshu \
  --keywords "小红书 限流 申诉,小红书 封号 经验" --max-notes 20

# 抖音（需要 Node.js）
python tools/mediacrawler_search.py --platform douyin \
  --keywords "抖音 违规 申诉 经验" --max-notes 10 --with-comments
```

平台别名：`xiaohongshu/xhs`、`douyin/dy`、`kuaishou/ks`、`bilibili/bili`、
`weibo/wb`、`tieba`、`zhihu`。

等价的原生 MediaCrawler 命令（不经过包装脚本）：

```bash
cd vendor/MediaCrawler
../mc-venv/bin/python main.py --platform xhs --lt qrcode --type search \
  --keywords "小红书 限流 申诉" --crawler_max_notes_count 20 \
  --save_data_option jsonl --save_data_path /tmp/mc-out
```

## 账号保护：频率与体量控制

登录的是你自己的账号，抓太密会触发平台风控（验证码、限流甚至封号）。本项目的
抓取常带评论（`--with-comments`），单次 run 的请求数比纯搜索更大，所以频率
上限不能放宽。包装脚本内置四道机制（默认参数即保守档，超限直接拒绝而不是
靠自觉）：

1. **同平台冷却 30 分钟**（`MC_COOLDOWN_SECONDS` 可调）：对应「同账号同平台
   每天 ≤ 4-6 次」的安全预算。多个关键词合并进一次 `--keywords`（单次最多
   3 个，`MC_MAX_KEYWORDS` 可调）；确有必要立即重抓时加 `--force`。
2. **失败退避 10 分钟**：抓取失败（没扫码 / 触发风控 / 无结果）也会写一个
   较短的冷却标记——失败往往发生在风控敏感期，立即重试只会继续加压。连续
   失败通常是登录失效或风控信号，先 `--status` 检查登录态，不要拿
   `--force` 硬闯。
3. **全机单实例锁**：同一时间只允许一个抓取进程，跨平台并行同样拒绝
   （并行会抢浏览器登录 profile、可能损坏登录态）。`--force` 也不绕过锁；
   崩溃残留超过 2 小时的锁会被自动抢占。
4. **请求间隔随机抖动**：setup 会给上游爬虫打补丁，把固定 2s 间隔改成
   3-6s 随机停顿（固定间隔是平台异常检测最经典的机器特征）；评论固定为
   一级、每条内容 ≤ `--max-comments`（默认 10）条，二级评论关闭。

守则：风控看的是长期总量，不是单次频率——每日预算同账号同平台 ≤ 4-6 次
run；额度用完改走 TikHub 或改天再抓。出现验证码、登录失效、连续空结果
立即停手。

## 输出

MediaCrawler 的原始文件落在 `<输出目录>/<平台>/jsonl/` 下，命名为
`{爬取类型}_{内容类型}_{日期}.jsonl`（如 `search_contents_2026-09-16.jsonl`
与 `search_comments_2026-09-16.jsonl`）。包装脚本把它们归一化为本项目的
记录格式，并生成：

- `digest.md` — 每条记录一行（id、评论数、点赞数、日期、昵称、搜索词、标题）；
- `records.json` — `{"records": [...], "comments": [...]}`，字段为
  `id/title/nick/comments/likes/date/url/platform/keyword`，与 `local/collect.py`
  的记录结构对齐，可直接进入后续整理流程。

默认输出目录是仓库内已被 git 忽略的 `local/mc_output/<平台>-<时间戳>/`，
原始数据与归一化结果都留在本机，不会进入提交。

## 知识沉淀闭环

抓回来的内容不止看一眼，两条路径都能沉淀回本 Skill 的知识库：

**维护者自动管道（本地安装才有）**：每次抓取会把去重后的记录镜像到
`local/records-mc-<日期>.json`。定时管道（`local/auto_update.sh`）在下一个
采集日运行 `collect.py dedup` 时会扫描这些文件（`seen_ids.txt` 保证幂等），
新条目自动进入 Claude triage → 追加进 `references/cases/<平台>.md` →
自动提交推送。手动跑的 MediaCrawler 抓取和定时 TikHub 采集走同一个
漏斗，不需要额外操作。

**普通 Skill 用户（确认后手动沉淀）**：审核完成后，如果用户想把发现留下来，
agent 会筛选有价值的记录，按 `references/cases/<平台>.md` 既有条目格式
（`类别:` 标签、脱敏昵称、内容 id、标题、互动数、样本日期、一句话发现、
明确的 `Review use:` 说明）生成条目提案，**经用户确认后**才写入仓库文件。
创作者帖子和评论只作为讨论样本，永远不当作平台规则。

## 合规红线

1. MediaCrawler 采用 NON-COMMERCIAL LEARNING LICENSE：仅限个人学习研究，
   禁止商业用途。
2. 只采集公开内容；遵守目标平台条款与 robots.txt。
3. 控制频率与样本量（`--max-notes` 保持小值，遵守同平台冷却），不加代理池、
   不做大规模爬取。
4. 用小号。限流、封号正是本仓库记录的处置类型，主号风险自负。
5. 登录 Cookie、浏览器数据（`vendor/MediaCrawler/browser_data/`）、原始抓取
   结果一律不进 git；昵称是平台脱敏值、`creator_hash` 是匿名哈希（防骚扰
   设计），不要写进对外报告。
