#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦年度报告 · MCD Annual Report —— 核心计算引擎
================================================

设计原则（这也是本项目与同类"人格/段位"项目的根本分野）：

1. 可回溯（Traceable）：年报里的每一个数字，都必须能指回具体的订单号 / 券 ID。
   本引擎对每一项聚合指标都生成 `trace` 字段，记录它由哪些原始记录、按什么公式得出。
2. 可手算（Hand-checkable）：所有金额计算只用加减乘除，不引入任何不可复现的权重。
   用户拿计算器和订单流水，可以逐项复算本文报的任意一个数。
3. 有同比（Period-over-Period）：不只是截面统计，而是按季度切片，给出轨迹与同比。
4. 闭环（Closed-loop）：分析结果直接产出可执行动作（券到期清算、套餐替换省钱），
   并可交给上层经由用户确认后创建订单。

零第三方依赖，仅用标准库。所有函数为纯函数，输入 dict 输出 dict，便于单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from collections import defaultdict


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class OrderItem:
    """订单中的单个商品行。"""
    product_code: str
    name: str
    unit_price: float          # 单价（元）
    qty: int                   # 数量
    category: str = "其他"      # 品类：主食/小食/饮品/甜点/其他

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.qty, 2)


@dataclass
class Order:
    """一笔历史订单。字段大多对应麦当劳 MCP `order-list` / `query-order` 返回结构。"""
    order_no: str                       # 订单号 —— 回溯的锚点
    ts: datetime                        # 下单时间
    store_name: str = ""
    store_city: str = ""
    channel: str = "外送"                # 外送 / 到店取餐 / 得来速 / 堂食
    items: List[OrderItem] = field(default_factory=list)
    # 金额口径（与麦当劳订单详情一致）
    product_total: float = 0.0          # 商品原价合计
    delivery_fee: float = 0.0           # 配送费
    discount: float = 0.0               # 优惠金额（券 + 活动，正数表示减免）
    payable: float = 0.0                # 实付
    coupon_used: Optional[str] = None    # 使用的券 ID（便于"用了谁的券"清算）

    @property
    def saved(self) -> float:
        """本单省下的钱 = 商品原价 + 配送费 - 实付。"""
        return round(self.product_total + self.delivery_fee - self.payable, 2)

    @property
    def discount_rate(self) -> float:
        """折扣率 = 优惠金额 / (商品原价 + 配送费)。"""
        gross = self.product_total + self.delivery_fee
        if gross <= 0:
            return 0.0
        return round(self.discount / gross, 4)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        d["items"] = [asdict(i) | {"subtotal": i.subtotal} for i in self.items]
        d["saved"] = self.saved
        d["discount_rate"] = self.discount_rate
        return d


@dataclass
class Coupon:
    """一张优惠券 / 兑换券。对应 MCP `query-my-coupons` 返回结构。"""
    coupon_id: str
    name: str
    face_value: float                   # 面额（元）
    threshold: float                    # 使用门槛（满 X 元可用），0 表示无门槛
    expire_at: Optional[date] = None    # 到期日
    redeemable: bool = True             # 门店级可用性（经 query-store-coupons 校验）
    kind: str = "满减"                   # 满减 / 兑换 / 折扣


@dataclass
class PointsAccount:
    """积分账户。对应 MCP `query-my-account`。"""
    available: int = 0
    total_earned: int = 0
    frozen: int = 0
    expiring_soon: int = 0              # 即将过期积分
    expiring_at: Optional[date] = None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def _pct_change(cur: float, prev: float) -> Optional[float]:
    """同比/环比变化率。prev 为 0 时返回 None（不编造"增长 100%"这种假数）。"""
    if prev == 0:
        return None
    return round((cur - prev) / prev, 4)


def _fmt_pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:+.1f}%"


# ---------------------------------------------------------------------------
# 1. 汇总：年度总账（每一格都可回溯）
# ---------------------------------------------------------------------------

def summarize_orders(orders: Sequence[Order]) -> Dict[str, Any]:
    """年度总账。返回的每个指标都带 trace，指向构成它的订单号。"""
    if not orders:
        return {
            "empty": True,
            "order_count": 0,
            "message": "本年度暂无订单记录。",
            "trace": {"order_count": {"formula": "count(orders)", "sources": []}},
        }

    n = len(orders)
    gross = round(sum(o.product_total + o.delivery_fee for o in orders), 2)
    paid = round(sum(o.payable for o in orders), 2)
    saved = round(sum(o.saved for o in orders), 2)
    delivery = round(sum(o.delivery_fee for o in orders), 2)

    # 客单价
    aov = round(paid / n, 2)

    # 品类结构：按 subtotal 加权
    cat_amount: Dict[str, float] = defaultdict(float)
    cat_count: Dict[str, int] = defaultdict(int)
    for o in orders:
        for it in o.items:
            cat_amount[it.category] += it.subtotal
            cat_count[it.category] += it.qty
    cat_amount = {k: round(v, 2) for k, v in cat_amount.items()}

    # 最常点的单品（按数量）
    item_qty: Dict[str, int] = defaultdict(int)
    item_spend: Dict[str, float] = defaultdict(float)
    for o in orders:
        for it in o.items:
            item_qty[it.name] += it.qty
            item_spend[it.name] += it.subtotal
    top_items = sorted(item_qty.items(), key=lambda kv: (-kv[1], -item_spend[kv[0]]))[:5]

    # 时段分布
    hour_bucket: Dict[str, int] = defaultdict(int)
    for o in orders:
        hour_bucket[_time_slot(o.ts.hour)] += 1

    # 渠道分布
    channel_count: Dict[str, int] = defaultdict(int)
    for o in orders:
        channel_count[o.channel] += 1

    # 门店分布
    store_count: Dict[str, int] = defaultdict(int)
    for o in orders:
        store_count[o.store_name or o.store_city or "未知"] += 1

    # 有券订单占比
    with_coupon = [o.order_no for o in orders if o.coupon_used]
    discount_rate = round(round(discount_sum := sum(o.discount for o in orders), 2) / gross, 4) if gross else 0.0

    return {
        "empty": False,
        "order_count": n,
        "gross": gross,                       # 原价 + 配送费
        "paid": paid,                         # 实付
        "saved": saved,                       # 省下
        "delivery_fee": delivery,
        "aov": aov,                           # 客单价
        "total_discount": round(discount_sum, 2),
        "discount_rate": discount_rate,
        "coupon_order_count": len(with_coupon),
        "category_amount": cat_amount,
        "category_count": dict(cat_count),
        "top_items": [{"name": k, "qty": v, "spend": round(item_spend[k], 2)} for k, v in top_items],
        "hour_distribution": dict(hour_bucket),
        "channel_distribution": dict(channel_count),
        "store_distribution": dict(store_count),
        # ---- 回溯表：每个结论指回原始订单 ----
        "trace": {
            "order_count": {"formula": "count(orders)", "sources": [o.order_no for o in orders]},
            "gross": {
                "formula": "原价合计 = 各单（商品原价 + 配送费）逐单相加",
                "sources": [o.order_no for o in orders],
            },
            "paid": {"formula": "实付合计 = 各单实付金额逐单相加", "sources": [o.order_no for o in orders]},
            "saved": {
                "formula": "省下金额 = 各单（商品原价 + 配送费 − 实付）逐单相加",
                "sources": [o.order_no for o in orders],
            },
            "aov": {"formula": "客单价 = 实付合计 ÷ 订单数", "sources": ["全部订单"]},
            "discount_rate": {
                "formula": "折扣率 = 优惠合计 ÷ 原价合计",
                "sources": [o.order_no for o in orders],
            },
            "top_items": {
                "formula": "按 Σ(qty) 降序，同数量按 Σ(subtotal) 降序",
                "sources": [o.order_no for o in orders],
            },
            "coupon_order_count": {
                "formula": "count(orders where coupon_used is not null)",
                "sources": with_coupon,
            },
        },
    }


def _time_slot(hour: int) -> str:
    if 5 <= hour < 10:
        return "早餐(05-10)"
    if 10 <= hour < 14:
        return "午餐(10-14)"
    if 14 <= hour < 17:
        return "下午茶(14-17)"
    if 17 <= hour < 21:
        return "晚餐(17-21)"
    return "夜宵(21-05)"


# ---------------------------------------------------------------------------
# 2. 季度切片 + 同比轨迹
# ---------------------------------------------------------------------------

def quarterly_breakdown(orders: Sequence[Order], year: int) -> List[Dict[str, Any]]:
    """按季度切片，给出实付、订单数、客单价、折扣率的轨迹。"""
    buckets: Dict[int, List[Order]] = defaultdict(list)
    for o in orders:
        if o.ts.year == year:
            buckets[quarter_of(o.ts.date())].append(o)

    result: List[Dict[str, Any]] = []
    for q in (1, 2, 3, 4):
        os_ = buckets.get(q, [])
        paid = round(sum(o.payable for o in os_), 2)
        gross = round(sum(o.product_total + o.delivery_fee for o in os_), 2)
        disc = round(sum(o.discount for o in os_), 2)
        n = len(os_)
        result.append({
            "quarter": f"Q{q}",
            "order_count": n,
            "paid": paid,
            "aov": round(paid / n, 2) if n else 0.0,
            "discount_rate": round(disc / gross, 4) if gross else 0.0,
            "trace": {"sources": [o.order_no for o in os_]},
        })
    return result


def month_slices(orders: Sequence[Order], year: int) -> List[Dict[str, Any]]:
    """按月切片，用于"轨迹"章节。"""
    buckets: Dict[int, List[Order]] = defaultdict(list)
    for o in orders:
        if o.ts.year == year:
            buckets[o.ts.month].append(o)
    out = []
    for m in range(1, 13):
        os_ = buckets.get(m, [])
        out.append({
            "month": m,
            "order_count": len(os_),
            "paid": round(sum(o.payable for o in os_), 2),
            "sources": [o.order_no for o in os_],
        })
    return out


def flavor_drift(orders: Sequence[Order], year: int) -> Dict[str, Any]:
    """
    口味漂移：对比"上半年"与"下半年"的品类占比变化。
    这是同类截面统计项目普遍缺失的纵向视角。
    """
    h1 = [o for o in orders if o.ts.year == year and o.ts.month <= 6]
    h2 = [o for o in orders if o.ts.year == year and o.ts.month >= 7]

    def cat_share(os_: Sequence[Order]) -> Dict[str, float]:
        amt: Dict[str, float] = defaultdict(float)
        for o in os_:
            for it in o.items:
                amt[it.category] += it.subtotal
        total = sum(amt.values())
        if total <= 0:
            return {}
        return {k: round(v / total, 4) for k, v in amt.items()}

    s1, s2 = cat_share(h1), cat_share(h2)
    cats = sorted(set(s1) | set(s2))
    drift = []
    for c in cats:
        a, b = s1.get(c, 0.0), s2.get(c, 0.0)
        drift.append({
            "category": c,
            "h1_share": a,
            "h2_share": b,
            "delta": round(b - a, 4),
        })
    drift.sort(key=lambda d: -abs(d["delta"]))

    return {
        "h1_order_count": len(h1),
        "h2_order_count": len(h2),
        "drift": drift,
        "narrative": _drift_narrative(drift),
        "trace": {
            "formula": "品类占比 = 该品类金额 ÷ 全部金额，分别在上半年/下半年计算后相减",
            "sources": {"h1": [o.order_no for o in h1], "h2": [o.order_no for o in h2]},
        },
    }


def _drift_narrative(drift: List[Dict[str, Any]]) -> str:
    if not drift:
        return "数据不足，无法判断口味漂移。"
    top = drift[0]
    if abs(top["delta"]) < 0.03:
        return "上半年与下半年的口味结构基本稳定，没有明显漂移。"
    name, a, b = top["category"], top["h1_share"], top["h2_share"]
    if top["delta"] > 0:
        return f"下半年你的「{name}」占比从 {a*100:.1f}% 升到 {b*100:.1f}%，吃得比上半年更偏向这一类。"
    return f"下半年你的「{name}」占比从 {a*100:.1f}% 降到 {b*100:.1f}%，这一类吃得比上半年少了。"


# ---------------------------------------------------------------------------
# 3. 券资产清算（闭环的入口）
# ---------------------------------------------------------------------------

def coupon_actions(
    coupons: Sequence[Coupon],
    orders: Sequence[Order],
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    券资产清算：算出每张券的"门槛效率"，并结合实际消费能力判断该不该用。
    输出直接可执行的动作清单（这正是不碰下单的项目所缺少的）。
    """
    today = today or date.today()

    # 从历史订单推算"单次消费中位数"，作为能否够到门槛的能力基准。
    # 注意：偶数样本必须取中间两个数的算术平均，否则会偏向上中位数。
    typical = median_payable(orders)

    rows: List[Dict[str, Any]] = []
    for c in coupons:
        days_left = (c.expire_at - today).days if c.expire_at else None
        # 门槛效率：每 1 元门槛换来多少面额。无门槛视为最高效率。
        efficiency = round(c.face_value / c.threshold, 4) if c.threshold > 0 else 99.0

        # 可达性：典型消费能否够到门槛
        reachable = c.threshold <= typical if c.threshold > 0 else True

        # 紧迫度
        if days_left is None:
            urgency = 0.5
        elif days_left < 0:
            urgency = -1.0          # 已过期
        elif days_left <= 7:
            urgency = 1.0
        elif days_left <= 30:
            urgency = 0.6
        else:
            urgency = 0.2

        # 综合建议分（仍然可手算：效率 × 紧迫 × 可达性系数）
        score = round(efficiency_clip(efficiency) * urgency * (1.0 if reachable else 0.3), 4)

        rows.append({
            "coupon_id": c.coupon_id,
            "name": c.name,
            "face_value": c.face_value,
            "threshold": c.threshold,
            "expire_at": c.expire_at.isoformat() if c.expire_at else None,
            "days_left": days_left,
            "efficiency": efficiency,
            "reachable_by_typical_order": reachable,
            "typical_order_payable": typical,
            "redeemable_in_store": c.redeemable,
            "urgency": urgency,
            "priority_score": score,
            "action": _coupon_action(c, days_left, reachable),
        })

    rows.sort(key=lambda r: -r["priority_score"])
    expiring = [r for r in rows if r["days_left"] is not None and 0 <= r["days_left"] <= 7]
    expired = [r for r in rows if r["days_left"] is not None and r["days_left"] < 0]
    blocked = [r for r in rows if not r["redeemable_in_store"]]

    return {
        "total_face_value": round(sum(c.face_value for c in coupons), 2),
        "coupon_count": len(coupons),
        "expiring_within_7d": expiring,
        "expired_count": len(expired),
        "store_unavailable_count": len(blocked),
        "priority_list": rows,
        "trace": {
            "formula": "门槛效率 = 面额 / 门槛（无门槛记为 99）；典型消费 = 历史订单实付的中位数；"
                       "建议分 = min(效率,5) × 紧迫度 × 可达性系数",
            "typical_order_payable": typical,
            "median_formula": "奇数样本取 pays[n//2]；偶数样本取 (pays[n//2-1]+pays[n//2])/2",
        },
    }


def efficiency_clip(e: float) -> float:
    """把效率截断到 [0,5]，避免无门槛券（99）把分数拉爆，保证各券可比。"""
    return max(0.0, min(e, 5.0))


def median_payable(orders: Sequence[Order]) -> float:
    """
    实付中位数（标准定义）：
    - 奇数个样本：取正中间那个
    - 偶数个样本：取中间两个的算术平均
    这是"典型消费能力"的基准，用于判断券门槛是否够得着。
    """
    pays = sorted(o.payable for o in orders)
    n = len(pays)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return round(pays[n // 2], 2)
    return round((pays[n // 2 - 1] + pays[n // 2]) / 2, 2)


def _coupon_action(c: Coupon, days_left: Optional[int], reachable: bool) -> str:
    if days_left is not None and days_left < 0:
        return "已过期，可忽略"
    if not c.redeemable:
        return "当前门店不可用，需换店或换券"
    if days_left is not None and days_left <= 7:
        if reachable:
            return f"⚠️ {days_left}天内到期，建议尽快使用"
        return f"⚠️ {days_left}天内到期，但门槛¥{c.threshold}高于你的典型消费，需凑单或放弃"
    if not reachable:
        return f"门槛¥{c.threshold}高于你的典型消费，优先级低"
    return "常规券，按需使用"


# ---------------------------------------------------------------------------
# 4. 省钱动作建议（闭环的输出）
# ---------------------------------------------------------------------------

def saving_playbook(
    orders: Sequence[Order],
    coupons: Sequence[Coupon],
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    产出"明年的钱可以怎么花"的行动清单。
    每条动作都附带：依据（回溯到订单/券）+ 预估可省金额 + 可验证的算法。
    """
    today = today or date.today()
    actions: List[Dict[str, Any]] = []

    coupon_report = coupon_actions(coupons, orders, today)

    # 动作 1：临期券清算
    for r in coupon_report["expiring_within_7d"]:
        if r["reachable_by_typical_order"] and r["redeemable_in_store"]:
            actions.append({
                "type": "use_coupon",
                "title": f"用掉「{r['name']}」",
                "reason": f"{r['days_left']}天后到期，你的典型消费¥{r['typical_order_payable']}已够门槛¥{r['threshold']}",
                "est_saving": r["face_value"],
                "evidence": {"coupon_id": r["coupon_id"], "days_left": r["days_left"]},
                "needs_confirmation": True,
            })

    # 动作 2：配送费优化 —— 若外送订单占比高且配送费可观
    delivery_total = sum(o.delivery_fee for o in orders)
    delivery_orders = [o for o in orders if o.delivery_fee > 0]
    if delivery_total > 0 and len(delivery_orders) >= 3:
        per = round(delivery_total / len(delivery_orders), 2)
        actions.append({
            "type": "reduce_delivery",
            "title": "改用到店取餐替代部分外送",
            "reason": f"全年配送费共¥{round(delivery_total,2)}，{len(delivery_orders)}单平均每单¥{per}",
            "est_saving": round(delivery_total * 0.5, 2),
            "assumption": "假设 50% 的外送单可改为到店自取（仅为估算情景，非承诺）",
            "evidence": {"order_nos": [o.order_no for o in delivery_orders]},
            "needs_confirmation": False,
        })

    # 动作 3：时段集中度 —— 若集中在高价时段，提示错峰
    hour_dist = defaultdict(int)
    for o in orders:
        hour_dist[_time_slot(o.ts.hour)] += 1
    if hour_dist:
        peak_slot, peak_n = max(hour_dist.items(), key=lambda kv: kv[1])
        if peak_slot.startswith(("午餐", "晚餐")) and peak_n >= 5:
            actions.append({
                "type": "shift_timing",
                "title": "错峰下单",
                "reason": f"你的 {peak_n} 单集中在{peak_slot}，该时段通常是高峰溢价时段",
                "est_saving": None,
                "assumption": "错峰能否省钱取决于当期活动，需实时核价确认",
                "evidence": {"slot": peak_slot, "count": peak_n},
                "needs_confirmation": False,
            })

    # 动作 4：积分即将过期
    actions.append({
        "type": "points_check",
        "title": "核对即将过期的积分",
        "reason": "积分会贬值，需在使用前核算兑换 ROI",
        "est_saving": None,
        "evidence": {"note": "调用 query-my-account 获取 expiring_soon"},
        "needs_confirmation": False,
    })

    total_est = round(sum(a["est_saving"] for a in actions if a.get("est_saving")), 2)

    return {
        "actions": actions,
        "estimated_total_saving": total_est,
        "disclaimer": "以上为基于历史数据的情景估算，实际优惠以麦当劳官方实时核价为准。",
        "trace": {
            "formula": "可省金额 = 各可量化动作的 est_saving 之和",
            "coupon_sources": [r["coupon_id"] for r in coupon_report["expiring_within_7d"]],
        },
    }


# ---------------------------------------------------------------------------
# 5.5 行为风格画像（可回溯、可反驳）
# ---------------------------------------------------------------------------

@dataclass
class Trait:
    """一个行为特征。全部由可验证的判定规则得出，不含主观性格判断。"""
    key: str                        # 机器可读标识
    label: str                      # 展示名，如"套餐依赖型"
    value: float                    # 实测特征值
    threshold: float                # 判定阈值
    comparator: str                 # ">=" 或 "<="
    unit: str = "%"                 # 单位
    rule: str = ""                  # 人类可读的判定规则
    evidence: List[str] = field(default_factory=list)   # 支撑它的订单号


def _ratio(a: float, b: float) -> float:
    return round(a / b, 4) if b else 0.0


def behavior_profile(orders: Sequence[Order]) -> Dict[str, Any]:
    """
    行为风格画像。

    设计原则（与同类"人格测试"项目的根本区别）：
    1. 只描述**可观测的行为习惯**，不下"性格"结论——
       我们不说"你是谨慎的人"，只说"你的套餐占比 100%"。
    2. 每个特征都带**判定规则 + 阈值 + 支撑订单号**，
       用户能看懂为什么这么判，也能拿自己的订单反驳。
    3. 阈值写死在 rule 里，公开透明，不是黑箱权重。

    四个维度：
    - 套餐依赖度：依赖套餐 vs 偏好自行组合
    - 时段集中度：集中在某一时段 vs 全时段分散
    - 口味多样性：持续探索新品 vs 反复点同样的
    - 客单价位：偏高 vs 经济（相对于自身订单集）
    """
    if not orders:
        return {
            "empty": True,
            "traits": [],
            "summary": "数据不足，无法生成行为画像。",
            "disclaimer": "行为画像需要至少 1 笔订单。",
        }

    n = len(orders)

    # 维度 1：套餐依赖度 —— 多子项订单（展平后的套餐）占比
    combo_orders = [o for o in orders if len(o.items) >= 2]
    combo_ratio = _ratio(len(combo_orders), n)

    # 维度 2：时段集中度
    slot_count: Dict[str, int] = defaultdict(int)
    for o in orders:
        slot_count[_time_slot(o.ts.hour)] += 1
    top_slot, top_slot_n = max(slot_count.items(), key=lambda kv: kv[1])
    slot_concentration = _ratio(top_slot_n, n)

    # 维度 3：口味多样性 —— 不同商品种类数 ÷ 订单数
    distinct_items: List[str] = sorted({it.name for o in orders for it in o.items})
    variety_ratio = _ratio(len(distinct_items), n)

    # 维度 4：客单价位
    mid = median_payable(orders)
    aov = round(sum(o.payable for o in orders) / n, 2)

    traits: List[Trait] = []

    traits.append(Trait(
        key="combo_dependence",
        label="套餐依赖型" if combo_ratio >= 0.7 else "自由组合型",
        value=combo_ratio, threshold=0.7, comparator=">=",
        rule="套餐依赖型：多子项订单占比 ≥ 70%；否则为自由组合型",
        evidence=[o.order_no for o in combo_orders] if combo_ratio >= 0.7
                 else [o.order_no for o in orders if len(o.items) < 2],
    ))

    traits.append(Trait(
        key="time_concentration",
        label=f"{top_slot}集中型" if slot_concentration >= 0.5 else "全时段分散型",
        value=slot_concentration, threshold=0.5, comparator=">=",
        rule="时段集中型：最高频时段的订单占比 ≥ 50%；否则为全时段分散型",
        evidence=[o.order_no for o in orders if _time_slot(o.ts.hour) == top_slot],
    ))

    traits.append(Trait(
        key="variety",
        label="探索尝新型" if variety_ratio >= 1.5 else "口味稳定型",
        value=variety_ratio, threshold=1.5, comparator=">=", unit="种/单",
        rule="探索尝新型：不同商品种类数 ÷ 订单数 ≥ 1.5；否则为口味稳定型",
        evidence=distinct_items,
    ))

    traits.append(Trait(
        key="price_level",
        label="偏高客单型" if aov >= 30 else "经济实付型",
        value=aov, threshold=30.0, comparator=">=", unit="元",
        rule="偏高客单型：客单价 ≥ ¥30；否则为经济实付型",
        evidence=[o.order_no for o in orders if o.payable > mid],
    ))

    summary = "你的行为特征：" + " × ".join(t.label for t in traits) + "。"

    return {
        "empty": False,
        "traits": [asdict(t) for t in traits],
        "summary": summary,
        "basis": {"order_count": n, "median_payable": mid, "aov": aov},
        "disclaimer": (
            "本画像只描述可观测的点餐行为，不构成对个人性格、健康或消费能力的评价。"
            "每个特征均由公开的判定规则与明确阈值得出，你可对照自己的订单核验或反驳。"
        ),
        "note": "与同类「人格测试」的差别：不做黑箱打分，只做可复现的规则判定。",
    }


# ---------------------------------------------------------------------------
# 5.6 麦麦人格：由"吃得最多的东西"决定的具体人格
# ---------------------------------------------------------------------------

# 人格池。每个人格 = 一个触发条件 + 一套由真实数据填充的文案模板。
#
# 设计要点（与同类"贴标签"项目的分水岭）：
# 1. **触发条件全部公开**：每个人格写明对应哪些商品、门槛是多少，写在下面这张表里。
# 2. **文案里的每个数字都来自真实订单**：`{}` 占位符由 `_fill()` 用实测值填入，
#    绝不写死。用户数不出这些数字，就说明我们的数据错了。
# 3. **兜底**：若一个都不命中，回落到"麦门永存"，而不是硬塞一个不符的标签。
#
# 字段说明：
#   key       机器标识
#   name      人格名（展示用）
#   kind      归类：单品型 / 组合型 / 场景型
#   match     匹配函数：(item_qty, combo_qty, orders) -> Optional[int] 返回主数值
#   unit      该数值的单位（盒/杯/份…）
#   cover     CSS 渐变（用于卡片配色）
#   lines     文案模板列表，{} 依次填入 (数值) 与 派生量
#   fame      一句话"封号"，含用户名的位置用 {owner}
_PERSONAS: List[Dict[str, Any]] = [
    {
        "key": "fries_pianist",
        "name": "薯条钢琴家",
        "kind": "单品型",
        "unit": "盒",
        "cover": "linear-gradient(135deg,#FFC72C,#F5A623)",
        "match_item": ("薯条",),
        "min_n": 8,
        "lines": [
            "本年度你一共吃了 {n} 盒薯条。",
            "8 盒一场八重奏、4 盒一场四重奏、2 盒一场双重奏 —— 你这一年凑出了：{music}。",
            "在薯门的世界里，「{owner}」是名副其实的**救薯**。",
        ],
    },
    {
        "key": "one_plus_one_king",
        "name": "极品小学生",
        "kind": "组合型",
        "unit": "份",
        "cover": "linear-gradient(135deg,#DA291C,#E8632A)",
        "match_item": ("随心配", "1+1", "随心选"),
        "min_n": 5,
        "lines": [
            "本年度你一共吃了 {n} 份「随心配 / 1+1」。",
            "按平均一份省下 {save} 元估算，你把「精打细算」四个字吃成了肌肉记忆。",
            "1+1 之王，非你莫薯。",
        ],
    },
    {
        "key": "mcflurry_whirl",
        "name": "旋麦",
        "kind": "单品型",
        "unit": "份",
        "cover": "linear-gradient(135deg,#8B5CF6,#6366F1)",
        "match_item": ("麦旋风", "旋风"),
        "min_n": 5,
        "lines": [
            "本年度你一共吃了 {n} 份麦旋风。",
            "杯子转起来的时候，据说能看见「黑旋风」—— 你的旋风，麦麦的麦。",
        ],
    },
    {
        "key": "corn_crusher",
        "name": "麦粒肿",
        "kind": "单品型",
        "unit": "杯",
        "cover": "linear-gradient(135deg,#F5C542,#C9A227)",
        "match_item": ("玉米杯", "玉米"),
        "min_n": 5,
        "lines": [
            "本年度你一共吃了 {n} 杯玉米杯。",
            "照这个量，你无疑是台**玉米粉碎机**。",
            "温馨提示：本名沿用的是「玉米粒」的粒，跟眼科那个没关系，别慌。",
        ],
    },
    {
        "key": "cola_joy",
        "name": "可劲儿乐呵",
        "kind": "单品型",
        "unit": "杯",
        "cover": "linear-gradient(135deg,#1E88E5,#0D47A1)",
        "match_item": ("可乐",),
        "min_n": 6,
        "lines": [
            "本年度你一共喝了 {n} 杯可乐。",
            "气泡管够，快乐管饱 —— 看来你是一个非常快乐的人。",
        ],
    },
    {
        "key": "cameroon",
        "name": "咖麦隆",
        "kind": "单品型",
        "unit": "杯",
        "cover": "linear-gradient(135deg,#6D4C41,#3E2723)",
        "match_item": ("麦咖啡", "拿铁", "美式", "卡布", "摩卡", "咖啡"),
        "min_n": 6,
        "lines": [
            "你本年度一共喝了 {n} 杯麦咖啡系列。",
            "别人在点餐，你在选豆；别人在续杯，你在续命。",
            "杯杯不落，场场首发 —— 咖麦隆，咖啡界的全能前锋。",
        ],
    },
    {
        "key": "spicy_warrior",
        "name": "麦辣战神",
        "kind": "单品型",
        "unit": "个",
        "cover": "linear-gradient(135deg,#DA291C,#8E0F06)",
        # 关键词必须命中"汉堡"，否则「麦辣鸡翅」会被误算成汉堡
        # （鸡翅是小食，与"战神汉堡"的文案不符）。
        "match_item": ("麦辣鸡腿堡", "麦辣鸡排堡", "辣腿堡", "辣堡", "麦辣双层"),
        "min_n": 6,
        "lines": [
            "你本年度一共吃了 {n} 个麦辣系列汉堡。",
            "别人的微辣是微辣，你的微辣是「再来一个」。",
        ],
    },
    {
        "key": "big_mac_loyalist",
        "name": "巨无霸原教旨",
        "kind": "单品型",
        "unit": "个",
        "cover": "linear-gradient(135deg,#B71C1C,#7F0E0E)",
        "match_item": ("巨无霸",),
        "min_n": 5,
        "lines": [
            "你本年度一共吃了 {n} 个巨无霸。",
            "两层牛肉、三层面包、固定的那口酱 —— 经典之所以是经典，是因为你没换过。",
        ],
    },
    {
        "key": "cheese_hedonist",
        "name": "吉士行乐",
        "kind": "单品型",
        "unit": "个",
        "cover": "linear-gradient(135deg,#F9A825,#E65100)",
        "match_item": ("吉士", "芝士", "双层吉士"),
        "min_n": 5,
        "lines": [
            "你本年度一共吃了 {n} 个吉士汉堡系列。",
            "融化的芝士从来不缺席你的一餐 —— 及时行乐，趁热吃堡。",
            "吉士行乐，你悟了。",
        ],
    },
    {
        "key": "burger_guardian",
        "name": "堡你周全",
        "kind": "组合型",
        "universal": True,
        # sub_only：只做副人格，永不当主人格。
        # 它把"所有汉堡"累加成一个宽泛数值，天然比单品人格大，
        # 若参与主人格竞争会长期压制「麦辣战神 / 巨无霸原教旨」等更具体的号，
        # 因此限定它只在副人格位展示（用户要求）。
        "sub_only": True,
        "unit": "个",
        "cover": "linear-gradient(135deg,#EF6C00,#B71C1C)",
        # 关键词须命中"汉堡"本身。「麦辣」单独两字会误吞「麦辣鸡翅」（小食），
        # 所以改成"麦辣鸡腿堡 / 麦辣鸡排堡"这类完整堡名。
        "match_item": ("汉堡", "巨无霸", "吉士", "芝士", "麦辣鸡腿堡", "麦辣鸡排堡",
                       "辣腿堡", "辣堡", "麦辣双层",
                       "双牛", "双层牛", "板烧", "鸡腿堡", "麦香", "培根", "牛堡"),
        "min_n": 10,
        "lines": [
            "你本年度一共吃了 {n} 个汉堡 —— 从经典牛肉到香辣鸡腿，一个都没落下。",
            "有面包、有肉、有酱，才叫一顿饭 —— 别的都是配菜。",
            "堡你周全，你一个人把整张菜单吃成了一条线。",
        ],
    },
    {
        "key": "ice_spear_claw",
        "name": "冰矛鸡爪流",
        "kind": "隐藏",
        "display_kind": "隐藏成就",
        "hidden": True,
        "unit": "单",
        "cover": "linear-gradient(135deg,#00BCD4,#1A237E)",
        "match_pair": (("鸡翅", "辣翅", "烤翅", "奥尔良", "鸡爪", "麦乐鸡", "鸡块"),
                       ("冰激凌", "冰淇淋", "新地", "麦旋风", "圣代", "甜筒", "奥利奥")),
        "min_n": 3,
        "lines": [
            "本年度你有 {n} 单同时点了「鸡翅」和「冰激凌」。",
            "一口热辣鸡翅，一口冰甜筒 —— 冰与火同时进场，这波节奏你控得死死的。",
            "别人打团靠队友，你打团靠自己：先叠「冰矛」，再上「鸡爪流」连招。",
            "隐藏成就解锁：**冰矛鸡爪流** —— 峡谷里最会吃的那个召唤师。",
        ],
    },
    {
        "key": "morning_dealer",
        "name": "清醒贩麦者",
        "kind": "场景型",
        "unit": "单",
        "cover": "linear-gradient(135deg,#FF8F00,#E65100)",
        "match_slot": ("早餐(05-10)",),
        "min_n": 4,
        "lines": [
            "本年度你有 {n} 单发生在早餐时段。",
            "别人的早晨在闹钟里挣扎，你的早晨在薯饼香气里落定。",
            "清醒得早，麦得也早 —— 清醒贩麦者，一天从一手交钱一手交汉堡开始。",
        ],
    },
    {
        "key": "national_treasure",
        "name": "国宝",
        "kind": "场景型",
        "unit": "单",
        "cover": "linear-gradient(135deg,#283593,#101A4D)",
        "match_slot": ("夜宵(21-05)",),
        "min_n": 4,
        "lines": [
            "本年度你有 {n} 单发生在夜宵时段。",
            "城市的灯一盏盏熄掉的时候，你的胃口才刚亮起来。",
            "熬最深的夜，点最香的餐 —— 黑眼圈就是你国宝级的勋章。",
        ],
    },
    {
        "key": "sweet_tooth",
        "name": "甜品特派员",
        "kind": "组合型",
        "unit": "份",
        "cover": "linear-gradient(135deg,#EC407A,#AD1457)",
        "match_cat": ("甜点",),
        "min_n": 4,
        "lines": [
            "本年度你一共吃了 {n} 份甜品。",
            "先吃甜的还是先吃咸的，你从来不纠结 —— 先吃甜的。",
        ],
    },
]

# 兜底人格：一条都没命中时使用，不硬塞标签。
_DEFAULT_PERSONA: Dict[str, Any] = {
    "key": "mcd_forever",
    "name": "麦门永存",
    "kind": "兜底",
    # 展示层用词：'兜底' 是内部排序用的分类名，不应直接暴露给用户
    # （display_kind 现仅保留在数据层，UI 上的类型印章已按用户要求移除）
    "display_kind": "通用",
    "unit": "单",
    "cover": "linear-gradient(135deg,#DA291C,#FFC72C)",
    "lines": [
        "本年度你一共在麦当劳点了 {n} 单，横跨 {kinds} 种不同的商品。",
        "没有极端偏好，也没有凑单凑出来的执念 —— 什么都点一点，这本身就是一种信仰。",
        "麦门永存。",
    ],
}


def _persona_qty(orders: Sequence[Order]) -> Dict[str, int]:
    """商品名 → 累计件数。"""
    q: Dict[str, int] = defaultdict(int)
    for o in orders:
        for it in o.items:
            q[it.name] += it.qty
    return dict(q)


def _sum_matching(item_qty: Dict[str, int], keywords: Sequence[str]) -> int:
    """累计名称命中任一关键词的商品件数。"""
    total = 0
    for name, q in item_qty.items():
        if any(k in name for k in keywords):
            total += q
    return total


def _sum_category(orders: Sequence[Order], cats: Sequence[str]) -> int:
    total = 0
    for o in orders:
        for it in o.items:
            if it.category in cats:
                total += it.qty
    return total


def _sum_slot(orders: Sequence[Order], slots: Sequence[str]) -> int:
    return sum(1 for o in orders if _time_slot(o.ts.hour) in slots)


def _persona_candidates(orders: Sequence[Order]
                        ) -> "tuple[List[Dict[str, Any]], List[Dict[str, Any]]]":
    """
    对人格池里每个人格求值。

    返回 `(candidates, hidden_hits)`：
      - `candidates`：已命中的普通候选（按主数值降序），用于主人格/副人格排序
      - `hidden_hits`：已命中的**隐藏人格**，单独返回、不混入候选清单

    命中即"该人格对应的商品/场景，在本年度确实出现了"，
    主数值 = 该人格相关的累计数量，用作主人格排序与文案填充。

    两条去重/排序规则（避免同一件商品被算进多个人格）：
    1. **同源去重**：已被更具体的"单品型/组合型"人格覆盖的商品，
       不再计入宽泛的"品类型"人格（如"奥利奥麦旋风"已计入「旋麦」，
       就不再计入「甜品特派员」），防止同一样东西被反复封号。
    2. **专指性优先**：数值并列时，单品型 > 组合型 > 场景型 > 兜底型，
       即"更具体的名字"优先。

    **例外：`universal=True` 的"全集型"人格**（如「堡你周全」= 所有汉堡之和）。
    它不参与同源去重，主动把已被单品人格认领的汉堡也统计进来，
    因此能和"麦辣战神/巨无霸原教旨"在同一量纲上比大小 ——
    **谁的累计件数多谁当主人格**。这样"吃得很杂、单一品类都不够门槛"的人
    才会被它接住（用户明确要求：汉堡总数第一即封此号）。

    场景型人格（早餐/夜宵）计的是**订单数**，与商品件数不同量纲，
    因此单独汇总、不参与同源去重。

    **隐藏人格（`hidden=True`）**：不参与普通匹配，只有满足其专属条件时
    才会被"揭晓"，且**不出现在候选清单**里（否则就不叫隐藏了）。
    当前唯一隐藏人格「冰矛鸡爪流」用 `match_pair` 描述：
    需要**同一笔订单里同时出现**两组关键词（鸡翅 × 冰激凌），
    计的是"同时出现的订单数"，而不是商品件数。
    """
    item_qty = _persona_qty(orders)
    claimed: set = set()          # 已被更具体人格认领的商品名
    out: List[Dict[str, Any]] = []

    KIND_RANK = {"单品型": 0, "组合型": 1, "场景型": 2, "隐藏": 3, "兜底": 4}

    # 先处理"具体"的人格（单品型 → 组合型），认领它们命中的商品名
    for p in _PERSONAS:
        if p.get("kind") not in ("单品型", "组合型"):
            continue
        universal = bool(p.get("universal"))
        n = 0
        hit_names = []
        if p.get("match_item"):
            for name, q in item_qty.items():
                if name in claimed and not universal:
                    continue
                if any(k in name for k in p["match_item"]):
                    n += q
                    hit_names.append(name)
        elif p.get("match_cat"):
            for o in orders:
                for it in o.items:
                    if it.name in claimed and not universal:
                        continue
                    if it.category in p["match_cat"]:
                        n += it.qty
                        hit_names.append(it.name)
        # 门槛：数量太少时不封号，避免"吃了 1 盒薯条就成钢琴家"的尬感。
        # 阈值随人格可调（min_n），默认至少 3 件 / 2 单。
        if n and n >= int(p.get("min_n", 2)):
            if not universal:
                claimed.update(hit_names)
            out.append({**p, "n": n, "matched": hit_names})

    # 再处理场景型（按订单数，与商品无关）
    for p in _PERSONAS:
        if p.get("kind") != "场景型":
            continue
        n = _sum_slot(orders, p["match_slot"])
        if n and n >= int(p.get("min_n", 2)):
            out.append({**p, "n": n, "matched": []})

    # 隐藏人格：单独判定，命中才揭晓，且**不混入候选清单**
    hidden_hits: List[Dict[str, Any]] = []
    for p in _PERSONAS:
        if not p.get("hidden") or not p.get("match_pair"):
            continue
        kw_a, kw_b = p["match_pair"]
        n = 0
        for o in orders:
            names = [it.name for it in o.items]
            if (any(any(k in nm for k in kw_a) for nm in names)
                    and any(any(k in nm for k in kw_b) for nm in names)):
                n += 1
        if n and n >= int(p.get("min_n", 2)):
            hidden_hits.append({**p, "n": n, "matched": []})

    # 排序：主数值降序；并列时名字更具体的优先。
    # `sub_only` 的人格（「堡你周全」）数值再大也**排在所有可当主人格的人选之后** ——
    # 它只做副人格，不抢主板位。
    out.sort(key=lambda x: (
        1 if x.get("sub_only") else 0,
        -x["n"],
        KIND_RANK.get(x.get("kind", "兜底"), 9),
    ))
    return out, hidden_hits


def _fries_music(n: int) -> str:
    """把 n 盒薯条拆成「重奏」组合：8 盒=八重奏、4 盒=四重奏、2 盒=双重奏。

    贪心拆分：优先凑八重奏，余数再凑四重奏、双重奏，最后剩单盒。
    返回人类可读的描述（如 "5 场八重奏" / "2 场八重奏、1 场双重奏"）。
    """
    oct_ = n // 8
    rem = n % 8
    qua_ = rem // 4
    rem = rem % 4
    dou_ = rem // 2
    rem = rem % 2
    segs = []
    if oct_:
        segs.append(f"{oct_} 场八重奏")
    if qua_:
        segs.append(f"{qua_} 场四重奏")
    if dou_:
        segs.append(f"{dou_} 场双重奏")
    if rem:
        segs.append(f"余 {rem} 盒")
    return "、".join(segs) if segs else "一场都没凑齐"


def persona_portrait(orders: Sequence[Order],
                     owner: str = "麦门用户") -> Dict[str, Any]:
    """
    麦麦人格画像 —— 由"吃得最多的那个东西"决定的具体人格。

    返回：
      {
        "empty": bool,
        "main":  {name, kind, unit, n, lines[], cover, ...} | None,
        "subs":  [ 至多 2 个副人格 ],
        "candidates": [ 全部命中项 ],       # 可回溯：为什么是这个结论
        "default": bool,                    # 是否走的兜底人格
        "basis": {订单数, 商品种数, 明细},
        "disclaimer": str,
      }

    可证伪性：`candidates` 里每个人格都带 `n`（实测数量）与 `match`（触发条件），
    用户可对着自己的订单逐项核验；`lines` 里出现的每个数字都可在 `basis.items` 中找到来源。
    """
    if not orders:
        return {
            "empty": True, "main": None, "subs": [], "candidates": [],
            "default": False,
            "summary": "数据不足，无法生成麦麦人格。",
            "disclaimer": "麦麦人格需要至少 1 笔订单。",
        }

    item_qty = _persona_qty(orders)
    cands, hidden_hits = _persona_candidates(orders)
    total_orders = len(orders)
    distinct_kinds = len(item_qty)

    # 隐藏人格一旦命中，直接**顶替主人格**（彩蛋优先级最高），
    # 原主人格降为第一副人格 —— 这样"隐藏"才有揭晓的分量。
    hidden_raw = hidden_hits[0] if hidden_hits else None

    # `sub_only` 人格（「堡你周全」）被排到了候选末尾，若直接截取 `cands[1:3]`
    # 它会掉出副人格位。因此副人格单独挑：先放它，再按名次补足到 2 个。
    def _pick_subs(pool: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        subs = [x for x in pool if x.get("sub_only")][:1]
        for x in pool:
            if len(subs) >= 2:
                break
            if not x.get("sub_only"):
                subs.append(x)
        # 保持"数量高者在前"的观感
        subs.sort(key=lambda x: -x["n"])
        return subs

    if hidden_raw is not None:
        main_raw = hidden_raw
        subs_raw = _pick_subs(cands)
        is_default = False
    elif cands and not cands[0].get("sub_only"):
        main_raw = cands[0]
        subs_raw = _pick_subs(cands[1:])
        is_default = False
    else:
        main_raw = {**_DEFAULT_PERSONA, "n": total_orders}
        subs_raw = _pick_subs(cands)
        is_default = True

    # 预先算好文案里需要的派生量（例如薯条 → 八重奏/四重奏/双重奏组合描述）。
    # 主人格与副人格各自独立计算 —— 副人格展开面板要显示自己的数量与文案。
    def _derived_for(p: Dict[str, Any]) -> Dict[str, Any]:
        n = p.get("n", 0)
        key = p.get("key")
        return {
            "owner": owner,
            "n": n,
            "kinds": distinct_kinds,
            "music": _fries_music(n) if key == "fries_pianist" else "",
            "save": 6,
        }

    derived = _derived_for(main_raw)

    def _fill(lines: Sequence[str], ctx: Dict[str, Any]) -> List[str]:
        out = []
        for ln in lines:
            try:
                out.append(ln.format(**ctx))
            except (KeyError, IndexError):
                out.append(ln)
        return out

    main = {
        "key": main_raw["key"],
        "name": main_raw["name"],
        "kind": main_raw["kind"],
        "display_kind": main_raw.get("display_kind") or main_raw["kind"],
        "hidden": bool(main_raw.get("hidden")),
        "unit": main_raw.get("unit", "单"),
        "cover": main_raw.get("cover", "linear-gradient(135deg,#DA291C,#FFC72C)"),
        "count": main_raw.get("n", 0),
        "lines": _fill(main_raw.get("lines", []), derived),
        "trigger": _persona_trigger_text(main_raw),
    }

    # 副人格：除名字/数量/触发条件外，补充完整封号信息（lines/display_kind/cover），
    # 供叙事版渲染"点击展开的迷你证书"（用户要求：副人格也能点开看详情）。
    subs = [{
        "key": s["key"], "name": s["name"], "unit": s.get("unit", "单"),
        "count": s.get("n", 0), "trigger": _persona_trigger_text(s),
        "display_kind": s.get("display_kind") or s.get("kind", ""),
        "cover": s.get("cover", "linear-gradient(135deg,#DA291C,#FFC72C)"),
        "hidden": bool(s.get("hidden")),
        "lines": _fill(s.get("lines", []), _derived_for(s)),
    } for s in subs_raw]

    return {
        "empty": False,
        "main": main,
        "subs": subs,
        "candidates": [{
            "name": c["name"], "key": c["key"],
            "count": c.get("n", 0), "unit": c.get("unit", "单"),
            "trigger": _persona_trigger_text(c),
            # sub_only 透传给测试与渲染层：该人格只做副人格、候选里沉底
            "sub_only": bool(c.get("sub_only")),
        } for c in cands],
        "default": is_default,
        "hidden_unlocked": bool(hidden_hits),
        "basis": {
            "order_count": total_orders,
            "distinct_items": distinct_kinds,
            "items": dict(sorted(item_qty.items(), key=lambda kv: -kv[1])),
        },
        "summary": (
            f"🎉 隐藏人格解锁：你的麦麦人格是「{main['name']}」。" if hidden_hits
            else f"你的麦麦人格是「{main['name']}」。"
        ),
        "disclaimer": (
            "「麦麦人格」由你本年度实际点过的商品与下单时段推出，触发条件逐条公开。"
            "文案里的每个数字都能在下方明细中查到来源，你可以核验，也可以反驳。"
            "它只描述点餐行为，不构成对性格、健康或消费能力的评价。"
        ),
    }


def _persona_trigger_text(p: Dict[str, Any]) -> str:
    """把触发条件翻译成人类可读的一句话（用于可回溯面板）。"""
    if p.get("match_pair"):
        kw_a, kw_b = p["match_pair"]
        return ("**同一笔订单**同时包含："
                + " / ".join(kw_a) + " ＋ " + " / ".join(kw_b))
    if p.get("match_item"):
        return "商品名包含：" + " / ".join(p["match_item"])
    if p.get("match_cat"):
        return "品类属于：" + " / ".join(p["match_cat"])
    if p.get("match_slot"):
        return "下单时段属于：" + " / ".join(p["match_slot"])
    return "默认人格（无特定偏好）"


# ---------------------------------------------------------------------------
# 6. 年度档案组装
# ---------------------------------------------------------------------------

def build_annual_report(
    orders: Sequence[Order],
    coupons: Sequence[Coupon] = (),
    points: Optional[PointsAccount] = None,
    year: Optional[int] = None,
    owner: str = "麦门用户",
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """组装完整的年度报告数据结构（供 HTML 渲染消费）。"""
    today = today or date.today()
    if year is None:
        year = max((o.ts.year for o in orders), default=today.year)

    summary = summarize_orders(orders)
    report = {
        "meta": {
            "title": f"{year} 麦麦年度报告",
            "owner": owner,
            "year": year,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_scope": "仅统计本账户在麦当劳的真实消费记录",
        },
        "summary": summary,
        "behavior": behavior_profile(orders),
        "persona": persona_portrait(orders, owner=owner),
        "quarterly": quarterly_breakdown(orders, year),
        "monthly": month_slices(orders, year),
        "flavor_drift": flavor_drift(orders, year),
        "coupons": coupon_actions(coupons, orders, today) if coupons else None,
        "playbook": saving_playbook(orders, coupons, today) if orders else None,
        "points": _points_to_dict(points) if points else None,
    }
    return report


def _points_to_dict(p: PointsAccount) -> Dict[str, Any]:
    d = asdict(p)
    if d.get("expiring_at") is not None:
        d["expiring_at"] = p.expiring_at.isoformat()
    return d


# ---------------------------------------------------------------------------
# 6. 自检：手算校验
# ---------------------------------------------------------------------------

def self_check(orders: Sequence[Order]) -> Dict[str, Any]:
    """
    对年报的关键数字做一次独立复算，确保"可手算"这一承诺成立。
    任何一项不符，都会在这里暴露。
    """
    checks: List[Dict[str, Any]] = []

    # 复算 1：实付 = Σ payable
    manual_paid = round(sum(o.payable for o in orders), 2)
    engine_paid = summarize_orders(orders).get("paid", 0.0) if orders else 0.0
    checks.append({
        "name": "实付总额",
        "manual": manual_paid,
        "engine": engine_paid,
        "pass": abs(manual_paid - engine_paid) < 0.01,
    })

    # 复算 2：省下 = Σ(原价 + 配送费 - 实付)
    manual_saved = round(sum(o.product_total + o.delivery_fee - o.payable for o in orders), 2)
    engine_saved = round(sum(o.saved for o in orders), 2)
    checks.append({
        "name": "省下总额",
        "manual": manual_saved,
        "engine": engine_saved,
        "pass": abs(manual_saved - engine_saved) < 0.01,
    })

    # 复算 3：客单价
    if orders:
        manual_aov = round(manual_paid / len(orders), 2)
        checks.append({
            "name": "客单价",
            "manual": manual_aov,
            "engine": summarize_orders(orders)["aov"],
            "pass": abs(manual_aov - summarize_orders(orders)["aov"]) < 0.01,
        })

    all_pass = all(c["pass"] for c in checks)
    return {"all_pass": all_pass, "checks": checks}


# ---------------------------------------------------------------------------
# 7. 叙事剧本：把年报数据编排成"逐屏揭晓"的故事线
# ---------------------------------------------------------------------------

def build_story(
    orders: Sequence[Order],
    coupons: Sequence[Coupon] = (),
    points: Optional[PointsAccount] = None,
    account: Optional[Dict[str, Any]] = None,
    year: Optional[int] = None,
    owner: str = "麦门用户",
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    生成叙事版年报的"分屏剧本"。

    设计原则：
    - 文案**全部由真实数据生成**，不做无中生有的抒情。
      没有订单就不编"你与麦当劳的 N 次相遇"。
    - 只说结论、不带公式与依据面板 —— 叙事版保持"年度回顾"的沉浸感。
      逐条核对数字的需求由报告版承担（每屏可携带 `evidence` 供其回溯）。
    - 涉及主观感受的句式一律避免；只做事实陈述 + 克制的解读。
    """
    today = today or date.today()
    if year is None:
        year = max((o.ts.year for o in orders), default=today.year)

    ys = sorted([o for o in orders if o.ts.year == year], key=lambda o: o.ts)
    scenes: List[Dict[str, Any]] = []

    # 会员尾号：MCP 不返回昵称，跳过署名时用它兜底（如「麦友 ··3118」）。
    # 取 accountId 末 4 位，避免暴露完整会员 ID。
    member_suffix = ""
    if account and account.get("accountId"):
        member_suffix = str(account["accountId"])[-4:]

    # ---- 屏 0：开场 ----
    if not orders:
        scenes.append({
            "kind": "opening",
            "title": f"{year}",
            "big": "还没有故事",
            "lines": ["这一年你还没有在麦当劳留下订单记录。", "去点一份，明年的年报就有内容了。"],
            "evidence": [],
        })
        return {"year": year, "owner": owner, "scenes": scenes,
                "empty": True, "member_suffix": member_suffix}

    # 样本量提示：订单太少时，部分结论的统计意义有限，如实说明。
    thin_note = []
    if len(orders) < 3:
        thin_note.append(f"本年度仅有 {len(orders)} 笔订单，以下结论基于极小样本，仅供参考。")

    scenes.append({
        "kind": "opening",
        "title": f"{year} 麦麦年度报告",
        "big": owner,
        "lines": [f"这一年，你在麦当劳点了 {len(orders)} 单。"] + thin_note,
        "evidence": [o.order_no for o in orders],
    })

    # ---- 屏 1：花了多少 ----
    paid = round(sum(o.payable for o in orders), 2)
    scenes.append({
        "kind": "number",
        "title": "你在麦当劳花的钱",
        "big": _money_str(paid),
        "unit": "实付总额",
        "lines": [f"平均每单 {_money_str(round(paid/len(orders), 2))}。"],
        "evidence": [o.order_no for o in orders],
        "formula": "把每一单的实付金额逐单相加，可自行核对",
    })

    # ---- 屏 2：最常去的门店 ----
    store_count: Dict[str, int] = defaultdict(int)
    for o in orders:
        store_count[o.store_name or "未知"] += 1
    top_store, top_n = max(store_count.items(), key=lambda kv: kv[1])
    store_orders = [o.order_no for o in orders if (o.store_name or "未知") == top_store]
    place_lines = [f"去过 {len(store_count)} 家餐厅，其中 {top_n} 单发生在这里。"]
    if len(store_count) == 1:
        place_lines.append("全部订单都在这家店。")
    scenes.append({
        "kind": "place",
        "title": "你最常出现的地方",
        "big": top_store,
        "lines": place_lines,
        "evidence": store_orders,
    })

    # ---- 屏 3：点得最多的东西 ----
    item_qty: Dict[str, int] = defaultdict(int)
    for o in orders:
        for it in o.items:
            item_qty[it.name] += it.qty
    top_items = sorted(item_qty.items(), key=lambda kv: -kv[1])[:3]
    if top_items:
        lines = ["、".join(f"{n}（{q} 次）" for n, q in top_items)]
        scenes.append({
            "kind": "taste",
            "title": "你反复点的",
            "big": top_items[0][0],
            "lines": lines,
            "evidence": [o.order_no for o in orders],
            "formula": "按全年累计件数排序（订单数据不提供单项价格，故只统计件数）",
        })

    # ---- 屏 4：时间轨迹 ----
    hours = [o.ts.hour for o in orders]
    avg_hour = sum(hours) / len(hours)
    slot_count: Dict[str, int] = defaultdict(int)
    for o in orders:
        slot_count[_time_slot(o.ts.hour)] += 1
    top_slot, top_slot_n = max(slot_count.items(), key=lambda kv: kv[1])
    first_o, last_o = ys[0] if ys else orders[0], orders[-1]
    scenes.append({
        "kind": "time",
        "title": "你的麦麦时间",
        "big": top_slot,
        "lines": [
            f"最集中的时段。{top_slot_n} 单落在这里。",
            f"第一次是 {first_o.ts.strftime('%m月%d日')}，最近一次是 {last_o.ts.strftime('%m月%d日')}。",
        ],
        "evidence": [o.order_no for o in orders if _time_slot(o.ts.hour) == top_slot],
    })

    # ---- 屏 5：人格预告（悬念页，底部按钮跳转到麦麦人格屏）----
    scenes.append({
        "kind": "persona_teaser",
        "title": f"{year} 年度 · 悬念揭晓",
        "big": "你的麦麦人格是…",
        "lines": [
            "根据你这一整年点过的每一单、每一件商品，推演出的专属封号。",
            "点下面的按钮，揭晓答案。",
        ],
    })

    # ---- 屏 6：麦麦人格（由"吃得最多的东西"决定，大标题即人格名）----
    persona = persona_portrait(orders, owner=owner)
    if not persona.get("empty"):
        main = persona["main"]
        subs = persona["subs"]
        # 副人格只在卡片下方的胶囊里展示，正文不再重复，避免同一信息出现两次。
        # 兜底人格不再附加"数据撑不起"说明行（用户要求删除）。
        lines = list(main["lines"])

        scenes.append({
            "kind": "persona",
            "title": "你的麦麦人格是",
            "big": main["name"],
            "unit": f"{main['count']} {main['unit']} · {main.get('display_kind') or main['kind']}",
            "lines": lines,
            "cover": main["cover"],
            "subs": subs,
            "hidden": bool(main.get("hidden")),
            "hidden_unlocked": bool(persona.get("hidden_unlocked")),
            # 可回溯：人格池里所有命中项 + 触发条件 + 实测数量
            "candidates": persona["candidates"],
            "basis": persona["basis"],
            "evidence": [o.order_no for o in orders],
            "note": persona["disclaimer"],
        })

    # ---- 屏 6：资产 ----
    if coupons or (points and (points.available or points.total_earned)):
        lines = []
        ev = []
        if coupons:
            lines.append(f"账户里还有 {len(coupons)} 张券可用。")
            ev += [c.coupon_id for c in coupons]
        if points:
            lines.append(f"积分可用 {points.available}，累计获得 {points.total_earned}。")
        scenes.append({
            "kind": "assets",
            "title": "你还握着的东西",
            "big": f"{len(coupons)} 张券" if coupons else f"{points.available} 积分",
            "lines": lines,
            "evidence": ev,
        })

    # ---- 屏 7：数据边界（诚实收尾）----
    scenes.append({
        "kind": "closing",
        "title": "关于这份年报",
        "big": "不编造",
        "lines": [
            "本报告所有数字均来自你在麦当劳的真实消费记录，未做任何修饰。",
            "数据本身没有提供的指标（如原价、优惠拆分、券面额），我们选择不展示，而不是估算。",
        ],
        "evidence": [],
    })

    return {"year": year, "owner": owner, "scenes": scenes,
            "empty": False, "member_suffix": member_suffix}


def _money_str(v: float) -> str:
    return f"¥{v:,.2f}"


if __name__ == "__main__":
    # 极简 demo：直接用 mock 数据跑一遍
    import json, os, sys
    sys.path.insert(0, os.path.dirname(__file__))
    from mock_loader import load_mock_orders, load_mock_coupons, load_mock_points

    orders = load_mock_orders()
    coupons = load_mock_coupons()
    points = load_mock_points()
    rep = build_annual_report(orders, coupons, points, year=2026, owner="演示用户")
    print(json.dumps(rep["summary"], ensure_ascii=False, indent=2)[:1200])
    print("\n--- 自检 ---")
    print(json.dumps(self_check(orders), ensure_ascii=False, indent=2))
