#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用真实 MCP 数据生成麦麦年度报告（叙事版）
==========================================

数据来源：mcd-mcp 真实接口
- order-list        → 已完成订单
- query-my-coupons  → 可用券
- query-my-account  → 积分账户

真实数据与 mock 的关键差异（见 real_adapter.py 顶部注释）：
接口不返回金额拆分、不返回单项价格、不返回券面额。
本脚本据此走"真实模式"渲染：只展示真实可得的指标，并把拿不到的指标
作为「数据缺口」显式打印出来 —— 绝不用实付倒推假数字。
"""

from __future__ import annotations

import os
from datetime import date

from real_adapter import load_owner_name, load_real
from render_story import generate_story

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if __name__ == "__main__":
    orders, coupons, points, gaps, acct = load_real(year=2026)
    owner = load_owner_name()

    print(f"载入 2026 年真实订单 {len(orders)} 笔 / 券 {len(coupons)} 张 / 积分 {points.available}")
    print(f"开场屏署名：{owner}（在 data/user.json 的 owner_name 里修改）")
    print(f"识别到数据缺口 {len(gaps)} 项")
    for g in gaps:
        print(f"  · {g}")

    print()
    generate_story(
        output=os.path.join(ROOT, "annual_report.story.real.html"),
        mock=False,
        orders=orders,
        coupons=coupons,
        points=points,
        account=acct,
        year=2026,
        owner=owner,
        today=date(2026, 10, 10),
    )
