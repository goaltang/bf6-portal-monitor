[English](README_EN.md)

# BF6 Portal 体验监控器 v5（已知码库交叉验证 + 发布日期）

多社区监控《战地 6》(Battlefield 6) Portal 体验码，发现新码实时推送到飞书
（默认通过 lark-cli 发到监控群，也可配置群 webhook 或 P2P 直发）。
v4 起对 YouTube/Reddit 源的每个新码自动拉取来源评论做**社区反馈验证**，
在推送里标注该码 ✅可能有效 / ⚠️不确定 / ❌可能失效。
v5 起新增**已知码库交叉验证**（候选码与 bfportal.gg 全量码库比对，
推送标注 已收录/未收录，根治英文单词类误报）和**发布日期**（三源推送
均附"发布:"行，便于判断码的新鲜度）。

## 背景

BF6 官方经常封禁刷枪/刷经验的 Portal 社区服务器，一个体验码的"保鲜期"
往往只有几小时。本工具每 5 分钟扫一次三个社区数据源，第一时间把新码推到
飞书，抢在别人前面进服。

## 三个数据源

| 源 | 机制 | 可靠性/延迟特性 |
|---|---|---|
| **bfportal.gg**（主源） | 官方 REST API，码是结构化字段 | **最可靠，零误报**；取决于玩家提交速度 |
| **YouTube** | yt-dlp 搜索刷码视频，从标题/描述提取码 | **最快**（视频发布即出现），但信息杂、有误报风险 |
| **Reddit**（Arctic Shift 存档镜像） | 扫描 3 个版块的新帖/评论提取码 | 存档有几秒~几分钟**同步延迟**；官方 .json 对本机 IP 已封锁，必须走镜像 |

### 源1：bfportal.gg

[bfportal.gg](https://bfportal.gg) 是社区维护的开源 Battlefield Portal
体验码库网站，收录玩家发布的 Portal 体验（含体验码、刷枪标记、失效状态等
结构化信息），并提供公开 REST API。

- 列表：`GET https://bfportal.gg/api/experiences/?order=-id&limit=20`
  - **必须显式带 `order=-id`**，否则返回顺序不是按新的
  - 列表混有 `HomePage` / `ExperiencesPage` 等非体验条目，程序按
    `meta.type == "core.ExperiencePage"` 过滤
- 详情：`GET https://bfportal.gg/api/experiences/{id}/`，含
  `code` / `xp_farm` / `broken` / `description` / `owner` / `meta.html_url`
- 过滤：`code` 为空/null/字符串 "None" 跳过；`broken=true` 跳过；
  `xp_farm=true` 的消息标注 🔥刷枪服务器

### 源2：YouTube

本机 `yt-dlp`（2026.07.04 实测可用）子进程搜索，三组关键词**轮询**
（每轮用一组，下轮换下一组）：

- `battlefield 6 portal code`
- `bf6 xp farm portal`
- `bf6 portal code bot lobby`

每组 `ytsearch15`，用 `--flat-playlist --print` 拿 id/标题/频道/播放量
（分隔符用 `|||`，因为标题里常含 `|`）。新视频（按 video id 去重）从标题
提码；另对**最多 5 个**新视频追加抓取描述（`--skip-download --print`）再
提码，控制单轮耗时。输出里混入的 `WARNING`/`ERROR` 行解析时过滤。

### 源3：Reddit（Arctic Shift 镜像）

Reddit 官方 `.json`/`.rss` 对本机 IP 已封锁，用存档镜像
`https://arctic-shift.photon-reddit.com/api`（实测可用）：

- `GET /api/posts/search?subreddit=<sub>&limit=50&sort=desc`
- `GET /api/comments/search?subreddit=<sub>&limit=50&sort=desc`
  （comments 接口不支持 query 参数；不要传 fields——permalink 不在其支持列表）

版块：`BattlefieldPortal` / `Battlefield` / `battlefield6`，共 6 条数据流
（版块 × 帖子/评论）。按每条流的 `created_utc` **水位线**取增量；首次接入
回溯 1 小时建基线。注意镜像有存档延迟，且晚入库的旧帖若早于水位线会漏掉
（可接受的代价）。

## 体验码提取（YouTube/Reddit 共用）

码格式：4-6 位字母数字，大小写敏感（推送保留原样）。`extract_codes()`
分层提取：

1. **显式引导**（高置信）：`code:` / `portal:` / `server code` 等引导词后
   冒号/连字符/空格直接跟码，允许纯字母码（如 `portal: MPHD`）
2. **松散语境**：token 紧邻 portal/experience/server/lobby/code 等引导词，
   要求同时含字母+数字
3. **冒号/逗号引出**：token 前是 `:` 或 `,`，且附近 150 字符内有模式/地图/
   刷枪语境词（deathmatch/conquest/xp/farm/bot/contaminated/mirak/cairo 等），
   要求同时含字母+数字
4. **黑名单兜底**：常见英文词（ENTIRE/CLASS/CUSTOM…）、游戏名
   （BF2042/PS5…）、数字单位（99ms/1080p/4GB/500XP…）一律过滤；提取前
   先把 URL 整体抹掉（discord.gg 邀请码片段、视频 id 不当码）

另有的启发式（实测数据调出来的）：纯数字串不当码（年份/数量误报率高）；
**纯小写的纯字母串不当码**（YouTube 描述教程文里的 menu/option/shown 等
散文单词；真实纯字母码是大写的）。误报样本见 `test_extract_codes.py`。

**误报风险客观存在**（YouTube/Reddit 源是正则推测，不是结构化字段），
推送里带来源和上下文说明，便于人工甄别。

## 评论验证（v4 新增）

对 YouTube/Reddit 抓到的每个新码，去它来源的视频/帖子拉评论，统计社区
反馈里的正/负信号关键词，推断码是否还有效。bfportal.gg 是码库网站没有
用户评论区，**不做验证**（推送保持 v3 格式）。

### 评论抓取

| 源 | 接口（均已实测可用） |
|---|---|
| Reddit | `GET https://arctic-shift.photon-reddit.com/api/comments/search?link_id=<post_id>&limit=30`（帖子 id 不带 t3_ 前缀也行；评论里的码按其父帖 link_id 拉） |
| YouTube | `yt-dlp --skip-download --write-comments --extractor-args "youtube:max_comments=30" --print "%(comments)j" <视频URL>` |

注意：本机 yt-dlp（2026.07.04）的 `%(comments)s` 输出 Python repr 而非
JSON，**必须用 `%(comments)j`**；输出混入的 WARNING/ERROR 行解析前过滤
（解析另带 `ast.literal_eval` repr 兜底）。

抓取控制（防慢/防封）：

- 每个码最多拉 **30 条评论**（Reddit `limit=30` / YouTube `max_comments=30`）
- 每轮监控最多对 **5 个码**做评论验证（预算用完后续码照常推送、不带反馈行）
- 只对有码的视频/帖子拉评论；验证**无状态**，每次重新拉，state.json 不变
- 评论抓取失败不阻塞推码，降级为 `⚠️ 不确定 (无评论数据)`
- `--no-verify` 完全跳过验证（调试用，消息保持 v3 格式）

### 评级逻辑

关键词库（英文、小写、整词匹配；评论与关键词都先转小写、去撇号、压缩
空白，故 `doesn't work`/`doesnt work`、`won't work`/`wont work` 等价）：

- **正面信号**（码可能有效）：worked, works, still working, still works,
  confirmed, valid, legit, thanks, got xp, leveling, fast, amazing, insane,
  love, great, perfect, awesome
- **负面信号**（码可能失效）：patched, banned, doesn't work, doesnt work,
  not working, dead, removed, nerfed, error, kicked, fixed, no longer, gone,
  invalid, broken, stopped working, wont work

每条评论最多贡献一个信号（同时命中正/负时**取负面**，负面信号更强）；
然后按信号条数评级：

| 评级 | 条件 |
|---|---|
| ✅ 可能有效 | 正面 ≥ 2 且 负面 = 0 |
| ❌ 可能失效 | 负面 ≥ 1 且 负面 ≥ 正面 |
| ⚠️ 不确定 | 其余情况（信号混杂、无信号等）；评论数 < 3 直接标 ⚠️ 样本不足 |

核心函数 `verify_code_feedback(source_type, source_id, code)` 返回
`(rating, pos_count, neg_count, comment_count, top_comments)`；
`comment_count == -1` 表示评论抓取失败。top_comments 是至多 3 条带信号
（👍正/👎负）的最相关评论（按点赞排序），只写日志不进推送消息。

## 码库交叉验证（v5 新增）

### 原理

[bfportal.gg](https://bfportal.gg) 本身就是全量 Portal 码库（约 643 个
体验），API 可批量拉取（实测无限流）。程序把全量码拉下来建本地索引
`code_index.json`，YouTube/Reddit 提取出的候选码与索引比对：

- 候选码**在码库中** → 高置信，推送附 `码库: ✅ 已收录 (体验标题)`
- 候选码**不在码库中** → 仍推送（新码可能还没入库），附 `码库: ➖ 未收录`

这样英文单词/SEO 词类误报因永远不在码库里会被标注出来，真实码不受
影响，**召回不降**。bfportal.gg 源自身就是码库，不需要比对。索引完全
不可用时（首建失败且无旧索引）推送不附码库行，不阻塞推码。

### 索引构建与维护

- 索引文件 `code_index.json`：
  `{"built_at": ISO时间, "count": N, "codes": {"小写码": {"code": 原样, "title", "owner", "broken"}}}`，
  键为小写码（**比对大小写不敏感，展示保留原始大小写**）
- 构建流程：列表 `?order=-id&limit=100&offset=N` 分页拿全部体验 id
  （过滤 `meta.type=="core.ExperiencePage"`），再逐条拉详情取
  `code/title/owner.username/broken`（User-Agent `python:bf6-monitor/3.0`）
- 耗时：约 643 条详情 × ~0.8s ≈ **9 分钟**，只在启动/过期时跑；
  每 50 条打一条进度日志
- 时机：**启动时**检查，不存在或 `built_at` 超过 **24 小时**自动重建；
  常驻运行期间每轮也会检查过期（重建失败最多每小时重试一次）
- 降级：重建失败用旧索引继续跑；没有旧索引则推送不带码库行
- `python3 bf6_portal_monitor.py --rebuild-index`：强制全量重建后退出
  （维护命令，不跑监控）
- 索引时间戳只存在 `code_index.json` 的 `built_at` 里，state.json 不重复存

## 发布日期（v5 新增）

三源推送都新增"发布:"行，便于判断码的新鲜度：

| 源 | 数据源字段 | 格式 |
|---|---|---|
| YouTube | `upload_date`（flat-playlist 拿不到，对单视频抓详情；与标题/描述**共用同一次** `--print` 调用，不多跑 yt-dlp） | `YYYY-MM-DD` |
| Reddit | `created_utc`（unix 时间戳） | `YYYY-MM-DD HH:MM UTC` |
| bfportal.gg | `meta.first_published_at`（ISO） | `YYYY-MM-DD` |

注意：YouTube 只对抓了描述的新视频（每轮最多 5 个）才有发布日期；
仅从标题提码的视频不带"发布"行。

## 环境要求

- Python 3.8+，**只用标准库**（urllib + subprocess 调 yt-dlp），无第三方包
- 本机装有 `yt-dlp`（YouTube 源必需；缺失时该源记日志跳过，不影响其他源）
- 不要用 requests 重写网络部分：本机 requests 经常 TLS 超时，urllib/curl 正常
- HTTP 请求带 3 次指数退避重试

## 通知配置（可选）

**默认无需任何配置**：通知走本机已安装并认证的 `lark-cli`，发到 BF6
Portal 监控通知群（`chat:oc_d1c86d84192d65595962a1ef4e105763`）。

| 环境变量 | 说明 |
|---|---|
| `FEISHU_TARGET` | 可选。lark-cli 通路的目标。`chat:oc_xxx` 发群；`user:ou_xxx` P2P 直发；无前缀按 `chat:` 处理 |
| `FEISHU_WEBHOOK` | 可选。飞书群自定义机器人 webhook。**设置后优先于 lark-cli** |
| `FEISHU_SECRET` | 可选。机器人"加签"密钥（HMAC-SHA256）；仅 webhook 通路使用 |

## 运行

```bash
python3 bf6_portal_monitor.py                        # 持续轮询，默认 300 秒一轮，三源全跑
python3 bf6_portal_monitor.py --once                 # 只跑一轮后退出
python3 bf6_portal_monitor.py --interval 60          # 自定义间隔（秒，最小 15）
python3 bf6_portal_monitor.py --sources youtube,reddit  # 只跑指定源（bfportal,youtube,reddit 逗号分隔）
python3 bf6_portal_monitor.py --once --backfill 5    # bfportal 首跑回溯推送最近 5 条（演示用）
python3 bf6_portal_monitor.py --once --no-verify     # 跳过评论反馈验证直接推码（调试用）
python3 bf6_portal_monitor.py --rebuild-index        # 强制全量重建码库索引后退出（约 9 分钟）

# 后台常驻
nohup python3 bf6_portal_monitor.py >> run.log 2>&1 &
```

首次运行行为：

- **码库索引**：无 code_index.json 时先全量建库（约 9 分钟）再开始监控
- **bfportal**：以当前最大体验 id 建基线，不推历史（`--backfill N` 除外）
- **YouTube**：当前搜索结果全部建基线；提取到码会直接推送
- **Reddit**：每条数据流回溯 1 小时建基线，窗口内的码会推送

单源失败（网络/yt-dlp 异常）记日志跳过，不影响其他源；每源每轮推送上限
10 条，防止首跑洪水。

## 推送消息格式

bfportal.gg 新体验：

```
🎯 新 Portal 体验: 030 Portal Lab
码: 1ZC5T
🔥 刷枪服务器          ← 仅当 xp_farm=true
玩家/Bot: 64/99
作者: xxx
发布: 2026-08-03       ← v5 新增（meta.first_published_at）
说明: <description 前 150 字符，已去 markdown 符号>
https://bfportal.gg/experiences/xxx/
```

YouTube 新码（v5 含发布行 + 码库行）：

```
📺 YouTube 新码: 1Y8CM
视频: NEW BF6 WEAPON XP FARM 2 V 64 BOTS //CODE 1Y8CM
频道: Sensation
发布: 2026-08-03       ← v5 新增（仅抓了描述的视频才有）
说明: <码附近一句话>
码库: ➖ 未收录         ← v5 新增（命中时：码库: ✅ 已收录 (体验标题)）
社区反馈: ✅ 可能有效 (正面3/负面0, 评论12条)
https://www.youtube.com/watch?v=<id>
```

Reddit 新码（v5 含发布行 + 码库行）：

```
💬 Reddit 新码: ZS57D
来源: r/battlefield6 (帖子)
标题: <帖子标题>          ← 评论没有标题，省略此行
发布: 2026-08-04 12:34 UTC   ← v5 新增
说明: <码附近一句话>
码库: ✅ 已收录 (BLACKSITE: ASCENDANT)   ← v5 新增（未收录时：码库: ➖ 未收录）
社区反馈: ❌ 可能失效 (正面0/负面2, 评论8条)
https://www.reddit.com<permalink>
```

社区反馈行的三种形态：

- `社区反馈: ✅ 可能有效 (正面N/负面M, 评论K条)`（或 ❌/⚠️）
- `社区反馈: ⚠️ 不确定 (样本不足, 评论K条)` —— 评论数 < 3
- `社区反馈: ⚠️ 不确定 (无评论数据)` —— 评论抓取失败/该源无评论

`--no-verify` 或当轮验证预算（5 个码）用尽时，消息不带社区反馈行
（与 v3 格式相同）。码库索引不可用时不带"码库"行。

## 状态文件 state.json

```json
{
  "version": 3,
  "bfportal": { "max_seen_id": 1273 },
  "youtube":  { "keyword_index": 0, "seen_videos": ["..."] },
  "reddit":   { "watermarks": {"BattlefieldPortal:posts": 1785860145}, "seen_posts": ["posts:..."] }
}
```

- 自动从 v2 状态（`{"version": 2, "max_seen_id": N}`）升级，bfportal 基线保留
- YouTube 按 video id 去重（保留最近 500 个）；Reddit 按 created_utc
  水位线 + 已见 id（保留最近 1000 个）双重去重
- 删掉 state.json 即完全重置（三源各自重建基线）
- 码库索引的构建时间存在 `code_index.json` 的 `built_at` 字段里，
  state.json 不重复存

## 文件说明

| 文件 | 说明 |
|---|---|
| `bf6_portal_monitor.py` | 主程序（单文件，纯标准库） |
| `code_index.json` | 自动生成：bfportal.gg 全量码库索引（v5），约 643 条码，24 小时过期自动重建 |
| `test_extract_codes.py` | 码提取单元测试（32 用例，含真实码样本与误报样本）：`python3 test_extract_codes.py` |
| `test_feedback.py` | 评论反馈验证单元测试（评级逻辑/关键词分类/消息格式，无网络）：`python3 test_feedback.py` |
| `test_code_index.py` | 码库交叉验证单元测试（假码库比对：收录/未收录/大小写/过期/降级，无网络）：`python3 test_code_index.py` |
| `manual_push_format_v1.py` / `manual_push_format_v3.py` | 飞书推送格式验证脚本（会真实发消息；由 test_push_format.py / test_v3_push_format.py 改名，避免 pytest 误收集真实发送） |
| `test_v4_push_format.py` | v4 格式验证：现场拉评论验证 + 发一条标注"格式测试"的消息 |
| `test_v5_push_format.py` | v5 格式验证：现场抓发布日期+码库比对 + 发一条标注"格式测试"的三源样例消息 |
| `state.json` | 自动生成，见上文 |
| `rebuild_index.log` | `--rebuild-index` 全量重建的运行日志 |
| `monitor.log` / `run*.log` | 历史运行日志 |

## 常见问题

- **码会重复推送吗？** 各源独立去重：bfportal 按体验 id 水位线；YouTube 按
  video id；Reddit 按 created_utc 水位线 + 已见 id。同一轮内同名码只推一次。
- **误报怎么办？** 三道防线：① 提取层黑名单+分层规则压误报；② v5 码库
  交叉验证——英文单词类误报永远不在 bfportal.gg 码库里，推送会标
  `码库: ➖ 未收录`，真实已收录码标 `✅ 已收录 (体验标题)`；③ 推送带
  来源/上下文便于人工甄别。bfportal.gg 源零误报。
- **码库索引多久更新？** `built_at` 超过 24 小时自动重建（约 9 分钟，
  重建期间用旧索引/不阻塞）；也可 `--rebuild-index` 手动强制重建。
  码库刚收录的新码在索引重建前会显示"未收录"，属正常延迟。
- **某个源挂了会影响其他源吗？** 不会。每源独立 try/except，失败只记日志。
- **v2 的 state.json 还能用吗？** 能，自动升级为 v3 并保留 bfportal 基线。
- **社区反馈评级可信吗？** 只是关键词启发式，样本少或评论跑题时会不准
  （所以有"样本不足/不确定"档）；推送里的 top 评论摘录写在运行日志里，
  可人工复核。验证失败/超时永远不会阻塞推码。
