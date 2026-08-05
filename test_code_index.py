#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已知码库交叉验证（v5）单元测试：构造假码库 JSON，验证比对逻辑
（收录/未收录/大小写不敏感）、索引存取/过期判断、重建失败降级（纯标准库，
无网络；索引文件走临时路径，不碰真实 code_index.json）。
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import bf6_portal_monitor as m
from bf6_portal_monitor import (
    extract_codes,
    format_index_line,
    index_is_fresh,
    load_code_index,
    lookup_code_index,
    refresh_index_if_needed,
    save_code_index,
    verify_hits_against_index,
)

# ---------------- 假码库（结构同 code_index.json：键为小写码） ----------------

FAKE_CODES = {
    "1zc5t": {"code": "1ZC5T", "title": "030 Portal Lab", "owner": "tnt_bro", "broken": False},
    "116pq": {"code": "116PQ", "title": "BLACKSITE: ASCENDANT | PROGRESSION |",
              "owner": "st_kia", "broken": False},
    "mphd": {"code": "MPHD", "title": "Mirak Contamination", "owner": "miraq", "broken": True},
}

TMP_DIR = tempfile.mkdtemp(prefix="code_index_test_")
TMP_INDEX_FILE = os.path.join(TMP_DIR, "code_index.json")


def make_index(hours_ago=0.0):
    built = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "built_at": built.isoformat(timespec="seconds"),
        "count": len(FAKE_CODES),
        "codes": {k: dict(v) for k, v in FAKE_CODES.items()},
    }


def patch_module(build=None):
    """把 CODE_INDEX_FILE 指到临时路径（可选替换 build_code_index），返回还原函数。"""
    orig_file, orig_build = m.CODE_INDEX_FILE, m.build_code_index
    m.CODE_INDEX_FILE = TMP_INDEX_FILE
    if build is not None:
        m.build_code_index = build

    def restore():
        m.CODE_INDEX_FILE = orig_file
        m.build_code_index = orig_build
        if os.path.exists(TMP_INDEX_FILE):
            os.remove(TMP_INDEX_FILE)

    return restore


FAILURES = 0


def check(name, cond, detail=""):
    global FAILURES
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES += 1
    print(f"[{status}] {name}" + (f"（{detail}）" if detail and not cond else ""))


def run():
    # ---------- lookup_code_index：收录/未收录/大小写 ----------
    print("== lookup_code_index 比对测试 ==")
    index = make_index()
    entry = lookup_code_index(index, "1ZC5T")
    check("收录：原始大小写 1ZC5T 命中", entry is not None and entry["title"] == "030 Portal Lab",
          f"got {entry!r}")
    check("收录：全小写 116pq 命中（键即小写）", lookup_code_index(index, "116pq") is not None)
    check("大小写不敏感：混合大小写 116pQ 命中", lookup_code_index(index, "116pQ") is not None)
    check("大小写不敏感：全大写 MPHD 命中小写键 mphd", lookup_code_index(index, "MPHD") is not None)
    check("展示保留原始大小写", (lookup_code_index(index, "mphd") or {}).get("code") == "MPHD")
    check("未收录：NEW99 返回 None", lookup_code_index(index, "NEW99") is None)
    check("英文单词误报永远不在码库：ENTIRE 返回 None", lookup_code_index(index, "ENTIRE") is None)
    check("空码返回 None", lookup_code_index(index, "") is None)
    check("索引为 None 返回 None", lookup_code_index(None, "1ZC5T") is None)

    # ---------- format_index_line：推送里的码库行 ----------
    print("\n== format_index_line 格式测试 ==")
    line = format_index_line(lookup_code_index(index, "116pq"))
    check("收录行", line == "码库: ✅ 已收录 (BLACKSITE: ASCENDANT | PROGRESSION |)", line)
    check("未收录行", format_index_line(None) == "码库: ➖ 未收录")

    # ---------- verify_hits_against_index：extract_codes 结果过比对 ----------
    print("\n== verify_hits_against_index 集成测试 ==")
    hits = extract_codes("portal code: 1ZC5T, and brand new lobby code NEWC1")
    check("样例文本提取出 2 个码", {h["code"] for h in hits} == {"1ZC5T", "NEWC1"},
          f"got {sorted(h['code'] for h in hits)}")
    verify_hits_against_index(hits, index)
    by_code = {h["code"]: h for h in hits}
    check("已收录码 verified=True", by_code["1ZC5T"]["verified"] is True)
    check("已收录码带码库条目", (by_code["1ZC5T"]["index_entry"] or {}).get("owner") == "tnt_bro")
    check("未收录码 verified=False", by_code["NEWC1"]["verified"] is False)
    check("未收录码 index_entry=None", by_code["NEWC1"]["index_entry"] is None)
    check("原有字段保留（code/snippet/layer）",
          all(k in h for h in hits for k in ("code", "snippet", "layer")))

    # ---------- index_is_fresh：24 小时过期判断 ----------
    print("\n== index_is_fresh 过期判断 ==")
    check("刚建的索引有效", index_is_fresh(make_index(hours_ago=0)) is True)
    check("23 小时的索引仍有效", index_is_fresh(make_index(hours_ago=23)) is True)
    check("25 小时的索引过期", index_is_fresh(make_index(hours_ago=25)) is False)
    check("缺 built_at 视为过期", index_is_fresh({"codes": FAKE_CODES}) is False)
    check("空码索引视为无效", index_is_fresh(make_index() | {"codes": {}}) is False)
    check("None 视为无效", index_is_fresh(None) is False)

    # ---------- 文件存取（临时路径，不碰真实 code_index.json） ----------
    print("\n== save/load_code_index 文件存取 ==")
    restore = patch_module()
    try:
        check("文件不存在返回 None", load_code_index() is None)
        saved = make_index()
        save_code_index(saved)
        loaded = load_code_index()
        check("存取往返一致", loaded == saved)
        with open(TMP_INDEX_FILE, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        check("损坏 JSON 返回 None", load_code_index() is None)
        with open(TMP_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump({"codes": ["不是", "dict"]}, f)
        check("结构异常返回 None", load_code_index() is None)
    finally:
        restore()

    # ---------- refresh_index_if_needed：新鲜直接用 / 失败降级旧索引 ----------
    print("\n== refresh_index_if_needed 重建/降级 ==")

    def boom():
        raise RuntimeError("模拟重建失败（网络不通）")

    restore = patch_module(build=boom)
    try:
        fresh = make_index()
        save_code_index(fresh)
        got = refresh_index_if_needed()
        check("索引新鲜：直接复用不重建", got == fresh)

        stale = make_index(hours_ago=25)
        save_code_index(stale)
        got = refresh_index_if_needed()
        check("索引过期且重建失败：用旧索引继续跑", got == stale)

        os.remove(TMP_INDEX_FILE)
        check("无索引且重建失败：返回 None（不阻塞推送）", refresh_index_if_needed() is None)
    finally:
        restore()

    new_index = make_index()
    new_index["codes"]["zzz99"] = {"code": "ZZZ99", "title": "New Farm", "owner": "x", "broken": False}
    new_index["count"] = len(new_index["codes"])

    def fake_build():
        save_code_index(new_index)  # 真实 build_code_index 也会写盘
        return new_index

    restore = patch_module(build=fake_build)
    try:
        stale = make_index(hours_ago=25)
        save_code_index(stale)
        got = refresh_index_if_needed()
        check("索引过期：重建成功返回新索引", got == new_index)
        check("新索引已写盘", load_code_index() == new_index)

        save_code_index(make_index())
        got = refresh_index_if_needed(force=True)
        check("force=True：索引新鲜也强制重建", got == new_index)
    finally:
        restore()

    print()
    if FAILURES:
        print(f"共 {FAILURES} 个用例失败")
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    run()
