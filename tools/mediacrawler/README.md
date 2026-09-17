# MediaCrawler 免费采集路线

本仓库的实时平台证据有两条路线：

| | TikHub（`tools/tikhub/`） | MediaCrawler（本路线） |
|---|---|---|
| 费用 | 付费 API，按调用计费 | 免费，用自己账号登录采集 |
| 原理 | 官方文档化 REST 端点 | Playwright 驱动本机已登录浏览器 |
| 平台 | 20+ 平台 | 小红书、抖音、快手、B站、微博、贴吧、知乎 |
| 风险 | 消耗额度 | 账号风控/处置风险（本项目记录的正是这类案例，务必小号、低频） |
| 适用 | 需要 API 级稳定和结构化数据 | 个人学习研究、小样本、偶尔取证 |

MediaCrawler 不随本仓库分发（其许可为 NON-COMMERCIAL LEARNING
LICENSE，且与商业使用不兼容），需要用户自行克隆安装。

## 安装（一次性）

前置：Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node.js ≥ 16
（抖音/知乎签名需要）、本机 Chrome 或 Edge（默认 CDP 模式直接用真实浏览器，
反检测最好）。

```bash
git clone https://github.com/NanmiCoder/MediaCrawler
cd MediaCrawler
uv sync
# 仅当关闭 CDP 模式（ENABLE_CDP_MODE=False）时才需要：
uv run playwright install chromium
```

首次运行会弹出浏览器要求扫码登录（`--lt qrcode`），登录态保存在
MediaCrawler 目录内（`browser_data/` / `*_user_data_dir`），之后的运行不再
需要登录。**登录态和浏览器数据绝不能提交进任何仓库。**

## 使用

推荐通过仓库自带的包装脚本调用（自动传关键词、指定输出目录、归一化为
本项目的记录格式）：

```bash
export MEDIACRAWLER_HOME=/path/to/MediaCrawler

# 先预览实际命令
python tools/mediacrawler_search.py --platform xiaohongshu \
  --keywords "小红书 限流 申诉,小红书 封号 经验" --dry-run

# 正式运行（默认打开浏览器窗口；首次需扫码）
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
cd /path/to/MediaCrawler
uv run main.py --platform xhs --lt qrcode --type search \
  --keywords "小红书 限流 申诉" --crawler_max_notes_count 20 \
  --save_data_option jsonl --save_data_path /tmp/mc-out
```

## 输出

包装脚本把 MediaCrawler 写入输出目录的 `search_contents*.jsonl` /
`comments*.jsonl` 归一化为本项目的记录格式，并生成：

- `digest.md` — 每条记录一行（id、评论数、点赞数、日期、昵称、标题）；
- `records.json` — `{"records": [...], "comments": [...]}`，字段为
  `id/title/nick/comments/likes/date/url/platform`，与 `local/collect.py`
  的记录结构对齐，可直接进入后续整理流程。

默认输出目录是仓库内已被 git 忽略的 `local/mc_output/<平台>-<时间戳>/`，
原始 JSONL 与归一化结果都留在本机，不会进入提交。

## 合规红线

1. MediaCrawler 采用 NON-COMMERCIAL LEARNING LICENSE：仅限个人学习研究，
   禁止商业用途。
2. 只采集公开内容；遵守目标平台条款与 robots.txt。
3. 控制频率与样本量（`--max-notes` 保持小值），不加代理池、不做大规模爬取。
4. 用小号。限流、封号正是本仓库记录的处置类型，主号风险自负。
5. 登录 Cookie、浏览器数据、原始抓取结果、付费或账号数据一律不进 git。
