#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4 推送格式验证脚本：发一条模拟的 YouTube 码推送到飞书，展示新增的
"社区反馈"行。

- 社区反馈数据由 verify_code_feedback 对真实视频 mFiLNhoQHvU 现场拉评论得出；
- 码本身是虚构占位（1Y8CM），消息首行标注"格式测试"，请勿当真。
"""
from bf6_portal_monitor import (
    build_youtube_message,
    send_feishu,
    verify_code_feedback,
)

VIDEO_ID = "mFiLNhoQHvU"


def main():
    print("--- 现场拉评论验证（%s）---" % VIDEO_ID)
    feedback = verify_code_feedback("youtube", VIDEO_ID, "1Y8CM")
    print("验证结果:", feedback)

    fake_hit = {
        "code": "1Y8CM",
        "snippet": "NEW BF6 WEAPON XP FARM 2 V 64 BOTS //CODE 1Y8CM",
        "layer": 1,
    }
    fake_video = {
        "id": VIDEO_ID,
        "title": "*NEW* UNLIMITED WEAPON XP BOT LOBBY GLITCH IN BF6!（格式测试）",
        "channel": "monitor-test",
        "views": 0,
    }
    msg = build_youtube_message(fake_hit, fake_video, feedback=feedback)
    msg = msg.replace("📺 YouTube 新码: 1Y8CM", "📺 YouTube 新码: 1Y8CM（格式测试，码为虚构请勿使用）")
    print("--- v4 格式测试消息 ---")
    print(msg)
    print("发送结果:", send_feishu(msg))


if __name__ == "__main__":
    main()
