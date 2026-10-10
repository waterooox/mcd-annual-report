#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
年报渲染器：把 build_annual_report() 的结果渲染成一个**单文件、零依赖**的 HTML 年报。

为什么用单文件 HTML：
- 浏览器双击即开，无需任何环境，路人 clone 后立刻能看到成果（利于 star）。
- 自带滚动叙事 + 图表（纯 CSS/SVG，不引 CDN），整页可一键截图传播。
- 所有数字旁标"↺"可点开回溯面板，看到构成该数字的原始订单号与公式。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from html import escape
from typing import Any, Dict, List

from ledger_engine import (Coupon, Order, PointsAccount, build_annual_report,
                           self_check)


# ---------------------------------------------------------------------------
# 小组件
# ---------------------------------------------------------------------------

def _money(v: float) -> str:
    return f"¥{v:,.2f}"


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def trace_panel(trace: Dict[str, Any], title: str = "数据回溯") -> str:
    """可折叠的回溯面板：证明每个数字都能指回原始记录。"""
    if not trace:
        return ""
    body = escape(json.dumps(trace, ensure_ascii=False, indent=2))
    return f"""
    <details class="trace">
      <summary>↺ {escape(title)}</summary>
      <pre>{body}</pre>
    </details>"""


def bar_chart(data: Dict[str, float], color: str = "var(--accent)") -> str:
    """纯 CSS 横向条形图。"""
    if not data:
        return '<p class="muted">暂无数据</p>'
    mx = max(data.values()) or 1
    rows = []
    for k, v in sorted(data.items(), key=lambda kv: -kv[1]):
        w = max(2.0, v / mx * 100)
        rows.append(f"""
        <div class="bar-row">
          <span class="bar-label">{escape(str(k))}</span>
          <span class="bar-track"><i style="width:{w:.1f}%;background:{color}"></i></span>
          <span class="bar-value">{v:,.2f}</span>
        </div>""")
    return '<div class="bars">' + "".join(rows) + "</div>"


def line_chart(monthly: List[Dict[str, Any]]) -> str:
    """纯 SVG 折线图，展示月度实付轨迹。"""
    paid = [m["paid"] for m in monthly]
    mx = max(paid) if paid and max(paid) > 0 else 1
    W, H, PAD = 660, 180, 28
    n = len(monthly)
    if n < 2:
        return '<p class="muted">数据不足</p>'
    step = (W - PAD * 2) / (n - 1)
    pts = [(PAD + i * step, H - PAD - (v / mx) * (H - PAD * 2)) for i, v in enumerate(paid)]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    area = path + f" L{pts[-1][0]:.1f},{H-PAD} L{pts[0][0]:.1f},{H-PAD} Z"
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="var(--accent)"/>' for x, y in pts)
    labels = "".join(
        f'<text x="{x:.1f}" y="{H-8}" font-size="10" text-anchor="middle" fill="var(--muted-fg)">{m["month"]}</text>'
        for (x, _), m in zip(pts, monthly)
    )
    return f"""
    <svg viewBox="0 0 {W} {H}" class="linechart" role="img" aria-label="月度实付轨迹">
      <path d="{area}" fill="var(--accent-soft)" opacity="0.45"/>
      <path d="{path}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>
      {dots}{labels}
    </svg>"""


def quarterly_table(quarters: List[Dict[str, Any]]) -> str:
    rows = []
    for q in quarters:
        rows.append(f"""
        <tr>
          <td><b>{q['quarter']}</b></td>
          <td>{q['order_count']}</td>
          <td>{_money(q['paid'])}</td>
          <td>{_money(q['aov'])}</td>
          <td>{_pct(q['discount_rate'])}</td>
        </tr>""")
    return f"""
    <table class="tbl">
      <thead><tr><th>季度</th><th>订单数</th><th>实付</th><th>客单价</th><th>折扣率</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def drift_view(drift: Dict[str, Any]) -> str:
    if not drift or not drift.get("drift"):
        return '<p class="muted">数据不足，无法判断口味漂移。</p>'
    rows = []
    for d in drift["drift"][:6]:
        delta = d["delta"]
        cls = "up" if delta > 0 else ("down" if delta < 0 else "flat")
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        rows.append(f"""
        <div class="drift-row">
          <span class="drift-cat">{escape(d['category'])}</span>
          <span class="drift-nums">{_pct(d['h1_share'])} → {_pct(d['h2_share'])}
            <em class="{cls}">{arrow} {abs(delta)*100:.1f}pp</em></span>
        </div>""")
    return f"""
    <p class="narrative">「{escape(drift['narrative'])}」</p>
    <div class="drift">{''.join(rows)}</div>"""


def _fmt_threshold(t: Dict[str, Any]) -> str:
    """按单位格式化阈值，避免把 0.7 显示成 "0.7%"。"""
    u = t["unit"]
    if u == "%":
        return f"{t['threshold']*100:.0f}%"
    if u == "元":
        return f"¥{t['threshold']:.0f}"
    return f"{t['threshold']:.1f} {u}"


def behavior_view(profile: Dict[str, Any]) -> str:
    """行为风格画像：每个特征都展示实测值、阈值、规则与支撑订单。"""
    if not profile or profile.get("empty"):
        return f'<p class="muted">{escape((profile or {}).get("summary", "数据不足。"))}</p>'

    cards = []
    for t in profile["traits"]:
        # 进度条：以阈值为参考线，展示实测值位置
        unit = t["unit"]
        if unit == "%":
            pos = min(100.0, t["value"] * 100)
            th_pos = min(100.0, t["threshold"] * 100)
            val_txt = f"{t['value']*100:.1f}%"
        elif unit == "元":
            scale = max(t["value"], t["threshold"]) * 1.4 or 1
            pos = min(100.0, t["value"] / scale * 100)
            th_pos = min(100.0, t["threshold"] / scale * 100)
            val_txt = f"¥{t['value']:.2f}"
        else:  # 种/单
            scale = max(t["value"], t["threshold"]) * 1.4 or 1
            pos = min(100.0, t["value"] / scale * 100)
            th_pos = min(100.0, t["threshold"] / scale * 100)
            val_txt = f"{t['value']:.2f} 种/单"

        th_txt = f"阈值 {_fmt_threshold(t)}"
        ev = t.get("evidence", [])
        ev_preview = "、".join(ev[:6]) + ("…" if len(ev) > 6 else "")

        cards.append(f"""
        <div class="trait-card">
          <div class="trait-head">
            <span class="trait-label">{escape(t['label'])}</span>
            <span class="trait-value">{escape(val_txt)}</span>
          </div>
          <div class="trait-bar">
            <i style="width:{pos:.1f}%"></i>
            <b class="trait-thresh" style="left:{th_pos:.1f}%"></b>
          </div>
          <div class="trait-meta">
            <span>{escape(th_txt)}</span>
            <span class="trait-cmp">{escape(t['comparator'])}</span>
          </div>
          <p class="trait-rule">{escape(t['rule'])}</p>
          <details class="trace">
            <summary>↺ 依据（{len(ev)} 条）</summary>
            <pre>{escape(ev_preview)}</pre>
          </details>
        </div>""")

    return f"""
    <div class="traits">{''.join(cards)}</div>
    <p class="disclaimer">{escape(profile['disclaimer'])}</p>
    <p class="muted small">注：{escape(profile['note'])}</p>"""


def data_gaps_panel(gaps: List[Dict[str, Any]]) -> str:
    """数据缺口面板：如实说明哪些指标接口未提供，以及我们如何处理。"""
    if not gaps:
        return ""
    rows = "".join(f"""
      <div class="gap-card">
        <div class="gap-field">未提供：<code>{escape(g['field'])}</code></div>
        <div class="gap-line"><span class="gap-k">影响</span>{escape(g['impact'])}</div>
        <div class="gap-line"><span class="gap-k">原因</span>{escape(g['reason'])}</div>
        <div class="gap-line"><span class="gap-k">处理</span>{escape(g['handling'])}</div>
      </div>""" for g in gaps)
    return f"""
    <section>
      <h2><span class="idx">!</span>数据可得性说明</h2>
      <p class="muted small">
        本页基于你在麦当劳的真实消费记录生成。以下指标在数据源中<strong>没有提供</strong>，
        因此我们<strong>不计算、也不猜</strong> —— 这比硬凑一个好看的数字更诚实。
      </p>
      <div class="gaps">{rows}</div>
    </section>"""


def coupon_view(c: Dict[str, Any]) -> str:
    if not c:
        return ""
    rows = []
    for r in c["priority_list"]:
        left = "已过期" if (r["days_left"] is not None and r["days_left"] < 0) else \
               (f"{r['days_left']}天" if r["days_left"] is not None else "—")
        flag = "bad" if not r["redeemable_in_store"] else ("warn" if r["urgency"] >= 1.0 else "ok")
        rows.append(f"""
        <tr class="{flag}">
          <td>{escape(r['name'])}</td>
          <td>{_money(r['face_value'])}</td>
          <td>{('满' + str(int(r['threshold']))) if r['threshold'] else '无门槛'}</td>
          <td>{left}</td>
          <td>{r['efficiency'] if r['efficiency'] < 90 else '极高'}</td>
          <td class="muted">{escape(r['action'])}</td>
        </tr>""")
    return f"""
    <p class="muted small">券面值合计 {_money(c['total_face_value'])}，其中 7 天内到期 {len(c['expiring_within_7d'])} 张、
    已过期 {c['expired_count']} 张、当前门店不可用 {c['store_unavailable_count']} 张。
    门槛效率 = 面额 ÷ 门槛；"典型消费"取值 = 你的历史订单实付中位数 {_money(c['trace']['typical_order_payable'])}。</p>
    {trace_panel(c['trace'], '券资产的算法口径')}
    <table class="tbl">
      <thead><tr><th>券</th><th>面额</th><th>门槛</th><th>剩余</th><th>门槛效率</th><th>建议</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def playbook_view(pb: Dict[str, Any]) -> str:
    if not pb or not pb.get("actions"):
        return '<p class="muted">暂无可执行建议。</p>'
    cards = []
    for a in pb["actions"]:
        saving = f'<span class="save-tag">可省 {_money(a["est_saving"])}</span>' if a.get("est_saving") else \
                 '<span class="save-tag ghost">情景估算</span>'
        assumption = f'<p class="assume">估算前提：{escape(a["assumption"])}</p>' if a.get("assumption") else ""
        confirm = '<span class="need-confirm">需你确认后才执行</span>' if a.get("needs_confirmation") else ""
        cards.append(f"""
        <div class="action-card">
          <div class="action-head"><b>{escape(a['title'])}</b>{saving}</div>
          <p class="muted">{escape(a['reason'])}</p>
          {assumption}{confirm}
          {trace_panel(a.get('evidence', {}), '依据')}
        </div>""")
    return f"""
    <div class="actions">{''.join(cards)}</div>
    <p class="disclaimer">{escape(pb['disclaimer'])}</p>
    <p class="total-save">合计可量化估算：<b>{_money(pb['estimated_total_saving'])}</b></p>"""


# ---------------------------------------------------------------------------
# 主模板
# ---------------------------------------------------------------------------

CSS = """
:root{
  --bg:#f6f7f9; --panel:#ffffff; --fg:#1a1c1f; --muted-fg:#6b7280;
  --accent:#d92b2b; --accent-soft:#f9dcdc; --line:#e5e7eb; --warn:#b45309; --ok:#15803d;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:820px;margin:0 auto;padding:28px 20px 80px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:30px 28px;margin-bottom:18px}
.hero h1{margin:0 0 6px;font-size:27px;letter-spacing:-0.5px}
.hero .sub{color:var(--muted-fg);font-size:13px;margin:0}
.badge{display:inline-block;background:var(--accent-soft);color:var(--accent);
  font-size:12px;padding:3px 10px;border-radius:999px;margin-bottom:12px;font-weight:600}
.mockwarn{background:#fff7ed;border:1px solid #fed7aa;color:var(--warn);
  border-radius:10px;padding:10px 14px;font-size:13px;margin-bottom:18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.kpi{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px}
.kpi .num{font-size:22px;font-weight:700;letter-spacing:-0.5px}
.kpi .lbl{font-size:12px;color:var(--muted-fg)}
section{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px 26px;margin-bottom:18px}
h2{font-size:17px;margin:0 0 4px;letter-spacing:-0.2px}
h2 .idx{color:var(--accent);margin-right:8px;font-weight:800}
.narrative{font-size:15px;background:var(--accent-soft);border-left:3px solid var(--accent);
  padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0}
.muted{color:var(--muted-fg)}
.small{font-size:13px}
.bars{margin-top:12px}
.bar-row{display:grid;grid-template-columns:96px 1fr 84px;align-items:center;gap:10px;margin:7px 0;font-size:13px}
.bar-label{color:var(--muted-fg);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{background:var(--bg);border-radius:6px;height:16px;overflow:hidden;border:1px solid var(--line)}
.bar-track i{display:block;height:100%}
.bar-value{font-variant-numeric:tabular-nums}
.tbl{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}
.tbl th,.tbl td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left}
.tbl th{color:var(--muted-fg);font-weight:600;font-size:12px}
.tbl tr.warn{background:#fffbeb}
.tbl tr.bad{background:#fef2f2;color:var(--muted-fg)}
.drift{margin-top:10px}
.drift-row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line);font-size:13px}
.drift-nums{font-variant-numeric:tabular-nums;color:var(--muted-fg)}
.drift-nums em{font-style:normal;margin-left:8px}
em.up{color:var(--accent)} em.down{color:var(--ok)} em.flat{color:var(--muted-fg)}
.trace{margin-top:10px;font-size:12px}
.trace summary{cursor:pointer;color:var(--accent);user-select:none}
.trace pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;
  padding:10px;overflow:auto;max-height:240px;font-size:11px;line-height:1.5}
.actions{display:grid;gap:12px;margin-top:12px}
.action-card{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px}
.action-head{display:flex;justify-content:space-between;align-items:center;gap:10px}
.save-tag{background:var(--accent);color:#fff;font-size:12px;padding:2px 9px;border-radius:999px;white-space:nowrap}
.save-tag.ghost{background:var(--line);color:var(--muted-fg)}
.need-confirm{display:inline-block;font-size:11px;color:var(--warn);border:1px dashed var(--warn);
  border-radius:6px;padding:1px 7px;margin-top:6px}
.assume{font-size:12px;color:var(--muted-fg);margin:6px 0 0}
.disclaimer{font-size:12px;color:var(--muted-fg);border-top:1px dashed var(--line);padding-top:10px}
.total-save{margin-top:12px;font-size:14px}
.linechart{width:100%;height:auto;margin-top:10px}
.foot{text-align:center;color:var(--muted-fg);font-size:12px;padding:20px 0}
.checkbox{font-size:12px;color:var(--ok)}
.realnote{background:#f0fdf4;border:1px solid #bbf7d0;color:var(--ok);
  border-radius:10px;padding:10px 14px;font-size:13px;margin-bottom:18px}
.gaps{display:grid;gap:10px;margin-top:12px}
.gap-card{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;font-size:13px}
.gap-field{font-weight:600;margin-bottom:6px}
.gap-field code{background:#fef3c7;padding:1px 6px;border-radius:4px;font-size:12px}
.gap-line{color:var(--muted-fg);margin:3px 0}
.gap-k{display:inline-block;width:34px;color:var(--warn);font-weight:600}
.nowrap{white-space:nowrap}
td.num{font-variant-numeric:tabular-nums}
.traits{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:14px}
.trait-card{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px}
.trait-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.trait-label{font-weight:700;font-size:14px}
.trait-value{font-variant-numeric:tabular-nums;color:var(--accent);font-size:13px;font-weight:600}
.trait-bar{position:relative;height:8px;background:var(--line);border-radius:5px;margin:10px 0 4px}
.trait-bar i{position:absolute;left:0;top:0;height:100%;background:var(--accent);border-radius:5px}
.trait-thresh{position:absolute;top:-3px;width:2px;height:14px;background:var(--fg);opacity:.55}
.trait-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--muted-fg);margin-bottom:6px}
.trait-cmp{font-family:ui-monospace,monospace}
.trait-rule{font-size:12px;color:var(--muted-fg);margin:6px 0 0}
.persona-sum{font-size:16px;font-weight:600;background:var(--accent-soft);
  border-left:3px solid var(--accent);padding:11px 15px;border-radius:0 8px 8px 0;margin:10px 0 4px}
"""


def order_table(orders: List[Order]) -> str:
    """真实数据下的订单明细表，每行可展开看到回溯信息。"""
    if not orders:
        return '<p class="muted">无订单。</p>'
    rows = []
    for o in sorted(orders, key=lambda x: x.ts, reverse=True):
        subs = "、".join(f"{i.name}×{i.qty}" for i in o.items)
        rows.append(f"""
        <tr>
          <td class="nowrap">{o.ts.strftime('%Y-%m-%d %H:%M')}</td>
          <td>{escape(o.store_name)}</td>
          <td class="num">{_money(o.payable)}</td>
          <td class="muted small">{escape(subs)}</td>
        </tr>""")
    return f"""
    <table class="tbl">
      <thead><tr><th>下单时间</th><th>门店</th><th>实付</th><th>商品（套餐子项）</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    {trace_panel({'formula': '实付 = 订单实付金额原值，未做任何换算',
                  'sources': [o.order_no for o in orders]}, '全部订单号')}"""


def real_coupon_view(coupons: List[Dict[str, Any]], today: date) -> str:
    """真实数据下的券视图：数据源只给用券价+有效期+限用标签，就只展示这些。"""
    if not coupons:
        return '<p class="muted">当前账户没有可用优惠券。</p>'
    rows = []
    for c in coupons:
        try:
            exp = date.fromisoformat(c["validTo"])
            days = (exp - today).days
        except Exception:
            days = None
        if days is None:
            left, cls = "—", ""
        elif days < 0:
            left, cls = "已过期", "bad"
        elif days <= 2:
            left, cls = f"{days}天", "warn"
        elif days <= 5:
            left, cls = f"{days}天", ""
        else:
            left, cls = f"{days}天", ""
        tags = "、".join(c.get("tags", [])) or "—"
        rows.append(f"""
        <tr class="{cls}">
          <td>{escape(c['name'])}</td>
          <td>{_money(float(c.get('price') or 0))}</td>
          <td>{c.get('validFrom','')} ~ {c.get('validTo','')}</td>
          <td>{escape(left)}</td>
          <td class="muted small">{escape(tags)}</td>
        </tr>""")
    return f"""
    <p class="muted small">共 {len(coupons)} 张可用券。"价格"为券的<strong>用券价（券后价）</strong>，
    非面额 —— 面额需原价才能推算，而原价未提供，故不展示。</p>
    <table class="tbl">
      <thead><tr><th>券名称</th><th>用券价</th><th>有效期</th><th>剩余</th><th>限用</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def render_html(report: Dict[str, Any], orders: List[Order], mock: bool = True,
                gaps: List[Dict[str, Any]] | None = None,
                raw_coupons: List[Dict[str, Any]] | None = None,
                raw_account: Dict[str, Any] | None = None) -> str:
    s = report["summary"]
    meta = report["meta"]
    check = self_check(orders)

    if s.get("empty"):
        kpis = '<div class="kpi"><div class="num">—</div><div class="lbl">本年度暂无订单</div></div>'
        body_core = '<section><h2><span class="idx">i</span>暂无数据</h2><p class="muted">账户在本年度没有可统计的订单记录。本工具不会编造任何数字。</p></section>'
    elif mock:
        # ---- 演示模式：mock 数据字段完整，展示全部分析 ----
        kpis = f"""
        <div class="kpi"><div class="num">{s['order_count']}</div><div class="lbl">全年订单数</div></div>
        <div class="kpi"><div class="num">{_money(s['paid'])}</div><div class="lbl">实付总额</div></div>
        <div class="kpi"><div class="num">{_money(s['saved'])}</div><div class="lbl">总共省下</div></div>
        <div class="kpi"><div class="num">{_money(s['aov'])}</div><div class="lbl">客单价</div></div>
        <div class="kpi"><div class="num">{_pct(s['discount_rate'])}</div><div class="lbl">综合折扣率</div></div>
        <div class="kpi"><div class="num">{s['coupon_order_count']}</div><div class="lbl">用券订单数</div></div>"""
        top_items = {i["name"]: float(i["qty"]) for i in s["top_items"]}
        cat = s["category_amount"]
        body_core = f"""
        <section>
          <h2><span class="idx">01</span>总账</h2>
          <p class="muted small">口径：原价 = 商品价 + 配送费；省下 = 原价 − 实付；折扣率 = 优惠 ÷ 原价。</p>
          {trace_panel(s['trace'].get('paid'), '实付总额的构成')}
          {trace_panel(s['trace'].get('saved'), '省下总额的构成')}
        </section>

        <section>
          <h2><span class="idx">02</span>你都在点什么</h2>
          <p class="muted small">按累计点单量排序（数量相同则按消费金额排序）。</p>
          {bar_chart(top_items)}
          <h2 style="margin-top:22px;font-size:15px">品类结构（按金额）</h2>
          {bar_chart(cat, 'var(--accent-soft)')}
        </section>

        <section>
          <h2><span class="idx">03</span>钱花在哪个月</h2>
          <p class="muted small">月度实付轨迹。鼠标悬停可对照季度表阅读。</p>
          {line_chart(report['monthly'])}
          {quarterly_table(report['quarterly'])}
          {trace_panel(report['quarterly'][0]['trace'], 'Q1 的订单来源（其余季度同理）')}
        </section>

        <section>
          <h2><span class="idx">04</span>这一年你变了什么口味</h2>
          <p class="muted small">上半年 vs 下半年的品类占比对比 —— 这是"截面统计"看不到的东西。</p>
          {drift_view(report['flavor_drift'])}
          {trace_panel(report['flavor_drift']['trace'], '口味漂移的计算口径')}
        </section>

        <section>
          <h2><span class="idx">05</span>你的行为画像</h2>
          <p class="persona-sum">{escape(report['behavior']['summary'])}</p>
          <p class="muted small">
            这些是<strong>行为习惯</strong>，不是性格判断。每个结论下方都有可展开的判定规则与支撑订单，
            你可以核验，也可以反驳。
          </p>
          {behavior_view(report['behavior'])}
        </section>"""
    else:
        # ---- 真实模式：只有真实可得的指标才展示 ----
        kpis = f"""
        <div class="kpi"><div class="num">{s['order_count']}</div><div class="lbl">订单数</div></div>
        <div class="kpi"><div class="num">{_money(s['paid'])}</div><div class="lbl">实付总额</div></div>
        <div class="kpi"><div class="num">{_money(s['aov'])}</div><div class="lbl">客单价</div></div>
        <div class="kpi"><div class="num">{s['order_count'] and len(s['store_distribution']) or 0}</div><div class="lbl">去过的门店数</div></div>"""

        # 门店分布
        store_bar = bar_chart({k: float(v) for k, v in s["store_distribution"].items()}) \
            if s.get("store_distribution") else '<p class="muted">无</p>'
        # 单品分布（按数量，均摊口径）
        top_items = {i["name"]: float(i["qty"]) for i in s["top_items"]}
        # 月度轨迹
        monthly_line = line_chart(report["monthly"])

        body_core = f"""
        <section>
          <h2><span class="idx">01</span>总账</h2>
          <p class="muted small">
            口径：实付金额直接来自订单记录，可信。
            原价 / 优惠 / 配送费未提供，故本页不展示"省下金额"等衍生指标。
          </p>
          {trace_panel(s['trace'].get('paid'), '实付总额的构成（逐单可溯）')}
        </section>

        <section>
          <h2><span class="idx">02</span>订单明细</h2>
          <p class="muted small">每笔订单都可点开回溯，看到构成它的原始订单号与商品子项。</p>
          {order_table(orders)}
        </section>

        <section>
          <h2><span class="idx">03</span>你点过的单品</h2>
          <p class="muted small">
            按累计件数排序。注意：明细只到套餐子项、不含单项价格，
            故此处只统计<strong>件数</strong>，不展示金额。
          </p>
          {bar_chart(top_items)}
        </section>

        <section>
          <h2><span class="idx">04</span>去过的门店</h2>
          {store_bar}
          {trace_panel({"formula": "按订单归属门店计数", "sources": [o.order_no for o in orders]},
                       '门店分布的来源订单')}
        </section>

        <section>
          <h2><span class="idx">05</span>消费轨迹</h2>
          <p class="muted small">月度实付。订单较少时轨迹不连续属正常现象。</p>
          {monthly_line}
        </section>

        <section>
          <h2><span class="idx">06</span>你的行为画像</h2>
          <p class="persona-sum">{escape(report['behavior']['summary'])}</p>
          <p class="muted small">
            这些是<strong>行为习惯</strong>，不是性格判断。每个结论下方都有可展开的判定规则与支撑订单，
            你可以核验，也可以反驳。
          </p>
          {behavior_view(report['behavior'])}
        </section>"""

    coupon_html = ""
    if not mock and raw_coupons is not None:
        coupon_html = f"""
        <section>
          <h2><span class="idx">07</span>券资产</h2>
          {real_coupon_view(raw_coupons, date(2026, 10, 10))}
        </section>"""
    elif report.get("coupons"):
        coupon_html = f"""
        <section>
          <h2><span class="idx">06</span>券资产清算</h2>
          <p class="muted small">不只列出券，而是算出"哪张该尽快用、哪张够不到门槛"。</p>
          {coupon_view(report.get('coupons'))}
        </section>"""

    playbook_html = ""
    if mock and report.get("playbook"):
        playbook_html = f"""
        <section>
          <h2><span class="idx">07</span>明年的钱可以怎么花</h2>
          <p class="muted small">分析 → 决策 → 履约。每条建议都可回溯依据，涉及花钱的动作一律等你确认。</p>
          {playbook_view(report.get('playbook'))}
        </section>"""

    points_html = ""
    if not mock and raw_account:
        acct = raw_account
        points_html = f"""
        <section>
          <h2><span class="idx">08</span>积分账户</h2>
          <table class="tbl">
            <tbody>
              <tr><td>可用积分</td><td><b>{acct.get('availablePoint','—')}</b></td></tr>
              <tr><td>累计积分</td><td>{acct.get('accumulativePoint','—')}</td></tr>
              <tr><td>已使用</td><td>{acct.get('usedPoint','—')}</td></tr>
              <tr><td>已过期</td><td class="muted">{acct.get('expiredPoint','—')}</td></tr>
              <tr><td>冻结</td><td>{acct.get('frozenPoint','—')}</td></tr>
              <tr><td>本月将过期</td><td>{acct.get('currentMouthExpirePoint','—')}</td></tr>
            </tbody>
          </table>
        </section>"""
    else:
        p = report.get("points")
        if p:
            exp = f"，其中 {p['expiring_soon']} 分将于 {p['expiring_at']} 过期" if p.get("expiring_soon") else ""
            points_html = f"""
            <section>
              <h2><span class="idx">08</span>积分账户</h2>
              <p>可用 <b>{p['available']:,}</b> 分，累计获得 {p['total_earned']:,} 分{escape(exp)}。</p>
            </section>"""

    gaps_html = data_gaps_panel(gaps or []) if not mock else ""

    mock_banner = ('<div class="mockwarn">⚠️ 当前展示的是 <b>演示数据</b>，'
                   '不是你的真实账户数据。接入麦当劳账号后运行即切换为真实数据。</div>') if mock else \
                  ('<div class="realnote">✓ 本页基于你的<b>真实消费记录</b>生成，'
                   '所有数字均来自原始订单，未做任何修饰。</div>')

    verify = "✅ 全部通过" if check["all_pass"] else "❌ 存在偏差，请检查"
    # 真实模式下，若金额拆分字段整体缺失（省下/折扣率恒为 0），
    # 不应把这些"恒为0"的项列为通过，否则会被误读成"省下 0 元"这一真实结论。
    if not mock and orders and all(o.discount == 0 and o.delivery_fee == 0 for o in orders):
        skip_names = {"省下总额"}
        shown = [c for c in check["checks"] if c["name"] not in skip_names]
        skipped = [c for c in check["checks"] if c["name"] in skip_names]
    else:
        shown, skipped = check["checks"], []

    detail = "".join(
        f'<div>{escape(c["name"])}：手算 {c["manual"]} / 引擎 {c["engine"]} '
        f'<span class="{"checkbox" if c["pass"] else "muted"}">{"✓" if c["pass"] else "✗"}</span></div>'
        for c in shown)
    if skipped:
        detail += "".join(
            f'<div class="muted">{escape(c["name"])}：<i>数据未提供原价与优惠拆分，该项不适用</i></div>'
            for c in skipped)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(meta['title'])} · {escape(meta['owner'])}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <span class="badge">MCD ANNUAL REPORT</span>
    <h1>{escape(meta['title'])}</h1>
    <p class="sub">{escape(meta['owner'])} · 生成于 {escape(meta['generated_at'])} · 数据范围：{escape(meta['data_scope'])}</p>
    <div class="kpis">{kpis}</div>
  </div>

  {mock_banner}
  {body_core}
  {coupon_html}
  {playbook_html}
  {points_html}
  {gaps_html}

  <section>
    <h2><span class="idx">✓</span>可手算校验</h2>
    <p class="muted small">本工具的承诺：年报里每个数字都能用计算器复算。下面是引擎输出与独立手算的比对结果。</p>
    <p><b>{verify}</b></p>
    {detail}
  </section>

  <div class="foot">
    麦麦年度报告 MCD Annual Report · 基于麦当劳中国官方 MCP 开发 · 使用腾讯 WorkBuddy 完成<br>
    本作品由水牛先生开发，请勿盗用<br>
    本项目为参赛作品，非麦当劳官方产品。输出仅供参考，不构成营养或医疗建议；实际价格与优惠以麦当劳官方实时结果为准。
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def generate(output: str = "annual_report.html", mock: bool = True,
             orders: List[Order] | None = None,
             coupons: List[Coupon] | None = None,
             points: PointsAccount | None = None,
             year: int | None = None, owner: str = "麦门用户",
             today: date | None = None,
             gaps: List[Dict[str, Any]] | None = None,
             raw_coupons: List[Dict[str, Any]] | None = None,
             raw_account: Dict[str, Any] | None = None) -> str:
    if orders is None:
        from mock_loader import (load_mock_coupons, load_mock_orders,
                                 load_mock_points)
        orders = load_mock_orders()
        coupons = coupons if coupons is not None else load_mock_coupons()
        points = points if points is not None else load_mock_points()

    report = build_annual_report(orders, coupons or [], points,
                                 year=year, owner=owner, today=today)
    html = render_html(report, orders, mock=mock, gaps=gaps,
                       raw_coupons=raw_coupons, raw_account=raw_account)

    out_path = output if os.path.isabs(output) else os.path.join(os.getcwd(), output)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 同时导出结构化 JSON，便于二次消费与审计
    json_path = os.path.splitext(out_path)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[OK] HTML  → {out_path}")
    print(f"[OK] JSON → {json_path}")
    print(f"[OK] 自检 → {'全部通过' if self_check(orders)['all_pass'] else '存在偏差'}")
    return out_path


if __name__ == "__main__":
    generate(output=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "annual_report.demo.html"),
             mock=True, year=2026, owner="演示用户",
             today=date(2026, 10, 9))
