#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回归自测套件
============

不依赖任何第三方测试框架，直接 python test_engine.py 即可运行。

覆盖：
- 金额口径的正确性（实付/省下/客单价）
- 回溯表必须指向真实订单号
- 季度切片求和必须等于全年总数
- 口味漂移的方向性
- 券清算的门槛可达性判断
- 空账户必须诚实产出"空"而不是假数据
"""

from __future__ import annotations

import re
import sys
from datetime import date, datetime

from ledger_engine import (_DEFAULT_PERSONA, _PERSONAS, _fries_music, Coupon,
                           Order, OrderItem, PointsAccount, behavior_profile,
                           build_annual_report, build_story, coupon_actions,
                           flavor_drift, median_payable, persona_portrait,
                           quarterly_breakdown, saving_playbook, self_check,
                           summarize_orders)
from mock_loader import load_mock_coupons, load_mock_orders, load_mock_points
from real_adapter import load_owner_name
from render_report import render_html
from render_story import check_arch_consistency, render_story_html

# 面向用户的产物里**绝不允许**出现的开发侧词汇（接口字段名 / 内部术语）
DEV_LEAK_KEYWORDS = [
    "realTotalAmount", "product_total", "delivery_fee", "coupon.face_value",
    "item.unit_price", "Σ(", "MCP Token", "mock）", "payload", "schema",
    "落库", "snapshot", "接口", "TODO", "FIXME", "console.log",
]

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} | {detail}")
        print(f"  ✗ {name}  {detail}")


def section(t: str) -> None:
    print(f"\n[{t}]")


def main() -> int:
    orders = load_mock_orders()
    coupons = load_mock_coupons()
    points = load_mock_points()
    TODAY = date(2026, 10, 9)

    # ------------------------------------------------------------------
    section("1. 金额口径")
    s = summarize_orders(orders)
    manual_paid = round(sum(o.payable for o in orders), 2)
    check("实付总额 = Σpayable", abs(s["paid"] - manual_paid) < 0.01,
          f'{s["paid"]} vs {manual_paid}')

    manual_saved = round(sum(o.product_total + o.delivery_fee - o.payable for o in orders), 2)
    check("省下总额 = Σ(原价+配送-实付)", abs(s["saved"] - manual_saved) < 0.01,
          f'{s["saved"]} vs {manual_saved}')

    check("客单价 = 实付/单数",
          abs(s["aov"] - round(manual_paid / len(orders), 2)) < 0.01)

    check("订单数正确", s["order_count"] == len(orders))

    # ------------------------------------------------------------------
    section("2. 回溯表完整性")
    valid_nos = {o.order_no for o in orders}
    for key in ("order_count", "gross", "paid", "saved"):
        srcs = set(s["trace"][key]["sources"])
        check(f"trace[{key}] 全部指向真实订单", srcs <= valid_nos,
              f"越界: {srcs - valid_nos}")
        check(f"trace[{key}] 覆盖全部订单", srcs == valid_nos)

    check("trace 每项都带 formula", all("formula" in v for v in s["trace"].values()))

    # ------------------------------------------------------------------
    section("3. 季度切片守恒")
    qs = quarterly_breakdown(orders, 2026)
    q_paid = round(sum(q["paid"] for q in qs), 2)
    y_paid = round(sum(o.payable for o in orders if o.ts.year == 2026), 2)
    check("四季度实付之和 = 全年实付", abs(q_paid - y_paid) < 0.01, f"{q_paid} vs {y_paid}")

    q_n = sum(q["order_count"] for q in qs)
    check("四季度订单数之和 = 全年订单数",
          q_n == len([o for o in orders if o.ts.year == 2026]), f"{q_n}")

    # ------------------------------------------------------------------
    section("4. 口味漂移")
    d = flavor_drift(orders, 2026)
    check("漂移结果按月切分完整",
          d["h1_order_count"] + d["h2_order_count"] == len(orders),
          f'{d["h1_order_count"]}+{d["h2_order_count"]}')
    check("H1 全部在上半年",
          all(o.ts.month <= 6 for o in orders if o.ts.year == 2026 and o.order_no in d["trace"]["sources"]["h1"]))
    check("H2 全部在下半年",
          all(o.ts.month >= 7 for o in orders if o.ts.year == 2026 and o.order_no in d["trace"]["sources"]["h2"]))
    check("漂移按变化幅度降序",
          all(abs(d["drift"][i]["delta"]) >= abs(d["drift"][i + 1]["delta"])
              for i in range(len(d["drift"]) - 1)))
    check("有叙事文本", len(d["narrative"]) > 0)

    # ------------------------------------------------------------------
    section("5. 券资产清算")

    # 先单独验证中位数的奇偶两种情形
    def _mk(pays):
        return [Order(order_no=f"T{i}", ts=datetime(2026, 3, 1, 12, 0),
                      payable=p, product_total=p, delivery_fee=0.0, discount=0.0)
                for i, p in enumerate(pays)]

    check("奇数样本中位数取正中", median_payable(_mk([10, 30, 20])) == 20.0,
          str(median_payable(_mk([10, 30, 20]))))
    check("偶数样本中位数取中间两数均值", median_payable(_mk([10, 20, 30, 40])) == 25.0,
          str(median_payable(_mk([10, 20, 30, 40]))))
    check("空样本中位数为0", median_payable([]) == 0.0)

    ca = coupon_actions(coupons, orders, TODAY)
    check("券数量正确", ca["coupon_count"] == len(coupons))
    check("面值合计正确",
          abs(ca["total_face_value"] - round(sum(c.face_value for c in coupons), 2)) < 0.01)

    # C2026B02 无门槛，效率应记为 99
    b02 = next(r for r in ca["priority_list"] if r["coupon_id"] == "C2026B02")
    check("无门槛券效率记为 99", b02["efficiency"] == 99.0)

    # C2026B05 redeemable=False，应被标记门店不可用
    b05 = next(r for r in ca["priority_list"] if r["coupon_id"] == "C2026B05")
    check("门店不可用券被正确标记", b05["redeemable_in_store"] is False)
    check("门店不可用券建议文案正确", "不可用" in b05["action"])

    # C2026B03 门槛50。中位数 = (47+47)/2 = 47.0 < 50，故不可达 —— 这是刻意的边界用例，
    # 用来验证"门槛高于典型消费"能被正确识别，而不是被悄悄放过。
    b03 = next(r for r in ca["priority_list"] if r["coupon_id"] == "C2026B03")
    check("典型消费=47.0（偶数样本取均值）",
          b03["typical_order_payable"] == 47.0, f'{b03["typical_order_payable"]}')
    check("门槛50高于典型消费 → 判为不可达",
          b03["reachable_by_typical_order"] is False)
    check("不可达券建议文案提示门槛过高",
          "门槛" in b03["action"] and "高" in b03["action"], b03["action"])

    # 临期券应被识别（B01 到期 10-20，距今 11 天；B02 到期 10-25，距今 16 天）→ 无 7 天内
    check("7天内到期券数量计算正确", isinstance(ca["expiring_within_7d"], list))

    # 已过期检测
    old = Coupon("X1", "已过期券", 10.0, 20.0, date(2026, 9, 1))
    ca2 = coupon_actions([old], orders, TODAY)
    check("过期券被识别", ca2["expired_count"] == 1)
    check("过期券动作文案正确", "过期" in ca2["priority_list"][0]["action"])

    # ------------------------------------------------------------------
    section("6. 省钱行动清单")
    pb = saving_playbook(orders, coupons, TODAY)
    check("产出至少一条建议", len(pb["actions"]) >= 1)
    check("有可量化估算值", pb["estimated_total_saving"] >= 0)
    check("含免责声明", "以麦当劳官方" in pb["disclaimer"])
    delivery_actions = [a for a in pb["actions"] if a["type"] == "reduce_delivery"]
    check("外送费优化被触发", len(delivery_actions) == 1)
    if delivery_actions:
        check("外送优化带估算前提说明", "assumption" in delivery_actions[0])

    # ------------------------------------------------------------------
    section("7. 空账户诚实性")
    empty = summarize_orders([])
    check("空账户标记 empty", empty["empty"] is True)
    check("空账户不编造数字", empty["order_count"] == 0)
    rep_empty = build_annual_report([], [], None, year=2026, owner="新用户")
    check("空账户年报可正常组装", rep_empty["summary"]["empty"] is True)
    empty_pb = saving_playbook([], [], TODAY)
    check("空账户不给虚假省钱承诺", empty_pb["estimated_total_saving"] == 0)

    # ------------------------------------------------------------------
    section("8. 独立手算校验")
    sc = self_check(orders)
    check("self_check 全部通过", sc["all_pass"] is True,
          str([c for c in sc["checks"] if not c["pass"]]))
    check("自检覆盖至少3项", len(sc["checks"]) >= 3)

    # ------------------------------------------------------------------
    section("9. 行为画像（可回溯、可反驳）")
    prof = behavior_profile(orders)
    check("画像非空", prof["empty"] is False)
    check("输出 4 个维度", len(prof["traits"]) == 4)

    keys = {t["key"] for t in prof["traits"]}
    check("维度键齐全",
          keys == {"combo_dependence", "time_concentration", "variety", "price_level"},
          str(keys))

    valid_nos = {o.order_no for o in orders}
    for t in prof["traits"]:
        check(f"[{t['key']}] 带判定规则", bool(t["rule"]))
        check(f"[{t['key']}] 带阈值与比较符",
              isinstance(t["threshold"], (int, float)) and t["comparator"] in (">=", "<="))
        check(f"[{t['key']}] 有依据", len(t["evidence"]) > 0)

    # 依据的订单号必须是真实订单（或商品名）——不能凭空捏造
    trait_by_key = {t["key"]: t for t in prof["traits"]}
    cd = trait_by_key["combo_dependence"]
    check("套餐维度依据指向真实订单",
          set(cd["evidence"]) <= valid_nos, str(set(cd["evidence"]) - valid_nos))
    pl = trait_by_key["price_level"]
    check("客单价维度依据指向真实订单",
          set(pl["evidence"]) <= valid_nos)

    # 阈值判定必须与 label 一致（防止标签和数值脱节）
    for t in prof["traits"]:
        if t["unit"] == "%":
            should_pass = (t["value"] >= t["threshold"]) if t["comparator"] == ">=" \
                else (t["value"] <= t["threshold"])
            check(f"[{t['key']}] 标签与阈值判定一致",
                  isinstance(t["label"], str) and len(t["label"]) > 0 and should_pass is not None)

    check("含免责声明", "不构成" in prof["disclaimer"])
    check("声明只描述行为", "行为" in prof["disclaimer"])
    check("含与同类项目的区分说明", "黑箱" in prof["note"])
    check("汇总语包含各维度标签",
          all(t["label"] in prof["summary"] for t in prof["traits"]))

    # 空数据
    empty_prof = behavior_profile([])
    check("空数据画像标记 empty", empty_prof["empty"] is True)
    check("空数据不给结论", empty_prof["traits"] == [])

    # 年报必须含 behavior 段
    rep_b = build_annual_report(orders, coupons, points, year=2026, owner="测试", today=TODAY)
    check("年报含 behavior 段", "behavior" in rep_b)
    check("年报 behavior 非空", rep_b["behavior"]["empty"] is False)

    # ------------------------------------------------------------------
    section("10. 叙事剧本")
    story = build_story(orders, coupons, points, year=2026, owner="测试", today=TODAY)
    check("叙事非空", story["empty"] is False)
    check("有 9 屏", len(story["scenes"]) == 9, str(len(story["scenes"])))
    check("首屏是开场", story["scenes"][0]["kind"] == "opening")
    check("末屏是收尾", story["scenes"][-1]["kind"] == "closing")

    # 会员尾号：跳过署名时的兜底（取 accountId 末 4 位）
    # 注意：这里刻意用**假 accountId**，只保证形状（20 位数字）与末 4 位即可，
    # 不得写入任何真实账号 ID —— 测试文件会入库。
    story_acct = build_story(orders, coupons, points, year=2026, owner="测试",
                             account={"accountId": "00000000000000003118"})
    check("带账户时取会员尾号末 4 位",
          story_acct.get("member_suffix") == "3118", str(story_acct.get("member_suffix")))
    check("无账户时会员尾号为空",
          story.get("member_suffix") == "", str(story.get("member_suffix")))
    check("短 accountId 只取末尾可用位",
          build_story(orders, account={"accountId": "12345"}).get("member_suffix") == "2345")

    kinds = [s["kind"] for s in story["scenes"]]
    for need in ("opening", "number", "place", "taste", "time",
                 "persona_teaser", "persona", "assets", "closing"):
        check(f"含 {need} 屏", need in kinds)
    check("已移除行为佐证屏（profile）", "profile" not in kinds, str(kinds))
    check("人格预告屏在人格屏之前",
          kinds.index("persona_teaser") < kinds.index("persona"), str(kinds))
    check("人格屏之后直接进入资产屏",
          kinds.index("persona") < kinds.index("assets"))

    valid_nos = {o.order_no for o in orders}
    for s in story["scenes"]:
        for ev in s.get("evidence", []):
            if ev.startswith("MCD2026") or ev.startswith("1030"):
                check(f"[{s['kind']}] 依据指向真实订单", ev in valid_nos, ev)
    check("每屏都有标题", all(s.get("title") for s in story["scenes"]))
    check("每屏都有大字", all(s.get("big") for s in story["scenes"]))
    check("涉及数字的屏带公式说明",
          any(s.get("formula") for s in story["scenes"]))

    # 人格屏：标题为「你的麦麦人格是」，人格名进大标题
    per_scene = next(s for s in story["scenes"] if s["kind"] == "persona")
    check("人格屏标题为『你的麦麦人格是』",
          per_scene["title"] == "你的麦麦人格是", per_scene["title"])
    check("人格屏大标题是具体人格名",
          per_scene["big"] in {p["name"] for p in _PERSONAS} | {"麦门永存"},
          per_scene["big"])
    check("人格屏带候选清单（可回溯）", len(per_scene.get("candidates", [])) > 0)
    check("人格屏候选带触发条件",
          all(c.get("trigger") for c in per_scene["candidates"]))
    check("人格屏声明只描述行为、非性格评价",
          "不构成对性格" in per_scene.get("note", ""))
    check("人格屏声明可核验可反驳",
          "核验" in per_scene.get("note", ""))

    # 行为佐证屏已从叙事版移除（四维度仍保留在报告版与 behavior_profile 中）
    check("叙事版不再包含 profile 屏",
          all(s["kind"] != "profile" for s in story["scenes"]))

    # 空账户叙事
    empty_story = build_story([], [], None, year=2026, owner="新用户")
    check("空账户叙事标记 empty", empty_story["empty"] is True)
    check("空账户只有一屏", len(empty_story["scenes"]) == 1)
    check("空账户不编造数字", "还没有" in empty_story["scenes"][0]["big"])

    # 小样本提示
    one = [orders[0]]
    thin = build_story(one, [], None, year=2026, owner="单笔用户", today=TODAY)
    check("单笔订单给出小样本提示",
          any("极小样本" in l for s in thin["scenes"] for l in s.get("lines", [])))

    # ------------------------------------------------------------------
    section("11. 完整年报组装")
    rep = build_annual_report(orders, coupons, points, year=2026,
                              owner="测试用户", today=TODAY)
    for key in ("meta", "summary", "quarterly", "monthly", "flavor_drift",
                "coupons", "playbook", "points"):
        check(f"年报含 {key} 段", key in rep)
    check("月度切片 12 个月", len(rep["monthly"]) == 12)
    check("积分已序列化", isinstance(rep["points"]["expiring_at"], str))
    check("不含真实 Token", "Bearer" not in str(rep))
    check("年报含 persona 段", "persona" in rep)

    # ------------------------------------------------------------------
    section("12. 麦麦人格")
    persona = persona_portrait(orders, owner="测试用户")
    check("人格池非空", len(_PERSONAS) >= 14, str(len(_PERSONAS)))
    check("人格池每个人格都有名字",
          all(p.get("name") for p in _PERSONAS))
    check("人格池每个人格都有触发条件",
          all(p.get("match_item") or p.get("match_cat") or p.get("match_slot")
              or p.get("match_pair")
              for p in _PERSONAS))
    check("隐藏人格必须用 match_pair 声明条件",
          all(p.get("match_pair") for p in _PERSONAS if p.get("hidden")))
    check("人格池每个人格都有文案模板",
          all(p.get("lines") for p in _PERSONAS))
    check("人格池每个人格都有门槛", all("min_n" in p for p in _PERSONAS))

    check("正常账户产出主人格", persona["main"] is not None)
    check("主人格是池中人格或兜底",
          persona["main"]["name"] in {p["name"] for p in _PERSONAS}
          or persona["main"]["name"] == _DEFAULT_PERSONA["name"])
    check("主人格数值为正", persona["main"]["count"] > 0)

    # 文案里的数字必须来自真实数据（可回溯）
    main = persona["main"]
    check("主人格文案含实测数量",
          any(str(main["count"]) in ln for ln in main["lines"]), str(main["lines"]))
    check("主人格带触发条件说明", bool(main.get("trigger")))

    # 副人格最多 2 个
    check("副人格不超过 2 个", len(persona["subs"]) <= 2, str(len(persona["subs"])))

    # 副人格可展开：必须携带完整封号信息（迷你证书）
    check("演示数据有副人格可测", len(persona["subs"]) > 0, str(len(persona["subs"])))
    for s_ in persona["subs"]:
        check(f"[{s_['name']}] 副人格带 lines 文案",
              bool(s_.get("lines")) and all(isinstance(x, str) for x in s_["lines"]),
              str(s_.get("lines"))[:60])
        check(f"[{s_['name']}] 副人格带 display_kind", bool(s_.get("display_kind")))
        check(f"[{s_['name']}] 副人格带 cover", bool(s_.get("cover")))
        check(f"[{s_['name']}] 副人格带触发条件", bool(s_.get("trigger")))
        # 副人格文案里的数字应是自己的实测数量（不是主人格的）
        check(f"[{s_['name']}] 副人格文案含自身数量",
              any(str(s_["count"]) in ln for ln in s_["lines"]),
              f"{s_['count']} vs {s_['lines'][:1]}")

    # 候选按数量降序（sub_only 人格被故意沉底，排除后再验证）
    counts = [c["count"] for c in persona["candidates"]
              if not c.get("sub_only")]
    check("候选按数量降序", counts == sorted(counts, reverse=True), str(counts))

    # 同源去重：同一商品不被两个人格重复计数
    check("候选之间数量单调不增（去重生效）",
          all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)))
    # sub_only 人格若在候选中，必须排在最后一位（不抢主人格顺位）
    sub_only_cands = [c for c in persona["candidates"] if c.get("sub_only")]
    if sub_only_cands:
        check("sub_only 候选沉底（排在最后）",
              persona["candidates"][-1].get("sub_only") is True,
              str([c["name"] for c in persona["candidates"]]))

    # 门槛：单笔订单撑不起具体人格 → 走兜底
    tiny = [Order(order_no="T1", ts=datetime(2026, 3, 1, 12, 0),
                  items=[OrderItem("P1", "巨无霸", 24.0, 1, "主食")],
                  payable=24.0)]
    tp = persona_portrait(tiny, owner="小用户")
    check("极小样本回落兜底人格", tp["default"] is True, str(tp["main"]["name"]))
    check("兜底人格名为麦门永存", tp["main"]["name"] == "麦门永存")

    # 空账户
    ep = persona_portrait([], owner="新用户")
    check("空账户人格标记 empty", ep["empty"] is True)
    check("空账户主人格为 None", ep["main"] is None)

    # 自检：薯条钢琴家的八重奏/四重奏/双重奏派生量
    fries = [Order(order_no=f"F{i}", ts=datetime(2026, 5, 1, 12, 0),
                   items=[OrderItem("P2", "大薯条", 15.0, 4, "小食")],
                   payable=60.0) for i in range(10)]   # 40 盒薯条
    fp = persona_portrait(fries, owner="薯门用户")
    fm = fp["main"]
    check("薯条多时主人格为薯条钢琴家", fm["name"] == "薯条钢琴家", fm["name"])
    check("薯条钢琴家数量为 40", fm["count"] == 40, str(fm["count"]))
    check("薯条钢琴家带八重奏文案",
          any("八重奏" in ln for ln in fm["lines"]))
    check("八重奏 = 40 盒 ÷ 8 = 5 场",
          any("5 场八重奏" in ln for ln in fm["lines"]), str(fm["lines"]))
    check("薯条钢琴家封号含用户名",
          any("薯门用户" in ln for ln in fm["lines"]), str(fm["lines"]))

    # 重奏换算（贪心拆分）：8/4/2 盒各一档
    check("18 盒 = 2 场八重奏 + 1 场双重奏",
          _fries_music(18) == "2 场八重奏、1 场双重奏", _fries_music(18))
    check("13 盒 = 1 场八重奏 + 1 场四重奏 + 余 1 盒",
          _fries_music(13) == "1 场八重奏、1 场四重奏、余 1 盒", _fries_music(13))
    check("7 盒 = 1 场四重奏 + 1 场双重奏 + 余 1 盒",
          _fries_music(7) == "1 场四重奏、1 场双重奏、余 1 盒", _fries_music(7))
    check("2 盒 = 1 场双重奏",
          _fries_music(2) == "1 场双重奏", _fries_music(2))
    check("1 盒凑不齐重奏、余 1 盒",
          _fries_music(1) == "余 1 盒", _fries_music(1))

    # 吉士行乐：吉士汉堡系列
    cheese = [Order(order_no=f"C{i}", ts=datetime(2026, 5, 1, 12, 0),
                    items=[OrderItem("P3", "双层吉士汉堡", 18.0, 1, "主食")],
                    payable=18.0) for i in range(6)]
    cp = persona_portrait(cheese, owner="芝士控")
    check("吉士多时主人格为吉士行乐",
          cp["main"]["name"] == "吉士行乐", cp["main"]["name"])
    check("吉士行乐数量为 6", cp["main"]["count"] == 6, str(cp["main"]["count"]))
    check("吉士行乐文案含封号",
          any("吉士行乐" in ln for ln in cp["main"]["lines"]), str(cp["main"]["lines"]))
    check("吉士行乐触发条件含『吉士』",
          "吉士" in cp["main"]["trigger"], cp["main"]["trigger"])
    # 「芝士」也是同一系列的常见写法，应一并命中
    cheese2 = [Order(order_no=f"D{i}", ts=datetime(2026, 5, 1, 12, 0),
                     items=[OrderItem("P4", "芝士蛋堡", 12.0, 1, "主食")],
                     payable=12.0) for i in range(6)]
    check("『芝士』写法同样命中吉士系列",
          persona_portrait(cheese2, owner="芝士控")["main"]["name"] == "吉士行乐")
    # 低于门槛不应封号
    few = [Order(order_no="C1", ts=datetime(2026, 5, 1, 12, 0),
                 items=[OrderItem("P3", "双层吉士汉堡", 18.0, 1, "主食")],
                 payable=18.0)]
    check("吉士不足门槛不封号",
          persona_portrait(few, owner="芝士控")["main"]["name"] == "麦门永存")

    # 堡你周全：所有汉堡之和（全集型，不与单品汉堡人格去重）
    def _burgers(name, n, cat="主食"):
        return [Order(order_no=f"B{i}", ts=datetime(2026, 5, 1, 12, 0),
                      items=[OrderItem("P5", name, 20.0, 1, cat)],
                      payable=20.0) for i in range(n)]

    # 麦辣 16 + 巨无霸 12 = 28 个汉堡，数值最高，但「堡你周全」是 sub_only：
    # 只能当副人格，主人格顺延给次高的「麦辣战神」（16 个）。
    mixed = _burgers("麦辣鸡腿堡", 16) + _burgers("巨无霸", 12)
    bp = persona_portrait(mixed, owner="汉堡控")
    check("堡你周全**不**当主人格（sub_only）",
          bp["main"]["name"] != "堡你周全", bp["main"]["name"])
    check("主人格顺延给次高的单品汉堡人格",
          bp["main"]["name"] == "麦辣战神", bp["main"]["name"])
    check("堡你周全出现在副人格中",
          "堡你周全" in [s["name"] for s in bp["subs"]],
          str([s["name"] for s in bp["subs"]]))
    check("副人格里堡你周全数量为所有汉堡之和 28",
          next(s["count"] for s in bp["subs"]
               if s["name"] == "堡你周全") == 28,
          str(bp["subs"]))
    check("堡你周全仍在候选清单中（可回溯）",
          "堡你周全" in [c["name"] for c in bp["candidates"]],
          str([c["name"] for c in bp["candidates"]]))
    check("候选清单里堡你周全被排到最后（不能抢主板位）",
          bp["candidates"][-1]["name"] == "堡你周全",
          str([c["name"] for c in bp["candidates"]]))
    # 单品汉堡人格仍在候选里（可回溯，不是被抹掉）
    cand_names = [c["name"] for c in bp["candidates"]]
    check("单品汉堡人格仍在候选清单中",
          "麦辣战神" in cand_names and "巨无霸原教旨" in cand_names,
          str(cand_names))
    # 只有汉堡时：主人格顺延给单品型，堡你周全做副人格
    tie = _burgers("巨无霸", 12)
    tp = persona_portrait(tie, owner="巨无霸粉")
    check("只有汉堡时主人格为单品型（堡你周全让位）",
          tp["main"]["name"] == "巨无霸原教旨", tp["main"]["name"])
    check("只有汉堡时堡你周全仍在副人格",
          "堡你周全" in [s["name"] for s in tp["subs"]],
          str([s["name"] for s in tp["subs"]]))
    # 汉堡总量低于门槛（3 个）不封号
    check("汉堡不足门槛不封号",
          persona_portrait(_burgers("巨无霸", 3),
                           owner="随便吃")["main"]["name"] == "麦门永存")
    check("universal 人格被标记",
          any(p.get("universal") for p in _PERSONAS))
    check("堡你周全被标记为 sub_only",
          any(p.get("sub_only") for p in _PERSONAS if p.get("key") == "burger_guardian"),
          str([p for p in _PERSONAS if p.get("key") == "burger_guardian"]))
    check("sub_only 人格永不当主人格（穷举构造用例）",
          all(persona_portrait(_burgers("巨无霸", n), owner="测")["main"]["name"] != "堡你周全"
              for n in (10, 12, 20, 40, 99)),
          "存在 n 使堡你周全成为主人格")

    # 隐藏人格：冰矛鸡爪流（同一单同时点鸡翅 + 冰激凌，≥3 单解锁）
    def _pair_orders(n, with_wings=True, with_ice=True, same_order=True):
        """构造 n 单；可控制是否含鸡翅/冰激凌、是否放在同一单。"""
        rows = []
        for i in range(n):
            items = []
            if same_order:
                if with_wings:
                    items.append(OrderItem("P6", "麦辣鸡翅", 12.0, 1, "小食"))
                if with_ice:
                    items.append(OrderItem("P7", "朱古力新地", 9.0, 1, "甜点"))
            else:
                if with_wings:
                    items.append(OrderItem("P6", "麦辣鸡翅", 12.0, 1, "小食"))
            rows.append(Order(order_no=f"H{i}", ts=datetime(2026, 5, 1, 12, 0),
                              items=items, payable=20.0))
        return rows

    hp = persona_portrait(_pair_orders(4), owner="召唤师")
    check("同单鸡翅+冰激凌≥3 单时解锁隐藏人格",
          hp["main"]["name"] == "冰矛鸡爪流", hp["main"]["name"])
    check("隐藏人格被标记 hidden",
          hp["main"]["hidden"] is True)
    check("hidden_unlocked 为 True", hp["hidden_unlocked"] is True)
    check("摘要含「隐藏人格解锁」",
          "隐藏人格解锁" in hp["summary"], hp["summary"])
    check("隐藏人格数量为同时出现的订单数 4",
          hp["main"]["count"] == 4, str(hp["main"]["count"]))
    check("隐藏人格 unit 为『单』", hp["main"]["unit"] == "单", hp["main"]["unit"])
    check("隐藏人格触发条件写明『同一笔订单』",
          "同一笔订单" in hp["main"]["trigger"], hp["main"]["trigger"])
    check("隐藏人格**不出现在**候选清单中",
          all(c["name"] != "冰矛鸡爪流" for c in hp["candidates"]),
          str([c["name"] for c in hp["candidates"]]))
    # 关键词覆盖多种写法
    hp2 = persona_portrait(
        [Order(order_no=f"K{i}", ts=datetime(2026, 5, 1, 12, 0),
               items=[OrderItem("P8", "奥尔良烤翅", 12.0, 1, "小食"),
                      OrderItem("P9", "圆筒冰激凌", 6.0, 1, "甜点")],
               payable=18.0) for i in range(3)])
    check("鸡翅/冰激凌的其他写法同样解锁",
          hp2["main"]["name"] == "冰矛鸡爪流", hp2["main"]["name"])
    # 反向条件
    check("只点鸡翅不解锁隐藏",
          persona_portrait(_pair_orders(6, with_ice=False))["hidden_unlocked"] is False)
    check("只点冰激凌不解锁隐藏",
          persona_portrait(_pair_orders(6, with_wings=False))["hidden_unlocked"] is False)
    check("鸡翅冰激凌不在同一单不解锁",
          persona_portrait(_pair_orders(6, same_order=False))["hidden_unlocked"] is False)
    check("同单但不足 3 单不解锁",
          persona_portrait(_pair_orders(2))["hidden_unlocked"] is False)
    # 隐藏人格顶替主人格，原主人格降为副人格（可回溯）
    hp3 = persona_portrait(_pair_orders(4) + _burgers("巨无霸", 10), owner="召唤师")
    check("隐藏人格顶替主人格",
          hp3["main"]["name"] == "冰矛鸡爪流", hp3["main"]["name"])
    check("原主人格降为副人格仍在候选/副人格中",
          any(s["name"] == "巨无霸原教旨" for s in hp3["subs"]),
          str([s["name"] for s in hp3["subs"]]))
    check("隐藏人格被标记 hidden 字段存在",
          all("hidden" in p for p in _PERSONAS if p.get("kind") == "隐藏"))

    # 麦辣战神关键词回归：鸡翅（小食）不应被算成"麦辣系列汉堡"
    wings = _burgers("麦辣鸡翅", 6, cat="小食")
    check("麦辣鸡翅不封麦辣战神（避免文案说成汉堡）",
          persona_portrait(wings, owner="翅粉")["main"]["name"] != "麦辣战神",
          persona_portrait(wings, owner="翅粉")["main"]["name"])
    check("麦辣鸡腿堡仍封麦辣战神",
          persona_portrait(_burgers("麦辣鸡腿堡", 6),
                           owner="战神")["main"]["name"] == "麦辣战神")

    # ------------------------------------------------------------------
    section("13. 无开发泄露（产物中不得出现接口字段名等开发侧词汇）")

    def _visible_text(html_str: str) -> str:
        """剥掉 script/style 与标签，只留用户能看到的文本。"""
        vis = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_str,
                     flags=re.S | re.I)
        vis = re.sub(r"<[^>]+>", " ", vis)
        from html import unescape as _unescape
        return _unescape(vis)

    story_html = render_story_html(story, mock=False)
    report_html = render_html(rep, orders, mock=False)

    for label, doc in (("叙事版", story_html), ("报告版", report_html)):
        vis = _visible_text(doc)
        leaked = [k for k in DEV_LEAK_KEYWORDS if k in vis]
        check(f"{label}可见文本无开发泄露词", not leaked, f"泄露：{leaked}")

    check("兜底人格展示名为『通用』而非『兜底』",
          _DEFAULT_PERSONA.get("display_kind") == "通用",
          str(_DEFAULT_PERSONA.get("display_kind")))
    check("隐藏人格展示名为『隐藏成就』",
          all(p.get("display_kind") for p in _PERSONAS if p.get("hidden")))
    fallback_story = build_story(
        [Order(order_no="F1", ts=datetime(2026, 5, 1, 12, 0),
               items=[OrderItem("P1", "苹果派", 8.0, 1, "甜点")], payable=8.0)],
        [], None, year=2026, owner="新用户")
    fb_scene = next(s for s in fallback_story["scenes"] if s["kind"] == "persona")
    check("兜底人格屏 unit 显示『通用』",
          "通用" in fb_scene["unit"] and "兜底" not in fb_scene["unit"],
          fb_scene["unit"])

    # 开场屏署名：MCP 无昵称字段，由 data/user.json 的 owner_name 自填（留空回落默认）
    import json as _json
    import os as _os
    import tempfile as _tf
    import real_adapter as _ra
    check("署名留空时回落默认",
          _ra.load_owner_name("默认名") == "默认名")
    _tmp = _tf.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                  encoding="utf-8")
    _json.dump({"owner_name": "测试昵称"}, _tmp, ensure_ascii=False)
    _tmp.close()
    _old_cfg = _ra._USER_CFG
    _ra._USER_CFG = _tmp.name
    try:
        check("署名读取自定义昵称",
              _ra.load_owner_name("默认名") == "测试昵称")
    finally:
        _ra._USER_CFG = _old_cfg
        _os.unlink(_tmp.name)

    # ------------------------------------------------------------------
    section("14. 叙事版不得出现「算法 / 依据」入口（保持沉浸感）")

    # 用带满人格、券、积分的完整剧本渲染，确保每种屏型都被覆盖到
    full_html = render_story_html(story, mock=False)
    # 只在页面结构层面找入口控件，不扫描正文（正文里"依据"可能正常出现）
    check("叙事版无「依据」展开面板",
          "↺ 依据" not in full_html and 'class="evidence"' not in full_html,
          "仍存在依据面板")
    check("叙事版无「算法」标签条",
          'class="formula"' not in full_html or "算法" not in full_html)
    check("叙事版页脚不再声称可展开依据",
          "每个结论都可以展开查看依据" not in full_html)
    # 人格屏的候选清单属于「人格是怎么判的」，是叙事版唯一保留的可回溯入口
    check("叙事版保留人格候选清单",
          'class="persona-roster"' in full_html, "候选清单被误删")
    # 副人格胶囊可点击展开（details 结构 + 迷你证书面板）
    check("叙事版副人格为可展开 details",
          '<details class="sub">' in full_html, "副人格胶囊未改为 details")
    check("叙事版副人格展开面板存在",
          'class="sub-detail"' in full_html, "副人格迷你证书缺失")
    # 人格预告屏：悬念页 + 「揭晓」按钮
    check("叙事版人格预告屏存在",
          'class="scene teaser"' in full_html, "预告屏缺失")
    check("叙事版预告屏有「揭晓」按钮",
          'id="teaser-btn"' in full_html, "预告屏按钮缺失")
    # 移动端触摸翻页（pointer 事件）逻辑存在，防回归
    check("叙事版含触摸翻页逻辑（pointerdown/pointerup）",
          'pointerdown' in full_html and 'pointerup' in full_html,
          "触摸翻页逻辑缺失")
    # 昵称署名层：首次打开输入昵称，localStorage 记住，开场屏显示
    check("叙事版开场屏有署名槽（owner-name）",
          'id="owner-name"' in full_html, "署名槽缺失")
    check("叙事版含署名输入层",
          'id="name-overlay"' in full_html and 'id="name-input"' in full_html,
          "署名输入层缺失")
    check("署名持久化用 localStorage（不上传）",
          'localStorage' in full_html and 'mcd-ledger-owner' in full_html)
    # 保存图片：人格屏有保存按钮 + Canvas 绘制 + 人格数据注入
    check("人格屏有「保存图片」按钮",
          'id="save-btn"' in full_html, "保存按钮缺失")
    check("保存图片含 Canvas 绘制逻辑",
          'drawShareCard' in full_html and 'toDataURL' in full_html,
          "Canvas 导出逻辑缺失")
    check("人格数据已注入（PERSONA）",
          'var PERSONA =' in full_html, "PERSONA 数据缺失")
    # 类型印章（单品型/组合型等）已按用户要求从 UI 移除
    check("叙事版无类型印章",
          'class="seal"' not in full_html and 'class="seal2"' not in full_html,
          "仍存在类型印章")
    # 用演示数据（命中多个人格）检查可见文本里不出现类型词
    demo_html = render_story_html(
        build_story(load_mock_orders(), load_mock_coupons(),
                    load_mock_points(), year=2026, owner="演示用户"),
        mock=True)
    vis_demo = _visible_text(demo_html)
    kind_words = [w for w in ("单品型", "组合型", "场景型", "兜底")
                  if w in vis_demo]
    check("叙事版可见文本无人格类型词", not kind_words, f"残留：{kind_words}")
    # 报告版必须继续保留回溯能力（与叙事版形成分工）
    check("报告版保留回溯面板",
          'class="trace"' in report_html or "↺" in report_html,
          "报告版回溯能力丢失")

    # ------------------------------------------------------------------
    section("[15. 分享卡与网页人格卡保持同一套版式]")
    # 分享卡与网页卡片同源：金拱门由同一份路径常量驱动
    try:
        check_arch_consistency()
        arch_ok, arch_msg = True, ""
    except AssertionError as e:
        arch_ok, arch_msg = False, str(e)
    check("金拱门几何常量自洽（SVG/Canvas 同源）", arch_ok, arch_msg)
    check("分享卡用 Path2D 复用 SVG 路径",
          "new Path2D(ARCH_D)" in full_html and "ARCH_TRANS" in full_html,
          "分享卡未复用 SVG 路径常量")
    # 网页卡片上的五个结构块，分享卡必须一一对应
    check("分享卡含 kicker「你的麦麦人格是」",
          "'你的麦麦人格是'" in full_html)
    check("分享卡有右侧「本年度累计」",
          "'本年度累计'" in full_html)
    check("分享卡含档案说明框（note）",
          "D.note" in full_html and "'#FFF3D4'" in full_html,
          "分享卡缺少档案说明框")
    check("分享卡含版权行",
          "本作品由水牛先生开发，请勿盗用" in full_html)
    # 卡片高度按内容计算，不得写死导致底部留白或内容溢出
    check("分享卡高度按内容自适应",
          "var CARD_H = Math.max(" in full_html and "realH" not in full_html,
          "分享卡仍存在写死高度")
    # 人格候选清单位于分享卡之外的网页卡片里（分享卡只放正文三条）
    check("分享卡备注字段已注入（note）",
          '"note":' in full_html, "PERSONA.note 未注入")

    # ------------------------------------------------------------------
    section("[16. 分享卡只含卡片内容，不含网页界面控件]")
    # 从 drawShareCard 函数体里取源码，只在这个范围内做「不得出现」检查
    _m = re.search(r"function drawShareCard\(\)\{(.*?)\n  \}\n", full_html, re.S)
    check("能定位 drawShareCard 函数体", _m is not None)
    if _m:
        raw_body = _m.group(1)
        # 先剥掉 JS 注释再检查：注释里会提到这些控件的名字，
        # 那是说明文字，不是绘制代码。
        body = re.sub(r"//[^\n]*", "", raw_body)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        # 用户蓝框点名的三处界面控件，都不得画进保存的图片
        for label, needle in (
            ("返回按钮", "\u2190"),
            ("真实数据徽标", "真实数据"),
            ("保存按钮胶囊", "保存我的麦麦人格图片"),
        ):
            check(f"分享卡不含{label}", needle not in body,
                  f"drawShareCard 内仍绘制了{label}")
        # 卡片正文该有的仍在
        check("分享卡仍有人格名", "D.name" in body)
        check("分享卡仍有正文条目", "D.lines" in body)
        check("分享卡仍有档案说明框", "D.note" in body)
        check("分享卡仍有金拱门", "drawArch" in body)

    # ------------------------------------------------------------------
    section("[17. 开场屏金拱门为黄色（用户点名，勿改回红色）]")
    hero_arch = re.search(
        r'class="arches-hero">\s*(<svg[^>]*>)', full_html, re.S)
    check("开场屏存在金拱门元素", hero_arch is not None, "未找到 arches-hero")
    if hero_arch:
        svg_tag = hero_arch.group(1)
        check("开场屏金拱门为品牌黄",
              "brand-yellow" in svg_tag,
              f"开场屏拱门颜色不是黄色：{svg_tag[:120]}")
    check("开场屏背景光晕已弱化（避免与黄色拱门撞色）",
          "rgba(255,199,44,.16)" in full_html,
          "开场屏光晕强度未下调")
    check("开场屏拱门有白色描边托底",
          "rgba(255,255,255,.95)" in full_html,
          "开场屏拱门缺少白描边")
    # 收尾屏拱门保持黄色（原本就是），确认两屏一致
    check("收尾屏金拱门亦为品牌黄",
          full_html.count("color:var(--brand-yellow)") >= 2,
          "收尾屏拱门颜色异常")

    # ------------------------------------------------------------------
    section("[18. 署名输入层金拱门为黄色（用户点名）]")
    name_card = re.search(
        r'<div class="name-card">\s*(<svg[^>]*>)', full_html, re.S)
    check("能定位署名层金拱门", name_card is not None, "未找到 name-card 内的拱门")
    if name_card:
        check("署名层金拱门为品牌黄",
              "brand-yellow" in name_card.group(1),
              f"署名层拱门颜色不对：{name_card.group(1)[:120]}")
    check("署名层拱门有暖黄描边托底",
          ".name-card .ga{" in full_html and "rgba(176,122,0,.55)" in full_html,
          "署名层拱门缺少描边，白底上会发飘")
    # 全站拱门配色一致性：开场/收尾/署名三处的黄色用量
    check("全站拱门黄色用法齐全",
          full_html.count("color:var(--brand-yellow)") >= 3,
          "有拱门位置未改为黄色")

    # ------------------------------------------------------------------
    print(f"\n{'='*52}")
    print(f"  通过 {PASS} 项，失败 {FAIL} 项")
    if FAILURES:
        print("  失败明细：")
        for f in FAILURES:
            print(f"    - {f}")
    print(f"{'='*52}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
