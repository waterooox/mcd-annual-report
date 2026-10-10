#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock 数据装载器
================

用途：在没有 MCP Token、或不想动真实账户的情况下，完整演示年报全流程。

设计要点：
- mock 数据刻意做成"有故事"的一年：Q1 口味偏主食、Q3 饮品变多、夜宵在考试周集中。
  这样"口味漂移""季度轨迹"这些差异化章节才有东西可展示。
- 所有 mock 数据带 `_mock: true` 标记，渲染层会显式提示"当前为演示数据"，
  绝不让人误以为这是真实账户数据。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import List

from ledger_engine import Coupon, Order, OrderItem, PointsAccount

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(os.path.dirname(_HERE), "mock", "sample_year.json")


def _parse_order(d: dict) -> Order:
    items = [
        OrderItem(
            product_code=i["product_code"],
            name=i["name"],
            unit_price=i["unit_price"],
            qty=i["qty"],
            category=i.get("category", "其他"),
        )
        for i in d["items"]
    ]
    return Order(
        order_no=d["order_no"],
        ts=datetime.fromisoformat(d["ts"]),
        store_name=d.get("store_name", ""),
        store_city=d.get("store_city", ""),
        channel=d.get("channel", "外送"),
        items=items,
        product_total=d["product_total"],
        delivery_fee=d.get("delivery_fee", 0.0),
        discount=d.get("discount", 0.0),
        payable=d["payable"],
        coupon_used=d.get("coupon_used"),
    )


def _load_raw() -> dict:
    with open(_DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def load_mock_orders() -> List[Order]:
    return [_parse_order(d) for d in _load_raw()["orders"]]


def load_mock_coupons() -> List[Coupon]:
    out = []
    for c in _load_raw().get("coupons", []):
        out.append(Coupon(
            coupon_id=c["coupon_id"],
            name=c["name"],
            face_value=c["face_value"],
            threshold=c.get("threshold", 0.0),
            expire_at=date.fromisoformat(c["expire_at"]) if c.get("expire_at") else None,
            redeemable=c.get("redeemable", True),
            kind=c.get("kind", "满减"),
        ))
    return out


def load_mock_points() -> PointsAccount:
    p = _load_raw().get("points", {})
    return PointsAccount(
        available=p.get("available", 0),
        total_earned=p.get("total_earned", 0),
        frozen=p.get("frozen", 0),
        expiring_soon=p.get("expiring_soon", 0),
        expiring_at=date.fromisoformat(p["expiring_at"]) if p.get("expiring_at") else None,
    )


if __name__ == "__main__":
    o = load_mock_orders()
    print(f"mock 订单数：{len(o)}")
    print(f"实付合计：¥{round(sum(x.payable for x in o), 2)}")
    print(f"券数：{len(load_mock_coupons())}")
