# MediaCrawler 免费采集路线

本仓库的实时平台证据有两条路线：

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
落在 `browser_data/`，扫码一次长期复用）→ `main.py --help` 自检。

随时用 `--status` 检查安装与登录态（JSON 输出，含已登录平台列表）。

也可以把已有克隆通过 `MEDIACRAWLER_HOME` 环境变量或 `--mc-dir` 指进来
（此时不强制 vendor 布局，但 venv 仍按 `<mc-dir>/../mc-venv` 查找）。

## 使用

首次运行会弹出浏览器窗口，用你的账号扫码登录；登录态保存后不再需要扫码。

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

## 账号保护：同平台冷却

同一平台两次抓取默认间隔 5 分钟（`MC_COOLDOWN_SECONDS` 可调），间隔不足
会被拒绝并提示——这是为了保护你的登录账号不触发风控。多个关键词合并进一次
`--keywords` 即可；确有必要立即重抓时加 `--force`。

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
