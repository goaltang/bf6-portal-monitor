#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5 推送格式验证脚本：发一条带"发布"+"码库"行的模拟推送到飞书，
整体标注"格式测试"，请勿当真。

- YouTube 段：对真实视频现场抓标题/描述/upload_date（yt_fetch_description，
  v5 同一次 --print 调用），现场拉评论验证，码取 code_index.json 里一条
  真实已收录码（展示"码库: ✅ 已收录"行）；
- Reddit 段：模拟帖子，created_utc 转"发布"行，码未收录（展示"➖ 未收录"行）；
- bfportal 段：模拟详情，meta.first_published_at 转"发布"行。
"""
import time

from bf6_portal_monitor import (
    build_feishu_text,
    build_reddit_message,
    build_youtube_message,
    format_created_utc,
    format_upload_date,
    load_code_index,
    lookup_code_index,
    send_feishu,
    verify_code_feedback,
    yt_fetch_description,
)

VIDEO_ID = "mFiLNhoQHvU"  # v4 格式测试用过的真实视频


def pick_index_code(index):
    """从码库挑一条真实已收录码（优先非 broken）。"""
    for entry in index["codes"].values():
        if not entry.get("broken"):
            return entry
    return next(iter(index["codes"].values()))


def main():
    index = load_code_index()
    if index is None:
        raise SystemExit("code_index.json 不存在，先跑 python3 bf6_portal_monitor.py --rebuild-index")
    entry = pick_index_code(index)
    code = entry["code"]
    print(f"码库挑一条真实码：{code} -> {entry['title']}")

    print(f"现场抓视频详情+发布日期（{VIDEO_ID}）…")
    title, _, upload_date = yt_fetch_description(VIDEO_ID)
    published = format_upload_date(upload_date)
    print(f"视频：{title}　发布：{published or 'NA'}")

    print("现场拉评论验证社区反馈…")
    feedback = verify_code_feedback("youtube", VIDEO_ID, code)
    print("验证结果:", feedback)

    yt_hit = {
        "code": code,
        "snippet": f"//CODE {code}（格式测试，视频为真实视频，码取自码库）",
        "layer": 1,
        "verified": True,
        "index_entry": lookup_code_index(index, code),
    }
    yt_video = {"id": VIDEO_ID, "title": title, "channel": "monitor-test", "views": 0}
    yt_msg = build_youtube_message(yt_hit, yt_video, feedback=feedback, published=published)

    rd_hit = {
        "code": "ZZZ90",
        "snippet": "模拟 Reddit 码，码库未收录（格式测试，请勿使用）",
        "layer": 1,
        "verified": False,
        "index_entry": None,
    }
    rd_item = {
        "title": "[格式测试] BF6 portal code thread",
        "permalink": "/r/battlefield6/comments/xxxxxx/format_test/",
        "created_utc": time.time() - 7200,
    }
    rd_msg = build_reddit_message(
        rd_hit, rd_item, "battlefield6", "posts",
        published=format_created_utc(rd_item["created_utc"]),
    )

    bp_msg = build_feishu_text({
        "id": 999998,
        "title": "v5 发布行格式测试",
        "code": "TEST5",
        "xp_farm": True,
        "broken": False,
        "description": "模拟 bfportal 详情（格式测试，请勿使用此码）",
        "no_players": 64,
        "no_bots": 99,
        "owner": {"username": "monitor-test"},
        "meta": {
            "type": "core.ExperiencePage",
            "html_url": "https://bfportal.gg/experiences/v5-format-test/",
            "first_published_at": "2026-08-03T16:17:20.377752Z",
        },
    })

    msg = "\n".join([
        "【v5 格式测试】以下为三源推送样例（新增 发布/码库 两行），请勿当真：",
        "──────────",
        yt_msg,
        "──────────",
        rd_msg,
        "──────────",
        bp_msg,
    ])
    print("--- v5 格式测试消息 ---")
    print(msg)
    print("发送结果:", send_feishu(msg))


if __name__ == "__main__":
    main()
