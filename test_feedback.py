#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评论反馈验证（v4）单元测试：评级逻辑 + 消息格式（纯标准库，无网络）。

覆盖任务规格：纯正面 / 纯负面 / 混杂三组假评论的评级，另加样本不足、
正负混杂单条评论（负面信号更强）、关键词整词匹配边界等用例。
"""
import sys

from bf6_portal_monitor import (
    RATING_DEAD,
    RATING_UNKNOWN,
    RATING_VALID,
    build_reddit_message,
    build_youtube_message,
    classify_comment,
    format_feedback_line,
    rate_comments,
)


def comments(*pairs):
    """pairs: (text, score) -> [{"text","score"}]"""
    return [{"text": t, "score": s} for t, s in pairs]


# (用例名, 评论列表, 期望(rating, pos, neg, count))
CASES = [
    # ---------- 任务要求的三组核心场景 ----------
    ("纯正面（>=2 正面且 0 负面 -> ✅ 可能有效）",
     comments(
         ("Great video it worked for me!!", 12),
         ("still works, got xp so fast", 5),
         ("confirmed valid code, thanks man", 3),
         ("amazing lobby, leveling is insane", 1),
     ),
     (RATING_VALID, 4, 0, 4)),

    ("纯负面（负面 >=1 且 负面 >= 正面 -> ❌ 可能失效）",
     comments(
         ("doesn't work anymore, got patched", 8),
         ("dead code, server was removed", 4),
         ("they nerfed it, stopped working", 2),
         ("this one is gone now", 0),
     ),
     (RATING_DEAD, 0, 4, 4)),

    ("混杂（正面 3 负面 2，正负都有但不满足任一确定条件 -> ⚠️ 不确定）",
     comments(
         ("worked for me earlier", 6),
         ("patched now, doesnt work", 9),
         ("still works if you join quick", 2),
         ("error when joining, removed?", 0),
         ("thanks, legit", 1),
     ),
     (RATING_UNKNOWN, 3, 2, 5)),

    # ---------- 边界与规则细节 ----------
    ("样本不足（<3 条直接 ⚠️，即使全正面）",
     comments(("worked perfectly", 5), ("great thanks", 1)),
     (RATING_UNKNOWN, 2, 0, 2)),

    ("无评论（0 条 -> ⚠️）",
     comments(),
     (RATING_UNKNOWN, 0, 0, 0)),

    ("单条评论同时命中正负 -> 该条取负面（最强信号）；整体 正2负1 -> ⚠️",
     comments(
         ("works great but it got patched", 10),
         ("works", 1),
         ("works", 1),
     ),
     (RATING_UNKNOWN, 2, 1, 3)),

    ("负面主导（正负同时有且 负 >= 正 -> ❌）",
     comments(
         ("works great but it got patched", 10),
         ("dead now", 3),
         ("works", 1),
     ),
     (RATING_DEAD, 1, 2, 3)),

    ("只有 1 条负面、其余无信号 -> ❌（负面 1 >= 正面 0）",
     comments(
         ("code is invalid", 3),
         ("is this portal conquest or assault?", 0),
         ("what level do I need?", 0),
     ),
     (RATING_DEAD, 0, 1, 3)),

    ("大量评论但全无信号 -> ⚠️ 不确定",
     comments(
         ("what map is this?", 1),
         ("join my discord", 0),
         ("first", 0),
         ("nice video quality", 0),
     ),
     (RATING_UNKNOWN, 0, 0, 4)),

    ("弯引号 won’t work 归一化后命中负面",
     comments(
         ("won’t work on xbox", 2),
         ("no longer active", 1),
         ("kicked after 2 minutes", 0),
     ),
     (RATING_DEAD, 0, 3, 3)),
]

# classify_comment 单条评论分类用例
CLASSIFY_CASES = [
    ("works", "pos"),
    ("It WORKED for me", "pos"),
    ("still  working", "pos"),          # 多余空格不影响整词匹配
    ("got XP in this lobby", "pos"),
    ("patched", "neg"),
    ("it doesn't work", "neg"),
    ("it doesnt work anymore", "neg"),
    ("no longer valid", "neg"),          # 同时含负面 no longer 与正面 valid -> 负面赢
    ("is this still up?", None),
    ("", None),
    ("this code is dead to me", "neg"),  # dead 整词命中
    ("deadline giveaway", None),          # dead 在 deadline 中不应命中（整词边界）
    ("breakfast farm guide", None),       # fast 在 breakfast 中不应命中
    ("it's broken :(", "neg"),
]

# 消息格式用例：验证"社区反馈"行位置与措辞
FORMAT_CASES = [
    ("正常评级行", (RATING_VALID, 3, 0, 12), "社区反馈: ✅ 可能有效 (正面3/负面0, 评论12条)"),
    ("失效评级行", (RATING_DEAD, 0, 2, 8), "社区反馈: ❌ 可能失效 (正面0/负面2, 评论8条)"),
    ("样本不足行", (RATING_UNKNOWN, 2, 0, 2), "社区反馈: ⚠️ 不确定 (样本不足, 评论2条)"),
    ("抓取失败行", (RATING_UNKNOWN, 0, 0, -1), "社区反馈: ⚠️ 不确定 (无评论数据)"),
]


def run():
    failures = 0

    print("== rate_comments 评级测试 ==")
    for name, clist, expected in CASES:
        rating, pos, neg, count, top = rate_comments(clist)
        got = (rating, pos, neg, count)
        status = "PASS" if got == expected else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"[{status}] {name}")
        if status == "FAIL":
            print(f"       期望 {expected}，实际 {got}")
        if top:
            for line in top:
                print(f"       top: {line}")

    print("\n== classify_comment 单条评论测试 ==")
    for text, expected in CLASSIFY_CASES:
        got = classify_comment(text)
        status = "PASS" if got == expected else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"[{status}] {text!r} -> {got}（期望 {expected}）")

    print("\n== format_feedback_line 格式测试 ==")
    for name, feedback, expected in FORMAT_CASES:
        got = format_feedback_line(*feedback)
        status = "PASS" if got == expected else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"[{status}] {name}: {got}")

    print("\n== 完整推送消息样例（含社区反馈行） ==")
    fake_hit = {"code": "1Y8CM", "snippet": "//CODE 1Y8CM", "layer": 1}
    fake_video = {"id": "TESTVID123", "title": "NEW BF6 WEAPON XP FARM //CODE 1Y8CM",
                  "channel": "monitor-test", "views": 0}
    feedback_ok = (RATING_VALID, 3, 0, 12, [])
    print(build_youtube_message(fake_hit, fake_video, feedback=feedback_ok))
    msg = build_youtube_message(fake_hit, fake_video, feedback=feedback_ok)
    lines = msg.splitlines()
    assert lines[-2].startswith("社区反馈: "), "社区反馈行应位于链接前一行"
    assert build_youtube_message(fake_hit, fake_video).count("\n") == 4, "无 feedback 时应保持 v3 五行格式"

    fake_item = {"title": "IGLA Challenge any helpful tips",
                 "permalink": "/r/battlefield6/comments/1xxx/test/"}
    feedback_dead = (RATING_DEAD, 0, 2, 8, [])
    print()
    print(build_reddit_message(fake_hit, fake_item, "battlefield6", "posts", feedback=feedback_dead))
    assert build_reddit_message(fake_hit, fake_item, "battlefield6", "posts").count("\n") == 4, \
        "无 feedback 时应保持 v3 五行格式"
    print("消息格式断言通过")

    print()
    if failures:
        print(f"共 {failures} 个用例失败")
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    run()
