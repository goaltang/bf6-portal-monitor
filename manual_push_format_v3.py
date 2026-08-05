#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 推送格式验证脚本（由 test_v3_push_format.py 改名，避免 pytest 误收集真实发送）：
1. 补发误报更正说明（前两轮提取器调优前有 7 条误报推进了群）
2. 发一条模拟的 YouTube 码推送（标注"格式测试"），验证三源消息格式
"""
from bf6_portal_monitor import build_youtube_message, send_feishu


def main():
    correction = (
        "⚠️ 监控器说明：刚才推送的 Mode / Setup / Maps / Tags / menu / option / shown "
        "7 条码为误报（YouTube 视频描述里的英文单词），已修复过滤规则，请忽略。"
    )
    print("--- 更正说明 ---")
    print(correction)
    print("发送结果:", send_feishu(correction))

    fake_hit = {
        "code": "TEST1",
        "snippet": "这是一条 v3 格式测试消息，模拟 YouTube 源的推送格式，请勿使用此码",
        "layer": 1,
    }
    fake_video = {
        "id": "TESTTEST123",
        "title": "[格式测试] BF6 AFK XP FARMING LOBBY PORTAL CODE",
        "channel": "monitor-test",
        "views": 0,
    }
    msg = build_youtube_message(fake_hit, fake_video)
    msg = msg.replace("📺 YouTube 新码: TEST1", "📺 YouTube 新码: TEST1（格式测试）")
    print("--- YouTube 格式测试消息 ---")
    print(msg)
    print("发送结果:", send_feishu(msg))


if __name__ == "__main__":
    main()
