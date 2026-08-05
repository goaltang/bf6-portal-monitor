#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动验证脚本（由 test_push_format.py 改名，避免 pytest 误收集真实发送）：
构造一条假 experience，走 v2 推送逻辑真实发到飞书，用于检查消息格式。跑完可删。"""
from bf6_portal_monitor import build_feishu_text, send_feishu


def main():
    fake = {
        "id": 999999,
        "title": "推送格式测试",
        "code": "TEST1",
        "xp_farm": True,
        "broken": False,
        "bugged": False,
        "description": "这是一条**测试消息**，用于验证 v2 的消息格式。\n\n- 请勿使用此码\n- 详情见 [bfportal.gg](https://bfportal.gg)",
        "tags": ["BF6", "Conquest"],
        "no_players": 64,
        "no_bots": 99,
        "owner": {"username": "tester"},
        "category": {"name": "Multiplayer"},
        "meta": {
            "type": "core.ExperiencePage",
            "html_url": "https://bfportal.gg/experiences/push-format-test/",
        },
    }

    msg = build_feishu_text(fake)
    print("--- 消息内容 ---")
    print(msg)
    print("--- 发送结果 ---")
    print(send_feishu(msg))


if __name__ == "__main__":
    main()
