#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BF6 Portal 体验监控器 v5（已知码库交叉验证 + 发布日期）。

数据源：
- bfportal.gg（主源）：官方 REST API，码是结构化字段，零误报，最可靠
- YouTube：yt-dlp 搜索刷码相关视频，从标题/描述里分层提取体验码（最快但杂）
- Reddit：Arctic Shift 存档镜像（官方 .json/.rss 对本机 IP 已封锁），
  扫描 BattlefieldPortal / Battlefield / battlefield6 的新帖与评论（有存档延迟）

YouTube/Reddit 源的码由 extract_codes() 分层提取（显式引导词 > 松散语境 >
冒号/逗号语境），黑名单过滤常见误报；bfportal.gg 的码直接取结构化字段。

v4 评论反馈验证：YouTube/Reddit 抓到的每个码，去来源视频/帖子拉评论
（每码最多 30 条，每轮最多验 5 个码），按正/负关键词统计社区反馈，给出
✅可能有效 / ⚠️不确定 / ❌可能失效 评级，附在推送消息的"社区反馈"行。
bfportal.gg 无用户评论区，不做验证。验证失败/无评论不阻塞推送（降级⚠️）。

v5 新增已知码库交叉验证：启动/过期时全量拉取 bfportal.gg 码库（约 643
个体验，列表分页 + 逐条详情，约 9 分钟）建本地索引 code_index.json
（24 小时过期自动重建）。extract_codes() 的候选码按小写与索引比对：
命中 → 推送附"码库: ✅ 已收录 (体验标题)"；未命中 → 仍推送但标注
"码库: ➖ 未收录"（英文单词类误报永远不在码库里，会被标注；真实新码
召回不降）。索引不可用时不附码库行，不阻塞推送。--rebuild-index 强制
重建后退出。

v5 新增发布日期：YouTube 取 upload_date（与标题/描述同一次 yt-dlp
--print 调用），Reddit 取 created_utc，bfportal.gg 取 meta.first_published_at，
统一渲染为推送消息的"发布:"行（YouTube/bfportal 为 YYYY-MM-DD，Reddit
为 YYYY-MM-DD HH:MM UTC）。

仅依赖 Python 标准库（urllib + subprocess 调 yt-dlp）；本机 requests 常
TLS 超时，勿改用。

用法：
    python3 bf6_portal_monitor.py                        # 持续轮询，默认 300 秒一轮，三源全跑
    python3 bf6_portal_monitor.py --once                 # 只跑一轮后退出
    python3 bf6_portal_monitor.py --interval 60          # 自定义间隔（秒，最小 15）
    python3 bf6_portal_monitor.py --sources youtube,reddit  # 只跑指定源（逗号分隔）
    python3 bf6_portal_monitor.py --once --backfill 5    # bfportal 首跑回溯推送最近 5 条（演示用）
    python3 bf6_portal_monitor.py --once --no-verify     # 跳过评论验证直接推码（调试用）
    python3 bf6_portal_monitor.py --rebuild-index        # 强制全量重建码库索引后退出

环境变量：
    FEISHU_WEBHOOK  可选。若设置则优先走群机器人 webhook（保留原逻辑）
    FEISHU_SECRET   可选，机器人加签密钥（HMAC-SHA256），仅 webhook 通路使用
    FEISHU_TARGET   可选，未设置 FEISHU_WEBHOOK 时通过本机 lark-cli 发送。
                    支持 chat:oc_xxx（发到群）/ user:ou_xxx（P2P 直发）；
                    无前缀按 chat 处理。
"""

import argparse
import ast
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------- 基本配置

API_BASE = "https://bfportal.gg/api"
EXPERIENCE_TYPE = "core.ExperiencePage"  # 列表中混有 HomePage/ExperiencesPage，只保留此类

USER_AGENT = "python:bf6-portal-monitor:v4.0"
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
LIST_LIMIT = 20          # 每轮列表拉取条数（按 -id 降序）
DEFAULT_INTERVAL = 300   # 默认轮询间隔（秒）
DESC_LIMIT = 150         # 推送消息里描述截断长度

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")

# ---- 已知码库索引（v5）
CODE_INDEX_FILE = os.path.join(BASE_DIR, "code_index.json")
INDEX_USER_AGENT = "python:bf6-monitor/3.0"  # 码库 API 实测好用的 UA（任务规格指定）
INDEX_PAGE_LIMIT = 100          # 码库列表单页条数（实测最大 100）
INDEX_MAX_AGE_SECONDS = 24 * 3600  # 索引超过 24 小时重建
INDEX_PROGRESS_EVERY = 50       # 详情全量拉取时每 N 条打一条进度日志

DEFAULT_FEISHU_TARGET = "chat:oc_d1c86d84192d65595962a1ef4e105763"  # BF6 Portal 监控通知群
LARK_CLI_TIMEOUT = 60

ALL_SOURCES = ("bfportal", "youtube", "reddit")
PUSH_CAP_PER_ROUND = 10  # 每源每轮推送上限，防止首跑/回溯洪水

# ---- YouTube（yt-dlp 子进程）
YT_KEYWORDS = [  # 轮询使用，每轮取一组，下轮换下一组
    "battlefield 6 portal code",
    "bf6 xp farm portal",
    "bf6 portal code bot lobby",
]
YT_SEARCH_SIZE = 15      # ytsearchN
YT_DESC_FETCH_MAX = 5    # 每轮最多抓描述的最新视频数（控制耗时）
YT_SEEN_LIMIT = 500      # state 中保留最近 N 个已见 video id
YT_DLP_TIMEOUT = 120     # 单个 yt-dlp 子进程超时（秒）
YT_DELIM = "|||"         # --print 字段分隔符（标题里常含 '|'，不能用单竖线）

# ---- Reddit（Arctic Shift 存档镜像；官方 .json 对本机 IP 已封锁）
ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"
REDDIT_SUBS = ["BattlefieldPortal", "Battlefield", "battlefield6"]
REDDIT_LIMIT = 50
REDDIT_BACKFILL_SECONDS = 3600  # 首次接入回溯 1 小时建基线
REDDIT_SEEN_LIMIT = 1000        # state 中保留最近 N 个已见帖子/评论 id

# ---- 评论反馈验证（v4；只作用于 YouTube/Reddit 源，bfportal.gg 无评论区不验证）
VERIFY_COMMENT_LIMIT = 30       # 每个码最多拉 30 条评论（防慢/防封）
VERIFY_CAP_PER_ROUND = 5        # 每轮监控最多对 5 个码拉评论（控制总耗时）
MIN_COMMENTS_FOR_RATING = 3     # 评论数少于此值直接标 ⚠️ 样本不足
TOP_COMMENTS_MAX = 3            # top_comments 保留最相关的 N 条
TOP_COMMENT_LEN = 80            # top_comments 单条文本截断长度

# ---- stdout/stderr 编码加固：GBK 控制台下 print emoji 会抛 UnicodeEncodeError，
# 被源级兜底 except 吞掉后该码静默不推送。模块级强制 UTF-8 + 替换兜底，
# import 本模块的测试脚本同样受益。reconfigure 需 3.7+，老解释器降级忽略。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- HTTP

def http_request(url, payload=None, user_agent=USER_AGENT):
    """GET（payload=None）或 POST JSON，带 3 次退避重试。返回解析后的 JSON。"""
    data = None
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last_err = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else {}
        except Exception as err:  # noqa: BLE001 网络异常全部兜底重试
            last_err = err
            if attempt < HTTP_RETRIES:
                wait = 2 ** attempt
                log(f"HTTP 请求失败（{attempt}/{HTTP_RETRIES}）{url} -> {err}，{wait}s 后重试")
                time.sleep(wait)
    raise RuntimeError(f"HTTP 请求失败（重试 {HTTP_RETRIES} 次后放弃）：{url} -> {last_err}")


# ---------------------------------------------------------------- 体验码提取（YouTube/Reddit 共用）
#
# 码格式：4-6 位字母数字，大小写敏感（保留原样）。分层提取：
#   L1 显式引导：code/portal/server/lobby 等引导词后紧跟冒号/连字符/空格，
#      允许纯字母码（如 "portal: MPHD"）
#   L2 松散语境：token 紧邻 portal/experience/server/lobby/code 等引导词，
#      要求同时含字母+数字
#   L3 冒号/逗号引出：token 前是 ":" 或 ","，且附近 150 字符内有模式/地图/
#      刷枪语境词（deathmatch/conquest/xp/farm/bot/contaminated/mirak/cairo 等），
#      要求同时含字母+数字
#   L4 黑名单兜底：常见英文词/游戏名/数字单位/URL 片段一律过滤；
#      纯数字 token 永不当码（年份/数量等误报率高）。
# 提取前先把 URL 整体抹掉（discord.gg 邀请码、视频 id 等不得被当码）。

CODE_CUE_ALTERNATION = (
    r"portal\s+codes?|experience\s+codes?|server\s+codes?|"
    r"codes?|portals?|servers?|lobb(?:y|ies)|experiences?"
)
EXPLICIT_CUE_RE = re.compile(
    r"\b(?:" + CODE_CUE_ALTERNATION + r")\b"
    r"\s*[:\-\u2013\u2014>]?\s*"
    r"(?<![A-Za-z0-9])([A-Za-z0-9]{4,6})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
CUE_WORD_RE = re.compile(r"\b(?:" + CODE_CUE_ALTERNATION + r")\b", re.IGNORECASE)
CODE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{4,6})(?![A-Za-z0-9])")
CONTEXT_WORD_RE = re.compile(
    r"\b(?:deathmatch|conquest|contaminat\w*|mirak|cairo|xp|farm\w*|grind\w*|level\w*"
    r"|unlock\w*|weapons?|bots?|portal|experience|servers?|lobb(?:y|ies)|codes?"
    r"|maps?|modes?|gamemode)\b",
    re.IGNORECASE,
)
URL_RE = re.compile(
    r"(?:https?://\S+|www\.\S+|discord\.gg/[A-Za-z0-9_\-]+|youtu\.be/[A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)
UNIT_TOKEN_RE = re.compile(
    r"^\d+(?:fps|ms|mins|min|ghz|mhz|khz|hz|mb|gb|tb|xp|hrs|hours|hour|days|day|p|k|m)$",
    re.IGNORECASE,
)
SNIPPET_LIMIT = 100
CUE_ADJACENCY = 30      # L2：token 与引导词之间的最大字符间隙
CONTEXT_WINDOW = 150    # L3：语境词搜索半径（字符）

BLACKLIST_WORDS = {
    # 常见英文词（标题大写风格里的高频词）
    "entire", "class", "classes", "custom", "customs",
    "code", "codes", "portal", "portals", "server", "servers",
    "lobby", "lobbies", "experience", "experiences",
    "farm", "farms", "farming", "level", "levels", "leveling",
    "rank", "ranks", "weapon", "weapons", "unlock", "unlocks", "unlocked",
    "secret", "secrets", "hidden", "epic", "insane", "crazy",
    "broken", "patch", "patches", "update", "updates", "updated", "beta",
    "trailer", "gameplay", "battlefield", "battlefiled",
    "conquest", "deathmatch", "infected", "contaminated", "contamination",
    "mirak", "cairo", "solo", "squad", "team", "teams", "rush",
    "free", "fire", "easy", "fast", "faster", "fastest", "best", "new", "newest",
    "working", "works", "fixed", "fixes", "glitch", "glitches", "bugged",
    "with", "your", "this", "that", "these", "those", "they", "them", "their",
    "have", "has", "been", "being", "into", "onto", "only", "more", "most",
    "much", "many", "some", "what", "when", "where", "which", "will",
    "would", "could", "should", "just", "like", "over", "under", "after",
    "before", "about", "here", "there", "from", "make", "makes", "made",
    "still", "every", "everyone", "also", "very", "really", "than", "then",
    "time", "times", "today", "season", "seasons", "official", "release",
    "leaked", "leaks", "news", "info", "need", "needs", "know", "known",
    "want", "wants", "look", "looks", "found", "find", "finds",
    "get", "gets", "getting", "use", "used", "using", "join", "joins",
    "play", "plays", "playing", "player", "players", "game", "games", "gaming",
    "video", "videos", "watch", "watching", "youtube", "reddit", "discord",
    "twitch", "link", "links", "comment", "comments", "post", "posts",
    "thread", "threads", "guide", "guides", "tutorial", "tutorials",
    "tips", "trick", "tricks", "help", "please", "thanks", "thank",
    "people", "good", "great", "awesome", "amazing", "never", "always",
    "maybe", "because", "through", "without", "within", "between", "around",
    "against", "another", "other", "others", "bots", "lobby",
    # YouTube 描述 SEO 关键词块里紧跟引导词的高频词（实测误报来源）
    "mode", "modes", "map", "maps", "tag", "tags", "setup", "setups",
    "guide", "guides", "host", "hosts", "hosting", "private", "public",
    "method", "methods", "list", "lists", "name", "names", "type", "types",
    "rule", "rules", "settings", "config", "configs", "preset", "presets",
    "loadout", "loadouts", "build", "builds", "invite", "invites",
    "channel", "channels", "playlist", "chapter", "chapters", "clip", "clips",
    "shorts", "stream", "streams", "social", "socials", "tiktok", "instagram",
    "patreon", "subscribe", "giveaway", "event", "events", "tier", "tiers",
    "sniper", "mastery", "progression", "challenge", "rotation", "routine",
    # 教程类描述里紧跟引导词的说明性词（实测误报来源）
    "menu", "menus", "option", "options", "shown", "show", "shows", "select",
    "enter", "browser", "button", "buttons", "screen", "screens", "field",
    "fields", "input", "inputs", "step", "steps", "below", "above", "follow",
    "check", "click", "press", "scroll", "section", "sections", "page",
    "pages", "match", "matches", "launch", "today",
    # 游戏/平台名
    "bf2042", "bf6", "bf4", "bfv", "bf1", "bfhardline",
    "xbox", "xboxone", "seriesx", "playstation", "switch", "nintendo",
    "steam", "origin", "eaapp", "dice", "ps5", "ps4", "psn",
}


def _snippet(text, start, end, limit=SNIPPET_LIMIT):
    """截取 token 附近一句话（按 .!?。！？\n;| 断句），压成单行并截断。"""
    bounds = ".!?。！？\n;|"
    lo = start
    while lo > 0 and text[lo - 1] not in bounds:
        lo -= 1
    hi = end
    while hi < len(text) and text[hi] not in bounds:
        hi += 1
    return " ".join(text[lo:hi].split())[:limit]


def extract_codes(text):
    """从文本中提取 Portal 体验码（YouTube 标题/描述、Reddit 帖子/评论共用）。

    返回 [{"code": 原样大小写, "snippet": 附近一句话, "layer": 1|2|3}]，
    按出现位置排序，按码（忽略大小写）去重、保留置信度更高的层。
    """
    if not text or not text.strip():
        return []
    cleaned = URL_RE.sub(" ", text)
    hits = {}  # code.lower() -> hit

    def accept(token, span, layer):
        if not any(c.isalpha() for c in token):
            return  # 纯数字不当码
        if layer >= 2 and not any(c.isdigit() for c in token):
            return  # L2/L3 要求字母+数字
        if token.isalpha() and token.islower():
            return  # 纯小写的纯字母串是散文单词（menu/option/shown…）；真实纯字母码是大写（MPHD）
        if token.lower() in BLACKLIST_WORDS or UNIT_TOKEN_RE.match(token):
            return  # L4 黑名单兜底
        key = token.lower()
        if key in hits and hits[key]["layer"] <= layer:
            return
        hits[key] = {
            "code": token,
            "snippet": _snippet(cleaned, span[0], span[1]),
            "layer": layer,
            "pos": span[0],
        }

    # L1：显式引导词
    for m in EXPLICIT_CUE_RE.finditer(cleaned):
        accept(m.group(1), m.span(1), 1)

    # L2：紧邻引导词；L3：冒号/逗号引出 + 语境词
    cue_spans = [m.span() for m in CUE_WORD_RE.finditer(cleaned)]
    for m in CODE_TOKEN_RE.finditer(cleaned):
        token = m.group(1)
        start, end = m.span(1)
        adjacent = any(
            (start >= cue_end and start - cue_end <= CUE_ADJACENCY)
            or (cue_start >= end and cue_start - end <= CUE_ADJACENCY)
            for cue_start, cue_end in cue_spans
        )
        if adjacent:
            accept(token, (start, end), 2)
            continue
        preceded = bool(re.search(r"[:,]\s*$", cleaned[:start]))
        if preceded:
            window = cleaned[max(0, start - CONTEXT_WINDOW):min(len(cleaned), end + CONTEXT_WINDOW)]
            if CONTEXT_WORD_RE.search(window):
                accept(token, (start, end), 3)

    result = sorted(hits.values(), key=lambda h: h["pos"])
    for h in result:
        h.pop("pos", None)
    return result


# ---------------------------------------------------------------- 评论反馈验证（v4）
#
# 对 YouTube/Reddit 抓到的每个码，去来源视频/帖子拉评论，按关键词统计社区
# 反馈推断码是否还有效。匹配规则：
#   - 评论与关键词都转小写、去掉撇号（' 与弯引号 ’）后按整词匹配，
#     因此 "doesn't work"/"doesnt work"、"won't work"/"wont work" 等价；
#   - 每条评论最多贡献一个信号：同时命中正/负时取负面（负面信号更强，
#     如 "works great but it got patched" 视为失效信号）；
#   - 评级无状态，每轮重新拉；抓取失败降级为 ⚠️（comment_count=-1 表示
#     无评论数据），不阻塞码推送。

POSITIVE_KEYWORDS = [  # 码可能有效
    "worked", "works", "still working", "still works", "confirmed", "valid",
    "legit", "thanks", "got xp", "leveling", "fast", "amazing", "insane",
    "love", "great", "perfect", "awesome",
]
NEGATIVE_KEYWORDS = [  # 码可能失效
    "patched", "banned", "doesn't work", "doesnt work", "not working", "dead",
    "removed", "nerfed", "error", "kicked", "fixed", "no longer", "gone",
    "invalid", "broken", "stopped working", "wont work", "won't work",
]

RATING_VALID = "✅ 可能有效"
RATING_UNKNOWN = "⚠️ 不确定"
RATING_DEAD = "❌ 可能失效"


def _compile_keyword_patterns(keywords):
    """关键词 -> 整词匹配正则（去重；小写、去撇号后编译）。"""
    patterns, seen = [], set()
    for kw in keywords:
        norm = kw.lower().replace("'", "")
        if norm in seen:
            continue
        seen.add(norm)
        patterns.append(re.compile(r"(?<!\w)" + re.escape(norm) + r"(?!\w)"))
    return patterns


POSITIVE_PATTERNS = _compile_keyword_patterns(POSITIVE_KEYWORDS)
NEGATIVE_PATTERNS = _compile_keyword_patterns(NEGATIVE_KEYWORDS)


def _normalize_feedback_text(text):
    norm = (text or "").lower().replace("\u2018", "'").replace("\u2019", "'").replace("'", "")
    return " ".join(norm.split())  # 压缩连续空白，保证多词关键词（still working）可命中


def classify_comment(text):
    """判断单条评论的信号：'pos' / 'neg' / None（无信号）。

    同时命中正/负关键词时返回 'neg'（负面信号更强）。
    """
    norm = _normalize_feedback_text(text)
    if not norm.strip():
        return None
    if any(p.search(norm) for p in NEGATIVE_PATTERNS):
        return "neg"
    if any(p.search(norm) for p in POSITIVE_PATTERNS):
        return "pos"
    return None


def rate_comments(comments):
    """对一组评论评级。comments: [{"text": 文本, "score": 点赞数}]。

    返回 (rating, pos_count, neg_count, comment_count, top_comments)；
    top_comments 是最相关的至多 3 条带信号评论（👍正/👎负 前缀，按点赞排序）。
    """
    count = len(comments)
    pos_count = neg_count = 0
    signaled = []
    for c in comments:
        sig = classify_comment(c.get("text", ""))
        if sig is None:
            continue
        if sig == "pos":
            pos_count += 1
        else:
            neg_count += 1
        signaled.append((sig, c))

    if count < MIN_COMMENTS_FOR_RATING:
        rating = RATING_UNKNOWN  # 样本不足
    elif pos_count >= 2 and neg_count == 0:
        rating = RATING_VALID
    elif neg_count >= 1 and neg_count >= pos_count:
        rating = RATING_DEAD
    else:
        rating = RATING_UNKNOWN

    signaled.sort(key=lambda sc: sc[1].get("score") or 0, reverse=True)
    top_comments = []
    for sig, c in signaled[:TOP_COMMENTS_MAX]:
        mark = "👍" if sig == "pos" else "👎"
        snippet = " ".join((c.get("text") or "").split())[:TOP_COMMENT_LEN]
        top_comments.append(f"{mark} {snippet}")
    return rating, pos_count, neg_count, count, top_comments


def reddit_fetch_comments(post_id, limit=VERIFY_COMMENT_LIMIT):
    """按帖子 id 拉评论树（Arctic Shift），返回 [{"text","score"}]。

    post_id 带不带 t3_ 前缀都行。
    """
    post_id = str(post_id)
    if post_id.startswith("t3_"):
        post_id = post_id[3:]
    query = urllib.parse.urlencode({"link_id": post_id, "limit": limit})
    payload = http_request(f"{ARCTIC_BASE}/comments/search?{query}")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Arctic Shift 评论接口响应格式异常")
    return [
        {"text": it.get("body") or "", "score": it.get("score") or 0}
        for it in payload["data"] if isinstance(it, dict)
    ]


def youtube_fetch_comments(video_id, limit=VERIFY_COMMENT_LIMIT):
    """yt-dlp 拉视频评论（max_comments=limit），返回 [{"text","score"}]。

    用 %(comments)j 取标准 JSON（%(comments)s 在本机 yt-dlp 2026.07.04 输出
    Python repr 而非 JSON，不可用）；输出可能混入 WARNING 行，先过滤；
    无评论时打印 NA。
    """
    output = _run_yt_dlp([
        "--skip-download", "--write-comments",
        "--extractor-args", f"youtube:max_comments={limit}",
        "--print", "%(comments)j",
        f"https://www.youtube.com/watch?v={video_id}",
    ])
    text = "\n".join(_clean_yt_lines(output)).strip()
    if not text or text == "NA":
        return []
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = ast.literal_eval(text)  # 兜底：个别版本仍输出 Python repr
        except (ValueError, SyntaxError):
            raise RuntimeError("yt-dlp 评论输出无法解析为 JSON")
    if not isinstance(data, list):
        return []
    return [
        {"text": c.get("text") or "", "score": c.get("like_count") or 0}
        for c in data if isinstance(c, dict)
    ]


def verify_code_feedback(source_type, source_id, code):
    """验证一个码的社区反馈，返回 (rating, pos, neg, comment_count, top_comments)。

    source_type: "youtube" | "reddit"；source_id: video_id 或帖子 id。
    comment_count == -1 表示评论抓取失败（降级 ⚠️ 无评论数据）。
    """
    try:
        if source_type == "youtube":
            comments = youtube_fetch_comments(source_id)
        elif source_type == "reddit":
            comments = reddit_fetch_comments(source_id)
        else:
            raise ValueError(f"不支持评论验证的来源类型：{source_type}")
    except Exception as err:  # noqa: BLE001 评论抓取失败不阻塞推码
        log(f"评论拉取失败 code={code} {source_type}/{source_id}：{err}")
        return RATING_UNKNOWN, 0, 0, -1, []
    rating, pos, neg, count, top = rate_comments(comments)
    log(f"评论验证 code={code} {source_type}/{source_id}：{rating}（正面{pos}/负面{neg}，评论{count}条）")
    for line in top:
        log(f"  └ {line}")
    return rating, pos, neg, count, top


def format_feedback_line(rating, pos, neg, comment_count):
    """把验证结果渲染成推送消息里的"社区反馈"行。"""
    if comment_count < 0:
        detail = "无评论数据"
    elif comment_count < MIN_COMMENTS_FOR_RATING:
        detail = f"样本不足, 评论{comment_count}条"
    else:
        detail = f"正面{pos}/负面{neg}, 评论{comment_count}条"
    return f"社区反馈: {rating} ({detail})"


# ---------------------------------------------------------------- 发布日期（v5）

def _parse_iso_utc(value):
    """ISO8601 时间串（兼容 Z 后缀）-> 带 UTC 时区的 datetime；非法返回 None。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_date(value):
    """bfportal meta.first_published_at（ISO）-> YYYY-MM-DD；非法返回 ''。"""
    dt = _parse_iso_utc(value)
    return dt.strftime("%Y-%m-%d") if dt else ""


def format_upload_date(value):
    """yt-dlp upload_date（YYYYMMDD）-> YYYY-MM-DD；NA/非法返回 ''。"""
    if not value:
        return ""
    text = value.strip()
    if text == "NA" or not re.fullmatch(r"\d{8}", text):
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def format_created_utc(value):
    """Reddit created_utc（unix 时间戳）-> 'YYYY-MM-DD HH:MM UTC'；非法返回 ''。"""
    if not isinstance(value, (int, float)):
        return ""
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- 已知码库索引（v5）
#
# bfportal.gg 是全量 Portal 码库（约 643 个体验）。启动/过期时全量拉取建
# 本地索引 code_index.json（键为小写码，码大小写不敏感比对，展示用原始
# 大小写）。extract_codes() 的候选码与索引比对：命中 → 高置信，推送附
# "码库: ✅ 已收录 (体验标题)"；未命中 → 仍推送（新码可能还没入库）但
# 标注"码库: ➖ 未收录"。英文单词类误报永远不在码库里，会被标注；真实
# 码不受影响，召回不降。索引缺失/重建失败不阻塞推送（不附码库行）。

def load_code_index():
    """读取 code_index.json；缺失/损坏返回 None。"""
    if not os.path.exists(CODE_INDEX_FILE):
        return None
    try:
        with open(CODE_INDEX_FILE, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, ValueError) as err:
        log(f"code_index.json 读取失败：{err}")
        return None
    if not isinstance(index, dict) or not isinstance(index.get("codes"), dict):
        log("code_index.json 内容异常（忽略）")
        return None
    return index


def save_code_index(index):
    tmp = CODE_INDEX_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        os.replace(tmp, CODE_INDEX_FILE)
    except OSError as err:
        log(f"保存 code_index.json 失败：{err}")


def index_is_fresh(index):
    """索引非空且 built_at 距今不超过 INDEX_MAX_AGE_SECONDS。"""
    if not index or not index.get("codes"):
        return False
    built = _parse_iso_utc(index.get("built_at"))
    if built is None:
        return False
    age = datetime.now(timezone.utc) - built
    return age.total_seconds() < INDEX_MAX_AGE_SECONDS


def fetch_experience_ids():
    """列表分页（order=-id, limit=100, offset 翻页）收集全部体验 id（降序）。"""
    ids = []
    offset = 0
    total_count = None
    while True:
        query = urllib.parse.urlencode(
            {"order": "-id", "limit": INDEX_PAGE_LIMIT, "offset": offset}
        )
        payload = http_request(f"{API_BASE}/experiences/?{query}", user_agent=INDEX_USER_AGENT)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("码库列表接口响应格式异常")
        items = payload["items"]
        if total_count is None:
            total_count = (payload.get("meta") or {}).get("total_count")
            log(f"码库列表 total_count={total_count}")
        if not items:
            break
        page_ids = [
            it["id"] for it in items
            if isinstance(it, dict) and isinstance(it.get("id"), int)
            and (it.get("meta") or {}).get("type") == EXPERIENCE_TYPE
        ]
        ids.extend(page_ids)
        log(f"码库列表页 offset={offset}：本页 {len(items)} 条"
            f"（ExperiencePage {len(page_ids)}，累计 {len(ids)}）")
        offset += len(items)
        if len(items) < INDEX_PAGE_LIMIT:
            break
        if total_count is not None and offset >= total_count:
            break
    return ids


def build_code_index():
    """全量拉取码库建索引：列表分页拿 id，逐条拉详情取码。

    约 643 条详情 × ~0.8s ≈ 9 分钟（可接受，只在启动/过期时跑）；
    每 INDEX_PROGRESS_EVERY 条打一条进度日志。返回索引 dict 并写盘。
    """
    started = time.time()
    ids = fetch_experience_ids()
    if not ids:
        raise RuntimeError("码库列表为空，无法建索引")
    log(f"开始全量拉取 {len(ids)} 条体验详情（每 {INDEX_PROGRESS_EVERY} 条一条进度日志）…")
    codes = {}
    fetched = 0
    for i, exp_id in enumerate(ids, 1):
        try:
            detail = fetch_experience_detail(exp_id, user_agent=INDEX_USER_AGENT)
        except Exception as err:  # noqa: BLE001 单条失败跳过，不中断建库
            log(f"码库详情拉取失败 id={exp_id}，跳过：{err}")
            continue
        fetched += 1
        code = clean_code(detail.get("code"))
        if code:
            key = code.lower()
            # ids 按 id 降序，先遇到的是最新体验，重复码保留最新
            if key not in codes:
                codes[key] = {
                    "code": code,
                    "title": detail.get("title") or "-",
                    "owner": (detail.get("owner") or {}).get("username") or "-",
                    "broken": bool(detail.get("broken")),
                }
        if i % INDEX_PROGRESS_EVERY == 0 or i == len(ids):
            elapsed = int(time.time() - started)
            log(f"码库详情进度 {i}/{len(ids)}（有效码 {len(codes)}，成功 {fetched}，已耗时 {elapsed}s）")
    index = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(codes),
        "codes": codes,
    }
    save_code_index(index)
    log(f"码库索引构建完成：{len(codes)} 条码（拉取详情 {fetched}/{len(ids)} 条，"
        f"耗时 {int(time.time() - started)}s）-> {CODE_INDEX_FILE}")
    return index


def refresh_index_if_needed(force=False):
    """检查码库索引，不存在/过期/强制时重建；重建失败用旧的继续跑。

    返回可用索引 dict；完全没有索引时返回 None（推送不附码库行，不阻塞）。
    """
    index = load_code_index()
    if not force and index_is_fresh(index):
        log(f"码库索引有效：{index.get('count')} 条码，built_at={index.get('built_at')}")
        return index
    if index is None:
        log("code_index.json 不存在，开始构建码库索引…")
    elif force:
        log("指定 --rebuild-index，强制重建码库索引…")
    else:
        log(f"码库索引已过期（built_at={index.get('built_at')}），重建…")
    try:
        return build_code_index()
    except Exception as err:  # noqa: BLE001 重建失败用旧索引继续跑
        log(f"码库索引构建失败：{err}")
        if index is not None:
            log("使用旧码库索引继续运行")
            return index
        log("无可用码库索引，推送不附码库行")
        return None


def lookup_code_index(index, code):
    """在索引中查码（大小写不敏感）。命中返回 entry dict，未收录返回 None。"""
    if not index or not isinstance(index.get("codes"), dict) or not code:
        return None
    return index["codes"].get(str(code).strip().lower())


def format_index_line(entry):
    """码库验证行：entry 为 None 表示未收录。"""
    if entry:
        return f"码库: ✅ 已收录 ({entry.get('title') or '-'})"
    return "码库: ➖ 未收录"


def verify_hits_against_index(hits, index):
    """extract_codes() 结果过一遍码库比对（原地），每码附 verified/index_entry。"""
    for hit in hits:
        entry = lookup_code_index(index, hit.get("code"))
        hit["verified"] = entry is not None
        hit["index_entry"] = entry
    return hits


# ---------------------------------------------------------------- bfportal.gg（v2 逻辑原样保留）

def fetch_latest_experiences():
    """拉取最新体验列表，只保留 core.ExperiencePage 条目。

    注意：必须显式 order=-id，否则返回顺序不是按新的。
    """
    query = urllib.parse.urlencode({"order": "-id", "limit": LIST_LIMIT})
    payload = http_request(f"{API_BASE}/experiences/?{query}")
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("列表接口响应格式异常")
    items = []
    for it in payload["items"]:
        if not isinstance(it, dict) or not isinstance(it.get("id"), int):
            continue
        if (it.get("meta") or {}).get("type") != EXPERIENCE_TYPE:
            continue
        items.append(it)
    return items


def fetch_experience_detail(exp_id, user_agent=USER_AGENT):
    detail = http_request(f"{API_BASE}/experiences/{exp_id}/", user_agent=user_agent)
    if not isinstance(detail, dict) or not detail.get("id"):
        raise ValueError(f"详情接口响应格式异常（id={exp_id}）")
    return detail


def clean_code(value):
    """规范化体验码：API 可能返回 null 或字符串 'None'，一律视为无码。"""
    if value is None:
        return ""
    code = str(value).strip()
    if code.lower() == "none":
        return ""
    return code


def should_push(detail):
    """过滤规则：无码跳过；broken 跳过；xp_farm/bugged 照常推送（消息里标注）。"""
    if not clean_code(detail.get("code")):
        return False
    if detail.get("broken"):
        return False
    return True


def clean_markdown(text, limit=DESC_LIMIT):
    """去掉 markdown 符号，压成单行，截断到 limit 字符。"""
    if not text:
        return ""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # [text](url) -> text
    text = re.sub(r"[*_`#>~\\]+", " ", text)
    text = " ".join(text.split())
    return text[:limit]


def build_feishu_text(detail):
    code = clean_code(detail.get("code"))
    lines = [
        f"🎯 新 Portal 体验: {detail.get('title') or '-'}",
        f"码: {code}",
    ]
    if detail.get("xp_farm"):
        lines.append("🔥 刷枪服务器")
    players = detail.get("no_players") or 0
    bots = detail.get("no_bots") or 0
    lines.append(f"玩家/Bot: {players}/{bots}")
    owner = (detail.get("owner") or {}).get("username") or "-"
    lines.append(f"作者: {owner}")
    published = format_iso_date((detail.get("meta") or {}).get("first_published_at"))
    if published:
        lines.append(f"发布: {published}")
    desc = clean_markdown(detail.get("description"))
    if desc:
        lines.append(f"说明: {desc}")
    meta = detail.get("meta") or {}
    url = meta.get("html_url") or f"https://bfportal.gg/experiences/{detail.get('id')}/"
    lines.append(url)
    return "\n".join(lines)


# ---------------------------------------------------------------- YouTube（yt-dlp）

def _run_yt_dlp(args):
    """调 yt-dlp 子进程，返回 stdout 文本。失败抛 RuntimeError（由上层记日志跳过）。"""
    cmd = ["yt-dlp"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=YT_DLP_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("yt-dlp 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"yt-dlp 超时（{YT_DLP_TIMEOUT}s）")
    return proc.stdout.decode("utf-8", "replace") if proc.stdout else ""


def _clean_yt_lines(output):
    """yt-dlp 输出可能混入 WARNING/ERROR 行，解析前先过滤。"""
    return [
        line for line in output.splitlines()
        if line.strip() and not line.strip().startswith(("WARNING", "ERROR"))
    ]


def yt_search(keyword):
    """ytsearchN 搜索，返回 [{"id","title","channel","views"}]。"""
    fmt = f"%(id)s{YT_DELIM}%(title)s{YT_DELIM}%(channel)s{YT_DELIM}%(view_count)s"
    output = _run_yt_dlp([
        "--flat-playlist", "--print", fmt, f"ytsearch{YT_SEARCH_SIZE}:{keyword}",
    ])
    entries = []
    for line in _clean_yt_lines(output):
        parts = line.split(YT_DELIM)
        if len(parts) != 4:
            continue
        vid, title, channel, views_raw = (p.strip() for p in parts)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{8,16}", vid):
            continue
        entries.append({
            "id": vid,
            "title": title,
            "channel": channel,
            "views": int(views_raw) if views_raw.isdigit() else 0,
        })
    return entries


def yt_fetch_description(video_id):
    """抓单个视频标题+描述+发布日期，返回 (title, description, upload_date)。

    upload_date 为 YYYYMMDD 串（不可用时为 None）；与标题/描述共用同一次
    yt-dlp --print 调用，不额外多跑。失败抛 RuntimeError。
    """
    fmt = f"%(title)s{YT_DELIM}%(description)s{YT_DELIM}%(upload_date)s"
    output = _run_yt_dlp([
        "--skip-download", "--print", fmt, f"https://www.youtube.com/watch?v={video_id}",
    ])
    text = "\n".join(_clean_yt_lines(output))
    if YT_DELIM not in text:
        raise RuntimeError("yt-dlp 输出格式异常（无分隔符，视频可能不可用）")
    title, _, rest = text.partition(YT_DELIM)
    desc, sep, upload = rest.rpartition(YT_DELIM)
    if not sep:
        raise RuntimeError("yt-dlp 输出格式异常（分隔符数量不足）")
    title = title.strip()
    desc = desc.strip()
    upload = upload.strip()
    return title, "" if desc == "NA" else desc, None if upload == "NA" else upload


def build_youtube_message(hit, video, feedback=None, published=None):
    """feedback: verify_code_feedback 的返回五元组（None 时不带社区反馈行）；
    published: YYYY-MM-DD（None 时不带发布行）；hit 带 index_entry 键时附码库行
    （全部缺省即 v3 五行格式）。
    """
    lines = [
        f"📺 YouTube 新码: {hit['code']}",
        f"视频: {video['title']}",
        f"频道: {video['channel']}",
    ]
    if published:
        lines.append(f"发布: {published}")
    lines.append(f"说明: {hit['snippet']}")
    if "index_entry" in hit:
        lines.append(format_index_line(hit.get("index_entry")))
    if feedback is not None:
        lines.append(format_feedback_line(*feedback[:4]))
    lines.append(f"https://www.youtube.com/watch?v={video['id']}")
    return "\n".join(lines)


def run_youtube_round(yt_state, verify_budget=None, code_index=None):
    """一轮 YouTube 监控：轮询关键词搜索，新视频提码推送，按 video id 去重。

    verify_budget: {"remaining": N} 本轮评论验证预算（None 表示不验证，
    即 --no-verify）；验证结果附在推送消息的"社区反馈"行。
    code_index: 已知码库索引（None 时不附码库行）；候选码过一遍比对，
    每码附 verified=True/False。
    """
    idx = int(yt_state.get("keyword_index", 0))
    keyword = YT_KEYWORDS[idx % len(YT_KEYWORDS)]
    yt_state["keyword_index"] = (idx + 1) % len(YT_KEYWORDS)

    entries = yt_search(keyword)
    if not entries:
        log(f"YouTube 搜索无结果（关键词：{keyword}）")
        return

    seen = list(yt_state.get("seen_videos", []))
    seen_set = set(seen)
    new_entries = [e for e in entries if e["id"] not in seen_set]
    log(f"YouTube 关键词 [{keyword}] 拉到 {len(entries)} 条，新视频 {len(new_entries)} 个")

    pushed = 0
    pushed_codes = set()
    desc_budget = YT_DESC_FETCH_MAX
    for video in new_entries:
        text = video["title"]
        published = None  # 抓了详情的视频才有 upload_date
        if desc_budget > 0:
            desc_budget -= 1
            try:
                title, desc, upload_date = yt_fetch_description(video["id"])
                text = (title or video["title"]) + "\n" + desc
                published = format_upload_date(upload_date) or None
            except Exception as err:  # noqa: BLE001 描述抓取失败退回仅标题提取
                log(f"获取视频描述失败 vid={video['id']}，仅从标题提取：{err}")
        hits = extract_codes(text)
        if code_index is not None and hits:
            verify_hits_against_index(hits, code_index)
            for hit in hits:
                if hit["verified"]:
                    log(f"码库命中：{hit['code']} -> {hit['index_entry'].get('title')}")
                else:
                    log(f"码库未收录：{hit['code']}")
        for hit in hits:
            code_key = hit["code"].lower()
            if code_key in pushed_codes:
                continue
            if pushed >= PUSH_CAP_PER_ROUND:
                log(f"YouTube 本轮达到推送上限 {PUSH_CAP_PER_ROUND}，其余跳过")
                break
            print(f"📺 YouTube 新码：{hit['code']} <- {video['title']}", flush=True)
            feedback = None
            if verify_budget is not None:
                if verify_budget["remaining"] > 0:
                    verify_budget["remaining"] -= 1
                    feedback = verify_code_feedback("youtube", video["id"], hit["code"])
                else:
                    log(f"YouTube 本轮评论验证预算用尽，{hit['code']} 跳过验证")
            ok, info = send_feishu(
                build_youtube_message(hit, video, feedback=feedback, published=published)
            )
            log(f"飞书通知：{hit['code']} -> {info}")
            pushed_codes.add(code_key)
            pushed += 1
        seen.append(video["id"])
        seen_set.add(video["id"])

    yt_state["seen_videos"] = seen[-YT_SEEN_LIMIT:]
    if new_entries:
        log(f"YouTube 本轮完成：推送 {pushed} 条码")


# ---------------------------------------------------------------- Reddit（Arctic Shift 镜像）

def arctic_search(kind, sub):
    """Arctic Shift 帖子/评论搜索。kind: posts|comments。comments 不支持 query 参数。"""
    query = urllib.parse.urlencode({"subreddit": sub, "limit": REDDIT_LIMIT, "sort": "desc"})
    payload = http_request(f"{ARCTIC_BASE}/{kind}/search?{query}")
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError(f"Arctic Shift 响应格式异常（{kind}/{sub}）")
    return payload["data"]


def build_reddit_message(hit, item, sub, kind, feedback=None, published=None):
    """feedback: verify_code_feedback 的返回五元组（None 时不带社区反馈行）；
    published: 'YYYY-MM-DD HH:MM UTC'（None 时不带发布行）；hit 带 index_entry
    键时附码库行（全部缺省即 v3 五行格式）。
    """
    lines = [
        f"💬 Reddit 新码: {hit['code']}",
        f"来源: r/{sub} ({'帖子' if kind == 'posts' else '评论'})",
    ]
    if kind == "posts" and item.get("title"):
        lines.append(f"标题: {item['title']}")
    if published:
        lines.append(f"发布: {published}")
    lines.append(f"说明: {hit['snippet']}")
    if "index_entry" in hit:
        lines.append(format_index_line(hit.get("index_entry")))
    if feedback is not None:
        lines.append(format_feedback_line(*feedback[:4]))
    lines.append(f"https://www.reddit.com{item.get('permalink', '')}")
    return "\n".join(lines)


def run_reddit_round(rd_state, verify_budget=None, code_index=None):
    """一轮 Reddit 监控：按数据流 created_utc 水位线取增量，提码推送。

    数据流 = 版块 × (帖子|评论)，共 6 条。首次接入回溯 1 小时建基线。
    verify_budget: {"remaining": N} 本轮评论验证预算（None 表示不验证）；
    帖子里的码按帖子 id 拉评论，评论里的码按其父帖（link_id）拉评论。
    code_index: 已知码库索引（None 时不附码库行）。
    """
    now = time.time()
    watermarks = rd_state.setdefault("watermarks", {})
    seen = list(rd_state.setdefault("seen_posts", []))
    seen_set = set(seen)
    total_processed = 0
    pushed = 0
    pushed_codes = set()

    for sub in REDDIT_SUBS:
        for kind in ("posts", "comments"):
            stream = f"{sub}:{kind}"
            wm = watermarks.get(stream)
            first_run = wm is None
            if first_run:
                wm = now - REDDIT_BACKFILL_SECONDS
            try:
                items = arctic_search(kind, sub)
            except Exception as err:  # noqa: BLE001 单数据流失败不影响其他流
                log(f"Reddit 数据流 {stream} 拉取失败，跳过：{err}")
                continue

            fresh = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                created = it.get("created_utc")
                item_id = str(it.get("id") or "")
                marked = f"{kind}:{item_id}"
                if not item_id or not isinstance(created, (int, float)):
                    continue
                if created >= wm and marked not in seen_set:
                    fresh.append(it)
            fresh.sort(key=lambda x: x["created_utc"])

            max_created = max((it.get("created_utc") or 0) for it in items) if items else wm
            watermarks[stream] = max(wm, max_created)

            for it in fresh:
                total_processed += 1
                marked = f"{kind}:{it['id']}"
                seen.append(marked)
                seen_set.add(marked)
                if kind == "posts":
                    text = f"{it.get('title') or ''}\n{it.get('selftext') or ''}"
                else:
                    text = it.get("body") or ""
                hits = extract_codes(text)
                if code_index is not None and hits:
                    verify_hits_against_index(hits, code_index)
                    for hit in hits:
                        if hit["verified"]:
                            log(f"码库命中：{hit['code']} -> {hit['index_entry'].get('title')}")
                        else:
                            log(f"码库未收录：{hit['code']}")
                published = format_created_utc(it.get("created_utc")) or None
                for hit in hits:
                    code_key = hit["code"].lower()
                    if code_key in pushed_codes:
                        continue
                    if pushed >= PUSH_CAP_PER_ROUND:
                        log(f"Reddit 本轮达到推送上限 {PUSH_CAP_PER_ROUND}，其余跳过")
                        break
                    print(f"💬 Reddit 新码：{hit['code']} <- r/{sub} ({kind})", flush=True)
                    feedback = None
                    if verify_budget is not None:
                        if kind == "posts":
                            verify_target = str(it.get("id") or "")
                        else:
                            verify_target = str(it.get("link_id") or "")
                        if verify_budget["remaining"] > 0 and verify_target:
                            verify_budget["remaining"] -= 1
                            feedback = verify_code_feedback("reddit", verify_target, hit["code"])
                        elif not verify_target:
                            log(f"Reddit 码 {hit['code']} 无法定位父帖，跳过评论验证")
                        else:
                            log(f"Reddit 本轮评论验证预算用尽，{hit['code']} 跳过验证")
                    ok, info = send_feishu(
                        build_reddit_message(hit, it, sub, kind, feedback=feedback, published=published)
                    )
                    log(f"飞书通知：{hit['code']} -> {info}")
                    pushed_codes.add(code_key)
                    pushed += 1

            if first_run:
                log(f"Reddit 数据流 {stream} 首次接入：回溯 1 小时建基线，处理 {len(fresh)} 条")

    rd_state["seen_posts"] = seen[-REDDIT_SEEN_LIMIT:]
    log(f"Reddit 本轮完成：处理 {total_processed} 条（帖子+评论），推送 {pushed} 条码")


# ---------------------------------------------------------------- 状态

def default_state():
    return {
        "version": 3,
        "bfportal": {},
        "youtube": {"keyword_index": 0, "seen_videos": []},
        "reddit": {"watermarks": {}, "seen_posts": []},
    }


def load_state():
    """读取 state.json。v3 格式；兼容 v2（max_seen_id 迁入 bfportal 段）。

    缺失/损坏按首次运行处理。
    """
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError) as err:
            log(f"state.json 读取失败，重建状态：{err}")
            return default_state()
        if not isinstance(state, dict):
            log("state.json 内容异常（非对象），按首次运行处理")
            return default_state()
        if state.get("version") == 3 and isinstance(state.get("bfportal"), dict):
            merged = default_state()
            for key in ("bfportal", "youtube", "reddit"):
                if isinstance(state.get(key), dict):
                    merged[key].update(state[key])
            return merged
        if isinstance(state.get("max_seen_id"), int):
            log("检测到 v2 状态，升级为 v3（保留 bfportal 基线）")
            merged = default_state()
            merged["bfportal"]["max_seen_id"] = state["max_seen_id"]
            if state.get("initialized_at"):
                merged["bfportal"]["initialized_at"] = state["initialized_at"]
            return merged
        log("state.json 为旧版本状态（无 max_seen_id），按首次运行处理")
    return default_state()


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError as err:
        log(f"保存 state.json 失败：{err}")


# ---------------------------------------------------------------- 轮询

def process_new_item(item):
    """请求单个新条目的详情，过滤后推送。"""
    try:
        detail = fetch_experience_detail(item["id"])
    except Exception as err:  # noqa: BLE001 单条失败不阻塞其余条目
        log(f"获取详情失败 id={item['id']}（{item.get('title')}），跳过：{err}")
        return
    if not should_push(detail):
        reason = "无有效码" if not clean_code(detail.get("code")) else "已标记 broken"
        log(f"跳过 id={item['id']}（{detail.get('title')}）：{reason}")
        return
    code = clean_code(detail.get("code"))
    print(f"🎯 新体验：{detail.get('title')} 码={code}", flush=True)
    ok, info = send_feishu(build_feishu_text(detail))
    log(f"飞书通知：{code} -> {info}")


def run_bfportal_round(bp_state, backfill=0):
    """一轮 bfportal.gg 轮询（v2 逻辑，状态收进 bfportal 段）。"""
    items = fetch_latest_experiences()
    if not items:
        log("列表中无 ExperiencePage 条目，本轮跳过")
        return
    max_id = max(it["id"] for it in items)

    if "max_seen_id" not in bp_state:
        # 首次运行：以当前最大 id 为基线，不推送历史（除非显式 --backfill）
        pushed = 0
        if backfill > 0:
            targets = sorted(items, key=lambda x: x["id"], reverse=True)[:backfill]
            for item in sorted(targets, key=lambda x: x["id"]):
                process_new_item(item)
                pushed += 1
        bp_state["max_seen_id"] = max_id
        bp_state["initialized_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        suffix = f"，回溯推送 {pushed} 条" if backfill > 0 else ""
        log(f"基线已建立, max_seen_id={max_id}{suffix}")
        return

    new_items = [it for it in items if it["id"] > bp_state["max_seen_id"]]
    if not new_items:
        log("无新体验")
        bp_state["max_seen_id"] = max(bp_state["max_seen_id"], max_id)
        return

    for item in sorted(new_items, key=lambda x: x["id"]):  # 按发布顺序推
        process_new_item(item)
        bp_state["max_seen_id"] = max(bp_state["max_seen_id"], item["id"])
    log(f"本轮处理新体验 {len(new_items)} 条")


# ---------------------------------------------------------------- 通知（v1 原样保留）

def _parse_feishu_target(target):
    """解析 FEISHU_TARGET，返回 (lark-cli 参数名, 目标 id)。

    user: 前缀 -> --user-id（P2P 直发）；chat: 前缀或无前缀 -> --chat-id（群）。
    """
    target = target.strip()
    if target.startswith("user:"):
        return "--user-id", target[len("user:"):].strip()
    if target.startswith("chat:"):
        return "--chat-id", target[len("chat:"):].strip()
    return "--chat-id", target


def _send_feishu_webhook(text, webhook):
    """走群机器人 webhook（含可选加签），原有逻辑。"""
    payload = {"msg_type": "text", "content": {"text": text}}
    secret = os.environ.get("FEISHU_SECRET", "").strip()
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        payload["timestamp"] = timestamp
        payload["sign"] = base64.b64encode(digest).decode("utf-8")
    try:
        resp = http_request(webhook, payload=payload)
        if isinstance(resp, dict) and resp.get("code", 0) == 0:
            return True, "ok"
        return False, f"飞书返回异常：{str(resp)[:200]}"
    except Exception as err:  # noqa: BLE001
        return False, f"飞书通知失败：{err}"


def _send_feishu_lark_cli(text):
    """通过本机已认证的 lark-cli 子进程发消息。"""
    target = os.environ.get("FEISHU_TARGET", "").strip() or DEFAULT_FEISHU_TARGET
    flag, target_id = _parse_feishu_target(target)
    if not target_id:
        return False, f"FEISHU_TARGET 解析后目标为空：{target!r}"
    cmd = [
        "lark-cli", "im", "+messages-send",
        flag, target_id,
        "--text", text,
        "--as", "bot",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=LARK_CLI_TIMEOUT)
    except FileNotFoundError:
        return False, "lark-cli 未安装或不在 PATH 中"
    except subprocess.TimeoutExpired:
        return False, f"lark-cli 执行超时（{LARK_CLI_TIMEOUT}s）"
    except Exception as err:  # noqa: BLE001
        return False, f"lark-cli 执行失败：{err}"
    stdout = proc.stdout.decode("utf-8", "replace").strip() if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8", "replace").strip() if proc.stderr else ""
    try:
        result = json.loads(stdout) if stdout else {}
    except ValueError:
        return False, f"lark-cli 输出无法解析为 JSON：{(stdout or stderr)[:200]}"
    if isinstance(result, dict) and result.get("ok") is True:
        return True, "ok"
    detail = result.get("error") if isinstance(result, dict) else None
    return False, f"lark-cli 发送失败：{str(detail or stdout or stderr or proc.returncode)[:200]}"


def send_feishu(text):
    """发送飞书通知。设置了 FEISHU_WEBHOOK 则优先走 webhook，否则走 lark-cli。"""
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if webhook:
        return _send_feishu_webhook(text, webhook)
    return _send_feishu_lark_cli(text)


# ---------------------------------------------------------------- 入口

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="BF6 Portal 体验监控器 v5（数据源：bfportal.gg + YouTube + Reddit/Arctic Shift；"
                    "含评论反馈验证 + 已知码库交叉验证 + 发布日期）"
    )
    parser.add_argument("--once", action="store_true", help="只执行一轮轮询后退出")
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL,
        help=f"轮询间隔秒数，默认 {DEFAULT_INTERVAL}（最小 15）",
    )
    parser.add_argument(
        "--backfill", type=int, default=0,
        help="首次运行时推送最近 N 条 bfportal 体验（演示用，默认 0 不推送历史）",
    )
    parser.add_argument(
        "--sources", default=",".join(ALL_SOURCES),
        help="要运行的数据源，逗号分隔：bfportal,youtube,reddit（默认全跑）",
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="跳过评论反馈验证，直接推码（调试用；YouTube/Reddit 消息不带社区反馈行）",
    )
    parser.add_argument(
        "--rebuild-index", action="store_true",
        help="强制全量重建码库索引（code_index.json）后退出，不跑监控",
    )
    args = parser.parse_args(argv)

    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        parser.error(f"未知数据源：{','.join(unknown)}（可选：{','.join(ALL_SOURCES)}）")
    if not sources:
        parser.error("未指定任何数据源")

    interval = max(15, args.interval)
    backfill = max(0, args.backfill)

    if args.rebuild_index:
        # 维护命令：强制全量重建码库索引后退出（约 9 分钟）
        index = refresh_index_if_needed(force=True)
        sys.exit(0 if index is not None else 1)

    state = load_state()
    code_index = refresh_index_if_needed()
    last_rebuild_try = time.time()
    if os.environ.get("FEISHU_WEBHOOK", "").strip():
        notify_note = "webhook 已配置（优先于 lark-cli）"
    else:
        target = os.environ.get("FEISHU_TARGET", "").strip() or DEFAULT_FEISHU_TARGET
        notify_note = f"lark-cli 直发（目标 {target}）"
    verify_note = "关闭（--no-verify）" if args.no_verify else f"开启（每轮最多 {VERIFY_CAP_PER_ROUND} 个码）"
    index_note = f"{code_index.get('count')} 条码" if code_index else "不可用（推送不带码库行）"
    log(f"监控启动：数据源={','.join(sources)} 间隔={interval}s 评论验证 {verify_note} "
        f"码库索引 {index_note} 飞书通知 {notify_note}")

    try:
        while True:
            started = time.time()
            # 常驻运行期间索引过期自动重建（失败最多每小时重试一次，用旧索引继续跑）
            if not index_is_fresh(code_index) and time.time() - last_rebuild_try >= 3600:
                last_rebuild_try = time.time()
                code_index = refresh_index_if_needed()
            # 评论验证预算按轮重置；--no-verify 时为 None（各源保持 v3 行为）
            verify_budget = None if args.no_verify else {"remaining": VERIFY_CAP_PER_ROUND}
            if "bfportal" in sources:
                try:
                    run_bfportal_round(state["bfportal"], backfill=backfill)
                except Exception as err:  # noqa: BLE001 单源失败不影响其他源
                    log(f"bfportal 源本轮失败（不影响其他源）：{err!r}")
                backfill = 0  # 回溯仅首次运行生效
                save_state(state)
            if "youtube" in sources:
                try:
                    run_youtube_round(state["youtube"], verify_budget=verify_budget, code_index=code_index)
                except Exception as err:  # noqa: BLE001
                    log(f"YouTube 源本轮失败（不影响其他源）：{err!r}")
                save_state(state)
            if "reddit" in sources:
                try:
                    run_reddit_round(state["reddit"], verify_budget=verify_budget, code_index=code_index)
                except Exception as err:  # noqa: BLE001
                    log(f"Reddit 源本轮失败（不影响其他源）：{err!r}")
                save_state(state)
            if args.once:
                break
            time.sleep(max(5.0, interval - (time.time() - started)))
    except KeyboardInterrupt:
        save_state(state)
        log("已手动中断，状态已保存。")


if __name__ == "__main__":
    main()
