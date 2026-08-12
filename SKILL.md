---
name: self-media-compliance-review
description: "Use when auditing self-media videos, scripts, covers, subtitles, voiceover, product links, account copy, comments, articles, or publishing packages for platform violation risk; especially before final delivery or publishing after video production or clipping. Also covers e-commerce compliance: product-consistency checks (video vs detail page vs script), 千川 low-quality素材, regulated-category qualifications, efficacy claims, price/gift/activity consistency, and pre-selection risk. Supports WeChat Channels, WeChat Official Accounts, Douyin, Kuaishou, Bilibili, Xiaohongshu, TikTok, Douyin E-Commerce, and other platforms."
---

# Self-Media Compliance Review

## Core Rule

Run a compliance review before any self-media video, clip, cover, title, subtitle, voiceover, product link, or publish copy is treated as final. The review is a risk-control pass, not legal advice and not a guarantee that a platform will approve the content.

Default output language is Chinese unless the user asks otherwise.

## Inputs

Collect or infer these inputs before judging:

- Target platform(s): 视频号, 微信公众号, 订阅号, 服务号, 抖音, 快手, B站, 小红书, TikTok, 抖音电商, etc.
- Public-facing material: final video path, script, subtitles, cover text, title, description, tags, comments, product link copy, account/profile copy.
- Context: account identity, topic vertical, target audience, source ownership/authorization, product/service being promoted, qualifications for regulated topics.
- Evidence access: timecodes, frame notes, transcript lines, copy files, screenshots, manifests, or links.

### E-Commerce Extended Inputs

When the content involves 带货、挂车、商品链接、抖店、千川投放 or any commercial promotion, also collect:

- **商品详情页**: product detail page URL, full-page screenshot, captured-at timestamp.
- **SKU/规格**: all SKU variants with price, weight, volume, color, size.
- **价格/赠品/活动规则**: current selling price, original/line-through price, gift items with specs, activity deadlines, coupon/red-packet conditions.
- **资质与授权**: business license, category-specific qualifications, brand authorization letter, patent/certification numbers.
- **素材来源**: source files, license/authorization proof for video, images, BGM, fonts, portrait, and brand assets.
- **历史处罚**: prior violations, rejected 千川素材, account penalty history.

If a required input is missing, continue with the available evidence and mark the item `待核验`; do not invent facts, qualifications, authorizations, prices, source provenance, or platform behavior.

## Platform References

Always run the universal audit areas below. Then load platform-specific references when relevant:

- 微信视频号 / 视频号 / WeChat Channels: read `references/wechat-channels.md`.
- 微信公众号 / 微信公众平台 / 订阅号 / 服务号 / WeChat Official Accounts: read `references/wechat-official-account.md`.
- 抖音 / Douyin: read `references/douyin.md`.
- 快手 / Kuaishou: read `references/kuaishou.md`.
- B站 / 哔哩哔哩 / Bilibili: read `references/bilibili.md`.
- 小红书 / Xiaohongshu / RED: read `references/xiaohongshu.md`.
- Recent enforcement cases, creator discussions, or account-status/限流 questions: read `references/recent-cases-2025-2026.md`.

### E-Commerce References

When the content involves 带货、挂车、商品链接、抖店、千川投放、选品 or any e-commerce scenario, also load:

- 抖音电商规则: `references/douyin-ecommerce.md`.
- 千川低质素材治理: `references/qianchuan-low-quality.md`.
- 电商功效与声明规则: `references/ecommerce-claims.md`.
- 电商违规案例: `references/cases/ecommerce-cases.md`.

E-Commerce trigger words: 带货、挂车、商品链接、详情页、SKU、佣金、转化、成交、选品、千川、低质素材、抖店、精选联盟、商品三一致、功效承诺、前后对比、赠品、优惠券、到手价、小黄车、商品分享、直播带货、达人带货、商家、开店、罚.

When using recent cases, load the index first, then the matching platform case file under `references/cases/`:

- 小红书: `references/cases/xiaohongshu.md`.
- 微信公众号: `references/cases/wechat-official-account.md`.
- 视频号: `references/cases/wechat-channels.md`.
- 抖音: `references/cases/douyin.md`.
- 快手: `references/cases/kuaishou.md`.
- B站: `references/cases/bilibili.md`.
- 抖音电商/带货: `references/cases/ecommerce-cases.md`.

## Optional Dynamic Xiaohongshu Evidence

When the user has already encountered a violation, limiting, takedown, failed appeal, low views, non-indexing, or unclear platform notice, dynamic Xiaohongshu search can be used as an optional evidence supplement.

Use `tools/xhs_dynamic_evidence.py diagnose` only when:

- the user asks to find similar cases or current discussion; or
- the review depends on recent hidden-rule symptoms; and
- `TIKHUB_API_KEY` is configured.

If the key is missing or the tool fails, do not block the review. Continue with official rules, static case files, and user-provided evidence. State: "动态小红书检索未启用：当前环境未配置 `TIKHUB_API_KEY` 或工具不可用。"

Dynamic evidence must be reported under `动态小红书相似案例`. It is a 可选增强 and must be separated from official rules. Ordinary creator notes and comments are discussion samples, not platform rules.

For new platforms, add one reference file under `references/<platform>.md` with:

- Platform scope and source date.
- Severity rules and hard blockers.
- Category checklist with platform article numbers or policy names.
- Common risky phrases, visuals, and behaviors.
- Safer rewrite/remediation patterns.

Do not overload this `SKILL.md` with platform rule catalogs; keep detailed platform material in references.

## Review Workflow

1. **Inventory the public surface**
   - List every user-visible or user-audible element: picture, cover, first frame, title, subtitles, voiceover, BGM, captions, stickers, comments, private-message prompts, product card, external links, QR codes, account profile.
   - For videos, sample the first 0-5s, major scene changes, product/CTA sections, sensitive visuals, and ending.

2. **Map content intent**
   - Identify whether the content is education, entertainment, news/current affairs, product marketing, health/medical, finance, legal, relationship advice, minors, animals, violence, sexuality, or public-interest event coverage.
   - Flag regulated domains early: medical/health, finance/investment, legal services, fundraising, lottery/gambling, pet/vehicle trading, drugs/medical devices, health food, special medical formula food.

3. **Run universal risk areas**
   - Rights: copyright, low-effort搬运/二创, third-party watermarks, portrait/name/reputation/privacy, trademark/patent.
   - Sexual/lowbrow: nudity, body focus, sexual implication, sexual sounds/text, sex jokes, animal mating.
   - Violence/discomfort: gore, injury/death, surgery, abuse, bullying, horror, excrement/secretions, dense holes/insects, disturbing food/animals.
   - Illegal or harmful: gambling, pyramid schemes, controlled goods, illegal finance, fraud, fake cheating tools, dangerous stunts, minors' unsafe behavior.
   - Marketing: exaggerated claims, unverifiable data, absolute terms, fake authority, inconsistent price/gifts/link, nonofficial purchase channels, excessive product insertion.
   - Misinformation: outdated events as news, fake interviews, unknown-source emotional stories, celebrity rumors, AI/synthetic accident/war scenes without clear labeling, pseudoscience.
   - Inducement and diversion: forced likes/comments/follows/shares, curses/coercion, fake benefits, incomplete episodes, off-platform traffic, risky contact methods.
   - Public order and morals: discrimination, insults, public-order disruption, abnormal relationship sensationalism, family abuse, bad marriage customs.
   - Production quality: unreadable/misaligned subtitles, wrong aspect ratio, black screens, distorted visuals, audio dropouts, audio-video mismatch, invalid/unrelated links.
   - **E-commerce product consistency** (load `references/douyin-ecommerce.md` and `references/qianchuan-low-quality.md`):
     - Video-displayed product vs detail page: brand, style, color, pattern, shape consistent?
     - Voiceover spec vs SKU spec: quantity, weight, volume, size consistent?
     - Voiceover price vs linked product price: consistent?
     - Gift/red-packet/coupon conditions: complete and accurate?
     - Efficacy/performance claims: supported by qualification or evidence?
     - Source material authorization: video, BGM, images, fonts, portrait, brand assets.
     - 千川低质素材 patterns: product pile-up, 卖惨/演戏, picture carousel/big-character posters/high-saturation, black borders/watermarks/blur, unclear product subject, ingredient/size chart replacing product display.
     - Regulated category check: food, cosmetics, medical devices, drugs, maternal-child, pet, financial, education — qualification required.

4. **Apply platform references**
   - Cite platform category ids or article names where available.
   - When using recent examples, separate `官方/监管`, `媒体转述`, and `小红书讨论样本`; do not treat creator comments as binding rules.
   - When optional dynamic Xiaohongshu evidence is used, put it in a separate `动态小红书相似案例` section with search terms, sample date, note ids, and the evidence limitation.
   - Prefer the most specific matching category. If multiple categories apply, list all but mark the primary risk.
   - When the platform rule depends on account history or qualifications that are not available, mark `待核验`.
   - Beyond official rules, platforms have many unwritten/隐形 rules. Treat creator-posted experience and comment-section discussion in the case files as a valuable supplement that surfaces these hidden enforcement patterns — but as symptoms and disputed edge cases, not as binding rules.

5. **Classify severity**
   - `Blocker`: clear illegal/high-risk violation, severe platform red line, likely takedown, user safety/property risk, unqualified regulated advice/marketing, porn/gambling/fraud, unmasked gore/death/sexual assault/minor harm, obvious unauthorized搬运, risky contact or off-platform diversion.
   - `High`: likely platform violation or strong enforcement risk; publish only after edits or proof is added.
   - `Medium`: ambiguous or context-dependent risk; revise, add context/disclosure, thicken masks, remove risky phrasing, or retain evidence.
   - `Low`: minor wording/UX/quality risk; monitor or polish.
   - `Pass`: no material risk found in the reviewed evidence.

6. **Write concrete fixes**
   - For audio risks: mute/beep exact ranges and rewrite subtitles/cards.
   - For visual risks: cut, replace, blur/mosaic, crop away, thicken masks, avoid using as cover/opening.
   - For claims: remove absolutes, add verifiable source/context, avoid guaranteed outcomes, disclose ad/marketing nature, align link price/gift/specs.
   - For regulated topics: remove advice/marketing, add verified qualification evidence, or convert to general non-prescriptive information.
   - For rights: replace with authorized/original material; attribution alone does not cure unauthorized use.
   - For inducement/diversion: remove coercive CTA, off-platform contacts, QR codes, risky private-message funnels, and fake benefits.

## Evidence Standards

Every finding should include at least one evidence pointer:

- Video timecode or frame range.
- Script/subtitle line.
- Cover/title/caption/comment/product-link text.
- Screenshot/frame description.
- Missing proof: authorization, qualification, source, product price, activity scope, link consistency.
- For platform discussion evidence: keyword searched, note id or visible account, comment evidence if used, publish date, sample date, and whether it is official-account material or creator-side discussion.

Do not report a violation solely because a topic is sensitive. Explain what visible/audible element creates the risk and which rule it maps to.

## E-Commerce Entry Points

The same Skill supports three e-commerce review entry points. Choose the right one based on the user's stage:

### 入口 1: 发布前合规 (Pre-Publish Compliance)

Full review of the complete video package before publishing:

- Run all universal risk areas + e-commerce product consistency.
- Load all relevant platform references + e-commerce references.
- Output full Markdown report + optional machine-readable JSON.
- `Blocker` or unaccepted `High` = must not publish.

Use when: "交付前审核"、"发布前跑一遍"、"check this video before publishing".

### 入口 2: 选品前风险 (Pre-Selection Risk)

Quick risk screen before the creator commits to promoting a product:

- Check if the product category is regulated (medical, food, cosmetic, maternal-child, pet, financial, education).
- Flag missing qualifications.
- Flag high-risk claim patterns in the product detail page itself.
- Output a condensed risk score + blocker list.

Use when: "帮我看看这个品能不能带"、"选品前风险排查"、"这个商品有没有违规风险".

### 入口 3: 文案生成前风险 (Pre-Copywriting Risk)

Scan the product's claims before writing scripts:

- Extract every claim from the product detail page.
- Classify as safe/risky/forbidden.
- Generate a forbidden-expression list for the copywriter.
- Flag claims that need qualification proof before they can be used.

Use when: "写文案前帮我扫一遍商品"、"这个品的禁用词有哪些"、"生成前风险检查".

## Machine-Readable Output

When the user asks for structured output, or when the report feeds into another Skill (e.g. `capsule-cinema`, `commerce-selection-advisor`, or a 飞书审批 flow), output both Markdown and JSON:

```json
{
  "platform": "douyin",
  "content_type": "commerce_video",
  "risk_level": "high",
  "rule_version": "douyin-ecommerce-2026-08",
  "findings": [
    {
      "severity": "high",
      "rule_id": "商品三一致-规格",
      "evidence": "口播 00:12；详情页 SKU",
      "reason": "视频口播数量与商品详情页不一致",
      "fix": "统一口播、画面和详情页数量"
    }
  ],
  "pending_verification": ["商品资质", "素材授权"],
  "reviewed_at": "2026-08-11T10:00:00+08:00"
}
```

Field definitions:
- `rule_id`: use labels from the e-commerce reference files (e.g. `商品三一致-规格`, `千川低质素材 卖惨/演戏/炒作`, `电商功效声明 效果承诺`).
- `severity`: `blocker` | `high` | `medium` | `low` | `pass`.
- `evidence`: video timecode, script line, detail page section, screenshot reference.
- `pending_verification`: list of items that could not be verified with the available evidence.

## Report Format

Use this structure for serious reviews:

```markdown
# 合规风险审核

- 平台: <platforms>
- 内容范围: <video/script/cover/copy/link/etc.>
- 结论: Pass | Low | Medium | High | Blocker
- 最高风险: <one sentence>

## 风险明细

| 等级 | 平台/条款 | 证据位置 | 风险说明 | 修改建议 |
| --- | --- | --- | --- | --- |
| High | 视频号 4.11.1 | 口播 00:12 / 标题 | 使用无法核验的销售数据 | 删除数字或补充可验证来源 |

## 待核验

- <authorization/qualification/link consistency/source provenance/etc.>

## 发布前复审清单

- [ ] 风险音频已消音或替换
- [ ] 风险字幕/封面/标题已改写
- [ ] 敏感画面已删除或充分打码
- [ ] 商品链接、价格、赠品、规格与视频一致
- [ ] 医疗/金融/法律等资质已核验或相关内容已移除
- [ ] 版权、肖像、隐私、商标授权已核验
```

For quick reviews, keep the same fields but collapse the table to bullets.

### E-Commerce Extended Report

When reviewing带货 content, add a product-consistency table after the main risk table:

```markdown
## 商品一致性审核

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 视频展示商品 vs 商品详情页 | 一致 / 不一致 / 待核验 | 画面时间点；详情页截图 |
| 口播规格 vs SKU 规格 | 一致 / 不一致 / 待核验 | 口播时间点；SKU 页面 |
| 口播价格 vs 商品链接价格 | 一致 / 不一致 / 待核验 | 口播时间点；链接价格 |
| 赠品/红包条件是否完整 | 完整 / 缺条件 / 待核验 | 口播时间点；活动规则页 |
| 功效表达是否有资质证据 | 有证据 / 高风险 / 待核验 | 证据来源；资质文件 |
| 来源素材是否有授权 | 有 / 无 / 待核验 | 授权文件 |

## 千川低质素材检查

| 类别 | 是否触发 | 证据/说明 |
| --- | --- | --- |
| 商品堆砌式累加 | 是/否 | |
| 品牌/款式/颜色/形状不一致 | 是/否 | |
| 数量/重量/规格不一致 | 是/否 | |
| 卖惨/演戏/炒作/清仓话术 | 是/否 | |
| 价格/赠品信息不完整 | 是/否 | |
| 污垢/血腥/危险/恶俗/不适 | 是/否 | |
| 图片轮播/大字报/高饱和配色 | 是/否 | |
| 黑边/遮挡/水印/模糊变形 | 是/否 | |
| 商品主体不明确 | 是/否 | |
| 素材授权 | 是/否 | |
```

## E-Commerce Tools

Two optional scripts supplement e-commerce reviews with automated checks. Use them when the user provides structured data (product JSON + claims JSON) or text to scan:

### `tools/compare_product_link.py`

Paired comparison of product detail page info versus video claims:

```bash
python tools/compare_product_link.py \
  --product product_info.json \
  --claims video_claims.json \
  --format markdown|json
```

Output: brand, style/color, specs, price, gift, deadline consistency results + regulated-category risk flag + 千川 checklist.

### `tools/extract_claims.py`

Scan script/subtitle/copy text for risky claims before writing or reviewing:

```bash
python tools/extract_claims.py \
  --file script.txt \
  --format markdown|json
```

Output: forbidden expressions (must delete), risky expressions (should rewrite), and items needing evidence — each with a suggested fix.

Both tools output JSON for machine-to-machine handoffs (e.g. `capsule-cinema`, `commerce-selection-advisor`, 飞书审批).

## Video Workflow Integration

When reviewing a final video package:

- Save the report as `qa/compliance_review.md` when the project has a release package.
- If the package separates public/internal files, keep risk notes in `qa/` or `internal/`, not in publishable `public/` copy.
- Update the release manifest or handoff notes with the compliance report path and final risk level.
- Do not call a video final if there is any unresolved `Blocker` or unaccepted `High` risk.

## Common Mistakes

- Treating subtitle rewrite as enough while risky audio remains audible.
- Reviewing only the script and missing cover/opening-frame risks.
- Assuming public material is safe because it came from another platform.
- Treating 小红书 creator notes or comments as official platform rules instead of discussion samples.
- Using "仅供参考" to keep medical, financial, legal, or guaranteed-effect claims that still require qualification or proof.
- Leaving product prices, gifts, quantities, or activity deadlines inconsistent with the linked item.
- Hiding uncertain source provenance instead of marking it `待核验`.
- Reviewing带货 content without loading e-commerce references (`douyin-ecommerce.md`, `qianchuan-low-quality.md`, `ecommerce-claims.md`).
- Treating product claims from the detail page as verified facts without checking qualifications.
- Missing 千川低质素材 patterns (picture carousel, big-character posters, black borders) that don't look like rule violations but trigger promotion rejection.
- Skipping the product-consistency check: video display, voiceover, subtitles, and product link must all agree on brand, specs, price, and gifts.
- Marking regulated-category products (食品, 化妆品, 医疗器械, 母婴, 宠物, 金融) as Pass without qualification evidence.
