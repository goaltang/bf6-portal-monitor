#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可用码账本（v6）单元测试：清单消息格式 + 容量淘汰 + state 兼容
（纯标准库，无网络，不发飞书）。
"""
import json
import os
import sys
import tempfile

import bf6_portal_monitor as m
from bf6_portal_monitor import (
    LEDGER_LIMIT,
    LEDGER_MSG_LIMIT,
    RATING_DEAD,
    RATING_UNKNOWN,
    RATING_VALID,
    book_code,
    build_ledger_message,
    format_feedback_summary,
)

FAILURES = 0


def check(name, cond, detail=""):
    global FAILURES
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES += 1
    print(f"[{status}] {name}" + (f"（{detail}）" if detail and not cond else ""))


def make_entry(code, source, first_found, **extra):
    """直接构造账本条目（不经 book_code，时间戳可控）。"""
    entry = {
        "code": code,
        "source": source,
        "title": None,
        "link": None,
        "published": None,
        "feedback": None,
        "index_hit": False,
        "first_found": first_found,
        "last_seen": first_found,
    }
    entry.update(extra)
    return entry


def run():
    # ---------- a. 空 ledger 不崩溃 ----------
    print("== a. build_ledger_message 空 ledger ==")
    msg = build_ledger_message({})
    check("空账本正常返回（含 共 0 条）", isinstance(msg, str) and "共 0 条" in msg, repr(msg))
    check("空账本 + 空 new_keys 也正常", isinstance(build_ledger_message({}, []), str))

    # ---------- b. 3 条码 1 新 2 旧 ----------
    print("\n== b. 3 条码 1 新 2 旧 ==")
    ledger = {
        "abc12": make_entry("ABC12", "bfportal", "2026-08-05T01:00:00+00:00",
                            title="旧码一", published="2026-08-05", index_hit=True),
        "zz999": make_entry("ZZ999", "reddit", "2026-08-06T01:00:00+00:00",
                            feedback="❌(0+/2-)"),
        "zd7hy": make_entry("ZD7HY", "youtube", "2026-08-07T01:00:00+00:00",
                            title="新码标题", published="2026-08-07",
                            feedback="✅(5+/0-)", index_hit=True,
                            link="https://www.youtube.com/watch?v=TEST0001"),
    }
    msg = build_ledger_message(ledger, ["zd7hy"])
    print(msg)
    lines = msg.splitlines()
    check("首行含 共 3 条", "共 3 条" in lines[0], lines[0])
    new_idx = next((i for i, l in enumerate(lines) if "ZD7HY" in l), -1)
    check("新码行首有 🆕", new_idx > 0 and lines[new_idx].startswith("🆕 ZD7HY"),
          lines[new_idx] if new_idx > 0 else "未找到 ZD7HY 行")
    first_entry_idx = next(i for i, l in enumerate(lines) if i > 0 and l.strip())
    check("新码排在最前（首行后的第一个条目）", new_idx == first_entry_idx,
          f"ZD7HY 在第 {new_idx} 行，第一个条目在第 {first_entry_idx} 行")
    idx_zz = next(i for i, l in enumerate(lines) if "ZZ999" in l)
    idx_abc = next(i for i, l in enumerate(lines) if "ABC12" in l)
    check("旧码按 first_found 从新到旧（ZZ999 先于 ABC12）", idx_zz < idx_abc,
          f"ZZ999 第 {idx_zz} 行, ABC12 第 {idx_abc} 行")
    check("旧码行无 🆕", not lines[idx_zz].startswith("🆕") and not lines[idx_abc].startswith("🆕"))
    check("新码行含反馈摘要与码库命中",
          "社区反馈 ✅(5+/0-)" in lines[new_idx] and "码库 ✅已收录" in lines[new_idx],
          lines[new_idx])
    check("标题行全角空格缩进", "　　标题：新码标题" in msg)
    check("链接行全角空格缩进", "　　https://www.youtube.com/watch?v=TEST0001" in msg)
    check("未命中码不带码库段", "码库" not in lines[idx_zz], lines[idx_zz])

    # 同轮多个新码按发现顺序（与 first_found 无关）
    ledger2 = {
        "bb222": make_entry("BB222", "youtube", "2026-08-07T01:00:00+00:00"),
        "aa111": make_entry("AA111", "youtube", "2026-08-07T03:00:00+00:00"),
        "cc333": make_entry("CC333", "reddit", "2026-08-06T01:00:00+00:00"),
    }
    msg2 = build_ledger_message(ledger2, ["aa111", "bb222"])
    lines2 = msg2.splitlines()
    idx_aa = next(i for i, l in enumerate(lines2) if "AA111" in l)
    idx_bb = next(i for i, l in enumerate(lines2) if "BB222" in l)
    idx_cc = next(i for i, l in enumerate(lines2) if "CC333" in l)
    check("多个新码按发现顺序在前（AA111 虽 first_found 更晚仍排第一）",
          idx_aa < idx_bb < idx_cc, f"行号 {idx_aa}/{idx_bb}/{idx_cc}")

    # ---------- 反馈摘要渲染 ----------
    print("\n== format_feedback_summary ==")
    check("正常评级摘要", format_feedback_summary(RATING_VALID, 5, 0, 12) == "✅(5+/0-)")
    check("失效评级摘要", format_feedback_summary(RATING_DEAD, 0, 2, 8) == "❌(0+/2-)")
    check("样本不足", format_feedback_summary(RATING_UNKNOWN, 1, 0, 2) == "⚠️(样本不足)")
    check("无评论数据", format_feedback_summary(RATING_UNKNOWN, 0, 0, -1) == "⚠️(无评论数据)")

    # ---------- c. ledger 超 30 条淘汰最旧 ----------
    print("\n== c. ledger 容量上限 ==")
    big = {}
    results = [book_code(big, f"CODE{i:02d}", "youtube", title=f"码 {i}")
               for i in range(LEDGER_LIMIT + 5)]
    check("首次入账均返回 True", all(results))
    check(f"超限后只保留最新 {LEDGER_LIMIT} 条", len(big) == LEDGER_LIMIT, f"len={len(big)}")
    check("最旧 5 条被淘汰", all(f"code{i:02d}" not in big for i in range(5)))
    check("较新条目保留", all(f"code{i:02d}" in big for i in range(5, LEDGER_LIMIT + 5)))
    msg_big = build_ledger_message(big)
    blocks = msg_big.split("\n\n")
    check(f"清单消息恰好展示 {LEDGER_LIMIT} 条码",
          f"共 {LEDGER_LIMIT} 条" in blocks[0] and len(blocks) == LEDGER_LIMIT + 1,
          f"块数 {len(blocks)}")
    fb = (RATING_VALID, 3, 0, 12, [])
    again = book_code(big, "CODE10", "youtube", feedback=fb)
    check("已有码重复入账返回 False（不重复计新）", again is False and len(big) == LEDGER_LIMIT)
    check("重复入账刷新 feedback/last_seen",
          big["code10"]["feedback"] == "✅(3+/0-)"
          and big["code10"]["last_seen"] >= big["code10"]["first_found"])

    # ---------- d. load_state 兼容无 ledger 段的旧 v3 state ----------
    print("\n== d. load_state ledger 段兼容 ==")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "state.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 3,
                "bfportal": {"max_seen_id": 1273},
                "youtube": {"keyword_index": 1, "seen_videos": ["vid1"]},
                "reddit": {"watermarks": {}, "seen_posts": []},
            }, f, ensure_ascii=False)
        orig = m.STATE_FILE
        m.STATE_FILE = path
        try:
            state = m.load_state()
        finally:
            m.STATE_FILE = orig
        check("旧 v3 state 无 ledger 段自动补空 dict", state.get("ledger") == {})
        check("其余段不受影响", state["bfportal"].get("max_seen_id") == 1273
              and state["youtube"].get("keyword_index") == 1)

        sample = {"zd7hy": make_entry("ZD7HY", "youtube", "2026-08-07T01:00:00+00:00")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 3,
                "bfportal": {"max_seen_id": 1273},
                "youtube": {"keyword_index": 0, "seen_videos": []},
                "reddit": {"watermarks": {}, "seen_posts": []},
                "ledger": sample,
            }, f, ensure_ascii=False)
        m.STATE_FILE = path
        try:
            state2 = m.load_state()
        finally:
            m.STATE_FILE = orig
        check("已有 ledger 段原样保留", state2.get("ledger") == sample)

    # ---------- e. 消息长度 < 3000 ----------
    print("\n== e. 消息长度上限 ==")
    long_ledger = {}
    long_title = "很长的标题文本内容 " * 10
    for i in range(LEDGER_LIMIT):
        book_code(long_ledger, f"LG{i:03d}", "youtube", title=long_title,
                  link="https://www.youtube.com/watch?v=" + "x" * 40,
                  published="2026-08-07", feedback=(RATING_VALID, 9, 0, 15, []),
                  index_hit=True)
    msg_long = build_ledger_message(long_ledger, ["lg029"])
    check(f"满容量长条目消息长度 {len(msg_long)} < {LEDGER_MSG_LIMIT}",
          len(msg_long) < LEDGER_MSG_LIMIT)
    title_lines = [l for l in msg_long.splitlines() if l.startswith("　　标题：")]
    check("展示的标题均截断 60 字符", bool(title_lines)
          and all(len(l) - len("　　标题：") <= 60 for l in title_lines),
          f"标题行 {len(title_lines)} 条")
    check("超长消息触发裁剪（30 条未全部展示，从最旧码裁起）",
          len(title_lines) < LEDGER_LIMIT, f"展示 {len(title_lines)}/{LEDGER_LIMIT} 条")
    check("裁剪后本轮新码仍在清单里", "LG029" in msg_long)

    print()
    if FAILURES:
        print(f"共 {FAILURES} 个用例失败")
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    run()
