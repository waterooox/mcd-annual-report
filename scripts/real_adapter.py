#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实 MCP 数据适配器
===================

职责：把 mcd-mcp 真实接口的返回结构，转换成 ledger_engine 的 Order / Coupon 模型。

【真机联调发现的结构差异】—— 这是设计 mock 阶段无法预知的：

1. `order-list` 返回的金额只有一个 `realTotalAmount`（实付），
   **没有** `productTotal` / `deliveryFee` / `discount` 的拆分。
   → 因此"原价""优惠""配送费"这些指标在真实数据下**无法计算**，必须显式标注为不可得，
     绝不能拿实付去倒推一个假的"省下金额"。

2. 商品明细嵌在 `orderProductList[].comboItemList[]` 里，是**套餐的子项**，
   不含单项价格 → 单品行无法给出 `unitPrice`，只能用套餐实付均摊（并标注为估算）。

3. `query-my-coupons` 返回的是**用券价格**（`price`），不是面额，
   且券的有效期是**具体到日期甚至时段**，还有"到店专用/外送专用"的限制标签。
   → 面额需要由"用券价 vs 原价"推算，而原价不可得 → 面额同样标注为不可得。

这三条差异说明：**"可回溯"的承诺必须包含"如实说明哪些数据拿不到"**，
而不是硬凑出一个好看的数字。这正是本项目与"编造型"年报的分水岭。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, date
from typing import Any, Dict, List, Tuple

from ledger_engine import Coupon, Order, OrderItem, PointsAccount

_HERE = os.path.dirname(os.path.abspath(__file__))
_REAL = os.path.join(os.path.dirname(_HERE), "data", "real_snapshot.json")
_USER_CFG = os.path.join(os.path.dirname(_HERE), "data", "user.json")


def load_owner_name(default: str = "我自己") -> str:
    """读用户自定义昵称（data/user.json 的 owner_name）。

    MCP 接口不返回昵称（query-my-account 只有会员 ID 与积分字段），
    所以署名由用户在 data/user.json 里自行填写；未配置或留空则回落 default。
    """
    try:
        with open(_USER_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        name = str(cfg.get("owner_name") or "").strip()
        return name or default
    except (OSError, ValueError):
        return default

# 品类推断表：MCP 不返回品类字段，这里用名称关键词做**保守**归类。
# 归不进去的一律标为"其他"，不做过度猜测。
_CATEGORY_RULES: List[Tuple[str, str]] = [
    ("堡", "主食"), ("鸡腿", "主食"), ("鸡排", "主食"), ("吉士", "主食"),
    ("随心配", "主食"), ("三件套", "主食"), ("双人餐", "主食"), ("任选", "主食"),
    ("薯条", "小食"), ("薯饼", "小食"), ("脆汁鸡", "小食"), ("琵琶腿", "小食"), ("小食", "小食"),
    ("可乐", "饮品"), ("咖啡", "饮品"), ("奶茶", "饮品"), ("雪碧", "饮品"), ("冰", "饮品"),
    ("麦旋风", "甜点"), ("派", "甜点"), ("新地", "甜点"), ("松饼", "甜点"), ("奥利奥", "甜点"),
]


def infer_category(name: str) -> str:
    for kw, cat in _CATEGORY_RULES:
        if kw in name:
            return cat
    return "其他"


def _parse_ts(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间：{s}")


def adapt_orders(raw_orders: List[Dict[str, Any]]) -> Tuple[List[Order], List[Dict[str, Any]]]:
    """
    转换订单，并返回 (订单列表, 数据缺口说明列表)。

    金额口径处理：
    - payable = realTotalAmount（真实可得，可信）
    - product_total / delivery_fee / discount 真实接口未提供 → 置为 0，
      并在缺口说明中记录，避免渲染层把它们当成真实值展示。
    """
    orders: List[Order] = []
    gaps: List[Dict[str, Any]] = []

    for r in raw_orders:
        order_id = r["orderId"]
        ts = _parse_ts(r["createTime"])
        payable = float(r.get("realTotalAmount") or 0)

        items: List[OrderItem] = []
        # 展平套餐子项，用套餐实付均摊给各子项（标注为估算口径）
        all_subs: List[Tuple[str, str, int]] = []
        for p in r.get("orderProductList", []):
            for c in p.get("comboItemList", []) or []:
                all_subs.append((c.get("productCode", ""), c.get("name", ""), int(c.get("quantity", 1))))
            if not p.get("comboItemList"):
                all_subs.append((p.get("productCode", ""), p.get("productName", ""),
                                 int(p.get("quantity", 1))))

        total_qty = sum(q for _, _, q in all_subs) or 1
        unit = round(payable / total_qty, 2) if payable else 0.0
        for code, name, qty in all_subs:
            items.append(OrderItem(
                product_code=code,
                name=name,
                unit_price=unit,          # ← 均摊估算值，非真实单价
                qty=qty,
                category=infer_category(name),
            ))

        orders.append(Order(
            order_no=order_id,
            ts=ts,
            store_name=r.get("storeName", ""),
            store_city=_city_from_store(r.get("storeName", "")),
            channel="到店取餐",            # 真实数据未标注渠道，按已完成堂食/取餐单处理
            items=items,
            product_total=payable,        # 缺拆分，暂等于实付（渲染层不展示"原价"）
            delivery_fee=0.0,
            discount=0.0,
            payable=payable,
            coupon_used=None,
        ))

    if raw_orders:
        gaps.append({
            "field": "金额拆分（原价 / 配送费 / 优惠）",
            "impact": "无法计算『原价』『配送费』『省下金额』『折扣率』",
            "reason": "订单数据只提供实付金额，没有提供金额的各段拆分",
            "handling": "相关指标显示为『未提供』，不用实付倒推",
        })
        gaps.append({
            "field": "单品单价",
            "impact": "单品无法给出真实单价",
            "reason": "商品明细为套餐子项，不含单项价格",
            "handling": "按套餐实付 ÷ 总件数均摊，并在页面标注为估算口径",
        })

    return orders, gaps


def _city_from_store(store_name: str) -> str:
    """从门店名尽力提取城市。提取不到则返回空，不瞎猜。"""
    cities = ["银川", "武汉", "北京", "上海", "广州", "深圳", "成都", "杭州",
              "西安", "南京", "重庆", "天津", "苏州", "长沙", "郑州", "青岛"]
    for c in cities:
        if c in store_name:
            return c
    return ""


def adapt_coupons(raw_coupons: List[Dict[str, Any]]) -> Tuple[List[Coupon], List[Dict[str, Any]]]:
    """
    转换券。

    注意：接口返回的 `price` 是**用券价**（券后价），不是面额。
    真实面额需要"原价 - 用券价"才能算出，但原价不可得。
    → 因此这里把 price 记为 face_value 是**不准确**的，我们改用
      face_value = 0 并在渲染层只展示"用券价"与有效期和限用标签。
    为保持引擎可用，这里用 face_value 承载"用券价"，并在 gaps 中说明语义。
    """
    coupons: List[Coupon] = []
    gaps: List[Dict[str, Any]] = []

    for i, c in enumerate(raw_coupons):
        try:
            exp = _parse_ts(c.get("validTo", "")).date()
        except Exception:
            exp = None
        # 用券价作为"参考价值"，threshold 置 0
        coupons.append(Coupon(
            coupon_id=f"REAL_C{i+1:02d}",
            name=c.get("name", "优惠券"),
            face_value=float(c.get("price") or 0),
            threshold=0.0,
            expire_at=exp,
            redeemable=True,
            kind="用券价",
        ))

    if raw_coupons:
        gaps.append({
            "field": "优惠券面额",
            "impact": "无法计算券的『门槛效率』与『真实面额』",
            "reason": "券数据返回的是用券后的价格，不是面额",
            "handling": "改展示『用券价 + 有效期 + 限用标签』，面额标为未提供",
        })

    return coupons, gaps


def adapt_points(raw: Dict[str, Any]) -> PointsAccount:
    return PointsAccount(
        available=int(float(raw.get("availablePoint") or 0)),
        total_earned=int(float(raw.get("accumulativePoint") or 0)),
        frozen=int(float(raw.get("frozenPoint") or 0)),
        expiring_soon=int(float(raw.get("currentMouthExpirePoint") or 0)),
        expiring_at=None,
    )


def load_real(year: int | None = None) -> Tuple[List[Order], List[Coupon], PointsAccount, List[Dict[str, Any]], Dict[str, Any]]:
    """
    载入真实快照，返回订单、券、积分、数据缺口、原始账户信息。

    year 不为 None 时，只返回该年份的订单。
    注意：真实接口的 order-list 会返回**跨年**订单（实测返回了 2025 与 2026 两年），
    因此做"年度报告"时必须显式按年份过滤，否则会把往年的单算进本年度。
    """
    import json
    with open(_REAL, "r", encoding="utf-8") as f:
        snap = json.load(f)

    orders, g1 = adapt_orders(snap.get("orders", []))
    coupons, g2 = adapt_coupons(snap.get("coupons", []))
    points = adapt_points(snap.get("account", {}))

    gaps = g1 + g2
    if year is not None:
        before = len(orders)
        orders = [o for o in orders if o.ts.year == year]
        if before != len(orders):
            gaps.append({
                "field": "订单年份过滤",
                "impact": f"共取到 {before} 笔历史订单，其中 {len(orders)} 笔属于 {year} 年",
                "reason": "订单记录不分年份返回，包含历史全部订单",
                "handling": f"仅统计 {year} 年订单，避免往年被计入本年度",
            })

    return orders, coupons, points, gaps, snap.get("account", {})


if __name__ == "__main__":
    orders, coupons, points, gaps, acct = load_real()
    print(f"真实订单：{len(orders)} 笔")
    for o in orders:
        print(f"  {o.ts.date()}  {o.payable:>7.2f}  {o.store_name}  ({len(o.items)} 个子项)")
    print(f"\n真实券：{len(coupons)} 张")
    for c in coupons:
        print(f"  {c.expire_at}  ¥{c.face_value:<6} {c.name}")
    print(f"\n积分：可用 {points.available} / 累计 {points.total_earned}")
    print(f"\n数据缺口（{len(gaps)} 项）：")
    for g in gaps:
        print(f"  - {g['field']}: {g['impact']}")
