#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_codes() 单元测试（纯标准库，直接 python3 运行）。

覆盖任务规格中的真实码样本（应命中）与误报样本（应过滤），共 27 例。
"""
import sys

from bf6_portal_monitor import extract_codes

# (用例名, 输入文本, 期望提取到的码集合)
CASES = [
    # ---------- 正例：真实码样本（应命中） ----------
    ("L1 冒号引导 code: X7ST",
     "code: X7ST",
     {"X7ST"}),
    ("L1 冒号引导纯字母码 portal: MPHD",
     "portal: MPHD",
     {"MPHD"}),
    ("L1 server code 119su",
     "New server code 119su, join quick before it gets patched",
     {"119su"}),
    ("L1 连字符引导 Portal code - 1ZC5T",
     "Portal code - 1ZC5T",
     {"1ZC5T"}),
    ("L2 标题紧邻 LOBBY/PORTAL 1XUJA",
     "BF6 NEW AFK XP FARMING LOBBY PORTAL // 1XUJA / BATTLEFILED 6",
     {"1XUJA"}),
    ("L2 真实 YouTube 标题 SZV4R",
     "BF6 WEAPON XP LOBBY / SZV4R / CONQUEST // BATTLEFIELD 6 PORTAL CODE",
     {"SZV4R"}),
    ("L2 松散语境 The code is 7AUR",
     "The code is 7AUR, have fun",
     {"7AUR"}),
    ("L2 experience 语境 YC5NN",
     "my new experience YC5NN is full of bots",
     {"YC5NN"}),
    ("L1 lobby ZJ7DX",
     "lobby ZJ7DX for bot matches",
     {"ZJ7DX"}),
    ("L1 server: X8XB",
     "server: X8XB — join quick",
     {"X8XB"}),
    ("L3 冒号引出+语境词 6GVY",
     "Mirak-style infected map: 6GVY",
     {"6GVY"}),
    ("L3 逗号引出+语境词 116PQ",
     "new conquest farm, 116PQ",
     {"116PQ"}),
    ("小写码原样保留 11ayn",
     "quick match code 11ayn",
     {"11ayn"}),
    ("Reddit 评论口语 ZJ7DX",
     "Here you go, portal code: ZJ7DX, have fun!",
     {"ZJ7DX"}),
    ("一段文本多个码",
     "code: X7ST and portal Z4ZT6 both work",
     {"X7ST", "Z4ZT6"}),
    ("URL 抹掉后仍提取真实码",
     "Watch https://www.youtube.com/watch?v=dQw4w9WgXcQ then use portal code: MPHD",
     {"MPHD"}),
    ("多行视频描述提码",
     "BF6 AFK XP FARM\n\njoin with portal code: 1ZC5T\n\nno bots needed, pure xp grind",
     {"1ZC5T"}),

    # ---------- 反例：误报样本（应过滤） ----------
    ("黑名单 ENTIRE（引导词后也过滤）",
     "portal code: ENTIRE lobby is bugged",
     set()),
    ("黑名单 CLASS",
     "server code CLASS, pick one",
     set()),
    ("黑名单 CUSTOM",
     "portal: CUSTOM settings",
     set()),
    ("数字单位 99ms",
     "my ping is 99ms today",
     set()),
    ("帧率/分辨率 120fps 1080p",
     "runs 120fps at 1080p easily",
     set()),
    ("游戏名 BF2042（引导词后也过滤）",
     "server code: BF2042 is old news",
     set()),
    ("discord.gg 邀请码片段",
     "join discord.gg/X7ST for updates",
     set()),
    ("数字单位 500XP",
     "got 500XP bonus today",
     set()),
    ("空文本",
     "",
     set()),
    ("纯数字不当码",
     "code: 2026",
     set()),
    ("无语境的纯字母词",
     "totally random words like PLANT in the sun",
     set()),
    ("YouTube SEO 关键词块（实测误报回归）",
     "BF6 Portal Mode Guide, BF6 Portal Bot Lobby, BF6 Portal Maps, "
     "Portal Bot Lobby Setup, BF6 Portal Codes 2025, BF6 Portal Guide, New AFK Lobby Code",
     set()),
    ("视频描述 Tags 块",
     "Tags: portal, xp farm, battlefield 6",
     set()),
    ("教程类描述小写单词（实测误报回归）",
     "Go to the Battlefield Portal menu. Select \"Host\" or \"Server Browser\" and look for "
     "the Experience Code option. Enter one of the codes shown in today's video.",
     set()),
    ("纯小写纯字母串不当码",
     "portal: mphd",
     set()),
]


def main():
    failed = 0
    for name, text, expected in CASES:
        got = {h["code"] for h in extract_codes(text)}
        if got == expected:
            print(f"PASS  {name}")
        else:
            failed += 1
            print(f"FAIL  {name}\n      期望: {sorted(expected)}\n      实际: {sorted(got)}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} 用例通过")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
