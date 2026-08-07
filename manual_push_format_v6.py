#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 可用码清单格式验证脚本（手动运行，会真实发一条飞书消息）。

构造一个含 3 条码（1 条模拟本轮新码）的账本，调用 build_ledger_message
生成完整清单并发送到飞书（带"格式测试"标注），供人工核对清单格式。
自动化流程请勿运行本脚本。
"""
import sys

from bf6_portal_monitor import build_ledger_message, send_feishu


def main():
    ledger = {
        # 模拟本轮新入账的码（new_keys 里只有它）
        "zd7hy": {
            "code": "ZD7HY",
            "source": "youtube",
            "title": "NEW BF6 PORTAL CODE ZD7HY 2V64 BOTS XP FARM",
            "link": "https://www.youtube.com/watch?v=FORMATTEST6",
            "published": "2026-08-07",
            "feedback": "✅(5+/0-)",
            "index_hit": True,
            "first_found": "2026-08-07T02:00:00+00:00",
            "last_seen": "2026-08-07T02:00:00+00:00",
        },
        # 旧码：reddit 来源，带反馈摘要，码库未命中
        "zz999": {
            "code": "ZZ999",
            "source": "reddit",
            "title": "anyone got a working portal code?",
            "link": "https://www.reddit.com/r/battlefield6/comments/format/test/",
            "published": "2026-08-06 12:34 UTC",
            "feedback": "❌(0+/2-)",
            "index_hit": False,
            "first_found": "2026-08-06T12:34:00+00:00",
            "last_seen": "2026-08-06T12:34:00+00:00",
        },
        # 旧码：bfportal 来源，无反馈（该源不做评论验证）
        "abc12": {
            "code": "ABC12",
            "source": "bfportal",
            "title": "030 Portal Lab",
            "link": "https://bfportal.gg/experiences/1/",
            "published": "2026-08-05",
            "feedback": None,
            "index_hit": True,
            "first_found": "2026-08-05T08:00:00+00:00",
            "last_seen": "2026-08-05T08:00:00+00:00",
        },
    }
    new_keys = ["zd7hy"]

    text = build_ledger_message(ledger, new_keys)
    print(text)
    print("-" * 60)
    ok, info = send_feishu(
        "【格式测试】v6 可用码清单（脚本模拟数据，非真实新码，请忽略）\n\n" + text
    )
    print(f"发送结果：ok={ok} info={info}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
