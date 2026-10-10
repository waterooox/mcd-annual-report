#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
叙事版年报渲染器（麦当劳品牌设计语言）
========================================

外壳：全屏分屏滚动，一屏一个结论，滚动时逐屏揭晓。
内核：文案只呈现结论本身，不夹杂公式与依据面板 —— 保持"年度回顾"的沉浸感。
      需要逐条核对数字的场景，交由报告版（render_report.py）承担，
      叙事与可核对各司其职，互不打扰。

【品牌视觉的三层构造】—— 全部由代码生成，不使用任何官方图片素材

1. 符号层：**金拱门**（Golden Arches）。
   用两段二次贝塞尔圆弧 + `stroke-linecap:butt`（垂直切边）+ 错位半格构造，
   与麦当劳商标在数学构造上同源，但完全是本项目代码绘制的矢量图形。
   开场屏与结尾屏以「品牌签名」级别的大尺寸出现，其余屏作为小尺寸水印。

2. 色彩层：官方主色 **红 #DA291C / 黄 #FFC72C**，
   暖白底 #FFFBF5（而非纯白），大色块 + 高对比，符合快餐品牌的视觉冲击力。

3. 排版层：粗壮字重（800）、负字距、大号数字、
   胶囊标签（pill chip）、黄色下划线强调条 —— 麦当劳广告物料里的常见语汇。

商品图仅为局部点缀，且**必须带 onerror 降级**：
接口返回的图片 URL 带签名会过期，加载失败时自动退回品牌色块，
避免出现破损图片图标。零第三方依赖，纯 CSS/SVG。
"""

from __future__ import annotations

import json
import os
from datetime import date
from html import escape
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# 金拱门：纯代码绘制的品牌符号
# ---------------------------------------------------------------------------

# 单拱路径：从 (3,60) 经控制点 (28,-14) 到 (53,60)。
# stroke-linecap:butt 让两端垂直切齐 —— 这是金拱门与普通圆弧的关键区别。
# 第二个拱整体 translate(0,58) 后落点相同，因此两弧共底、视觉上连成一体。
_ARCH_PATH = "M3,60 Q28,-14 53,60"
_ARCH_PATH_2 = "M55,2 Q80,-72 105,2"
_ARCH_TRANSFORM = "translate(0,58)"


def check_arch_consistency() -> None:
    """校验金拱门几何常量自洽：第二拱必须以 translate(0,58) 落到第一拱同一基线。

    SVG 与分享卡（Canvas Path2D）共用这两个路径字符串，
    所以只要这里断言通过，两边的造型就不可能跑偏。
    """
    def _nums(path: str):
        seg = path[1:].replace("Q", " ").replace(",", " ").split()
        return [float(v) for v in seg]

    a = _nums(_ARCH_PATH)     # move(3,60)  → quad(28,-14, 53,60)
    b = _nums(_ARCH_PATH_2)   # move(55,2)  → quad(80,-72, 105,2)
    dy = a[1] - b[1]
    assert dy == 58, f"金拱门第二拱偏移应为 58，实际 {dy}"
    assert f"translate(0,{dy:g})" == _ARCH_TRANSFORM, \
        f"_ARCH_TRANSFORM 与路径偏移不一致：{_ARCH_TRANSFORM} vs {dy}"
    assert b[4] <= 108 and a[1] <= 66, "金拱门超出 viewBox 0 0 108 66"


def golden_arches(size: str = "96px", color: str = "currentColor",
                  opacity: float = 1.0, width: float = 12.5,
                  cls: str = "ga") -> str:
    """
    金拱门符号（标题级，用于开场/结尾屏的品牌签名）。

    size 传 CSS 长度，如 "min(38vw,260px)"；color 传任何 CSS 颜色。
    """
    return (
        f'<svg class="{escape(cls)}" viewBox="0 0 108 66" '
        f'width="{escape(size)}" aria-hidden="true" '
        f'style="opacity:{opacity};color:{escape(color)}">'
        f'<g fill="none" stroke="currentColor" stroke-width="{width}" '
        'stroke-linecap="butt">'
        f'<path d="{_ARCH_PATH}"/><path d="{_ARCH_PATH_2}" transform="translate(0,58)"/>'
        '</g></svg>'
    )


def arch_watermark(size: str = "120px", opacity: float = 0.06) -> str:
    """每屏右上角的金拱门水印（弱化，不抢正文）。"""
    return golden_arches(size=size, opacity=opacity, cls="ga wm")


def arch_divider(color: str = "var(--brand-red)", opacity: float = 0.9) -> str:
    """金拱门分隔条：小尺寸居中，作为章节之间的品牌呼吸。"""
    return golden_arches(size="46px", color=color, opacity=opacity, cls="ga div")


# ---------------------------------------------------------------------------
# 样式：品牌设计语言
# ---------------------------------------------------------------------------

STORY_CSS = """
:root{
  /* 麦当劳官方主色 */
  --brand-red:#DA291C;
  --brand-yellow:#FFC72C;
  --brand-red-deep:#A81C11;
  --brand-brown:#2A1F1A;

  --bg:#FFFBF5;              /* 暖白底，不是纯白 */
  --bg-alt:#FFF6E9;
  --bg-tint:#FFF1DC;         /* 更暖的强调底 */

  --fg:#2A1F1A;
  --muted:#8A7A6E;
  --accent:var(--brand-red);
  --card:rgba(255,255,255,.78);
  --line:rgba(42,31,26,.12);
  --shadow:0 8px 30px rgba(160,110,60,.11);
  --shadow-lg:0 18px 50px rgba(160,110,60,.16);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
              "Hiragino Sans GB","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased;overflow-x:hidden;
}

/* ===============================================================
   符号层：金拱门
   =============================================================== */
.ga{display:block;flex:0 0 auto}
.ga.wm{position:absolute;top:7vh;right:6vw;pointer-events:none}
.ga.div{margin:20px 0 6px}
.arches-hero{
  display:flex;justify-content:center;align-items:center;
  margin-bottom:clamp(10px,2.4vh,26px);
  filter:drop-shadow(0 10px 26px rgba(218,41,28,.22));
}
/* 开场屏的金拱门为黄色：
   在暖白底上纯黄容易发飘，所以用「白描边 + 暖黄投影」把它从背景里托起来，
   投影同步换成暖黄色调，避免红色阴影与黄弧打架。 */
.scene.hero .arches-hero{
  filter:
    drop-shadow(0 0 2.5px rgba(255,255,255,.95))
    drop-shadow(0 10px 26px rgba(176,122,0,.34));
}
.arches-hero .ga{
  animation:archIn .95s cubic-bezier(.22,1,.36,1) both;
}
@keyframes archIn{
  from{opacity:0;transform:translateY(22px) scale(.9)}
  to{opacity:1;transform:none}
}

/* ===============================================================
   背景：自制几何纹理（品牌联想，无版权风险）
   =============================================================== */
.scene{
  min-height:100vh;display:flex;flex-direction:column;justify-content:center;
  padding:11vh 7vw 9vh;position:relative;overflow:hidden;
  cursor:pointer;
  border-bottom:1px solid rgba(218,41,28,.07);
  background-image:
    /* 薯条：细长黄条 */
    linear-gradient(90deg, transparent 0 96%, rgba(255,199,44,.26) 96% 100%),
    /* 汉堡：横向层次 */
    linear-gradient(180deg,
      rgba(218,41,28,.045) 0 2px, transparent 2px 34px,
      rgba(255,199,44,.06) 34px 36px, transparent 36px 70px),
    /* 网点 */
    radial-gradient(circle, rgba(218,41,28,.05) 1.5px, transparent 1.5px);
  background-size: 78px 100%, 100% 70px, 27px 27px;
}
.scene:nth-child(even){background-color:var(--bg-alt)}
.scene::before{
  content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(circle at 16% 10%, rgba(255,199,44,.24), transparent 52%),
             radial-gradient(circle at 90% 88%, rgba(218,41,28,.09), transparent 50%);
}
/* 开场/结尾屏：品牌色块压顶，做"签名屏" */
.scene.hero{
  background-color:var(--bg-tint);
  background-image:
    linear-gradient(180deg, var(--brand-red) 0 10px, transparent 10px),
    /* 光晕从 .30 降到 .16：金拱门本身是黄色，背景再压一层黄会糊在一起 */
    radial-gradient(circle at 50% 26%, rgba(255,199,44,.16), transparent 58%);
}
.scene.hero::before{background:none}
/* 开场屏右下角版权署名 */
.credit{
  position:absolute;right:20px;bottom:16px;z-index:5;
  font-size:11px;letter-spacing:.03em;color:var(--muted);
}
.scene.finale{
  background-color:var(--brand-brown);
  background-image:
    radial-gradient(circle at 84% 16%, rgba(255,199,44,.16), transparent 56%),
    radial-gradient(circle at 12% 92%, rgba(218,41,28,.30), transparent 54%);
  color:#FFF6E9;
}
.scene.finale .kicker{color:var(--brand-yellow)}
.scene.finale .kicker::after{background:var(--brand-red)}
.scene.finale .big{color:var(--brand-yellow)}
.scene.finale .lines p{color:#F3E3D2;background:rgba(255,255,255,.07)}
.scene.finale .lines p.small{color:#C9B2A0}
.scene.finale .formula{color:#E8C98F;background:rgba(255,199,44,.13)}

/* ===============================================================
   排版层
   =============================================================== */
.kicker{
  font-size:12.5px;letter-spacing:.26em;color:var(--brand-red);
  text-transform:uppercase;margin-bottom:24px;font-weight:800;
  display:inline-block;position:relative;padding-left:2px;
}
.kicker::after{
  content:"";position:absolute;left:2px;bottom:-8px;width:38px;height:4px;
  background:var(--brand-yellow);border-radius:2px;
}
.big{
  font-size:clamp(40px,8.6vw,88px);font-weight:800;line-height:1.05;
  letter-spacing:-.035em;margin-bottom:22px;color:var(--brand-red-deep);
}
.big.plain{color:var(--fg)}
.big.hero-name{
  font-size:clamp(34px,7vw,72px);letter-spacing:-.02em;
}
.big .unit{
  display:block;font-size:clamp(13px,1.8vw,16px);font-weight:700;
  letter-spacing:.2em;color:var(--muted);margin-top:10px;
  text-transform:uppercase;
}
.lines{display:flex;flex-direction:column;gap:11px;max-width:680px}
.lines p{
  font-size:clamp(15px,2.3vw,18.5px);line-height:1.78;color:#4A3B33;
  background:var(--card);border-radius:14px;padding:10px 16px;
  border-left:3px solid rgba(255,199,44,.85);
  backdrop-filter:blur(3px);
}
.lines p.small{font-size:13.5px;color:var(--muted);border-left-color:rgba(218,41,28,.28)}

/* 规则列表：行为画像的判定规则，用紧凑的行式排版而非卡片 */
.rules{
  display:grid;gap:7px;margin-top:18px;max-width:720px;
}
.rules li{
  list-style:none;font-size:12.8px;line-height:1.62;color:#5A4A40;
  background:rgba(255,255,255,.62);border-radius:10px;
  padding:8px 13px 8px 34px;position:relative;
  border:1px solid rgba(218,41,28,.10);
}
.rules li::before{
  content:"";position:absolute;left:13px;top:14px;
  width:9px;height:9px;border-radius:50%;
  background:var(--brand-yellow);
  box-shadow:0 0 0 2.5px rgba(218,41,28,.16);
}
.rules li.hit{
  background:rgba(255,199,44,.16);border-color:rgba(218,41,28,.28);
  color:#3A2C24;font-weight:600;
}
.rules li.hit::before{background:var(--brand-red);box-shadow:0 0 0 2.5px rgba(218,41,28,.22)}
.formula{
  margin-top:16px;font-size:12px;color:#9A7B5E;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  background:rgba(255,199,44,.18);border-left:3px solid var(--brand-yellow);
  padding:8px 13px;border-radius:0 9px 9px 0;display:inline-block;
  line-height:1.6;
}

/* 胶囊标签：麦当劳广告里常见的语汇 */
.trait-mini{display:flex;flex-wrap:wrap;gap:9px;margin-top:20px}
.trait-mini span{
  font-size:13px;font-weight:600;background:#fff;
  border:1.5px solid rgba(218,41,28,.24);
  border-radius:999px;padding:7px 15px;color:#5A4A40;
  box-shadow:0 3px 10px rgba(160,110,60,.08);
}
.trait-mini span.on{
  border-color:var(--brand-red);background:var(--brand-red);
  color:#fff;box-shadow:0 5px 16px rgba(218,41,28,.28);
}

/* 顶部导航条：品牌红压顶 + 金色拱门 */
.topbar{
  position:fixed;top:0;left:0;right:0;z-index:25;height:52px;
  display:flex;align-items:center;gap:12px;padding:0 20px;
  background:linear-gradient(90deg,var(--brand-red),var(--brand-red-deep));
  box-shadow:0 3px 18px rgba(168,28,17,.24);
}
.topbar .brand{
  color:#fff;font-weight:800;font-size:15.5px;letter-spacing:.02em;
  display:flex;align-items:baseline;gap:8px;
}
.topbar .brand em{
  font-style:normal;font-weight:600;font-size:11px;color:rgba(255,255,255,.72);
  letter-spacing:.16em;
}
.topbar .backbtn{
  cursor:pointer;border:none;background:rgba(255,255,255,.16);
  color:#fff;font-size:16px;font-weight:800;width:34px;height:34px;
  border-radius:10px;display:flex;align-items:center;justify-content:center;
  transition:.15s;flex:0 0 auto;padding:0;
}
.topbar .backbtn:hover{background:var(--brand-yellow);color:#7A2E00}
.topbar .backbtn:disabled{opacity:.3;cursor:default;background:rgba(255,255,255,.16);color:#fff}

.scrollhint{
  position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
  font-size:11.5px;color:#fff;letter-spacing:.18em;z-index:10;font-weight:700;
  background:var(--brand-red);border-radius:999px;padding:8px 18px;
  box-shadow:0 6px 22px rgba(218,41,28,.34);animation:bob 1.9s ease-in-out infinite;
}
.scrollhint.off{animation:none;opacity:0;pointer-events:none;transition:opacity .35s}

/* ===============================================================
   署名输入层：首次打开请用户留名（localStorage 记住，点击开场屏名字可改）
   =============================================================== */
.name-overlay{
  position:fixed;inset:0;z-index:60;
  display:flex;align-items:center;justify-content:center;
  background:rgba(38,24,14,.46);backdrop-filter:blur(6px);
  opacity:0;visibility:hidden;transition:opacity .35s, visibility .35s;
}
.name-overlay.show{opacity:1;visibility:visible}
.name-card{
  background:var(--bg);border-radius:24px;padding:32px 30px 26px;
  max-width:min(88vw,420px);width:88vw;text-align:center;
  box-shadow:0 30px 80px rgba(30,15,5,.42);
  border-top:6px solid var(--brand-red);
}
.name-card .ga{margin:0 auto 6px}
/* 署名层的金拱门为黄色：白底上纯黄会发飘，用暖黄描边 + 轻投影托底 */
.name-card .arches-hero,
.name-card .ga{
  filter:drop-shadow(0 0 2px rgba(176,122,0,.55))
         drop-shadow(0 6px 14px rgba(176,122,0,.26));
}
.name-q{
  font-size:17px;font-weight:800;color:var(--brand-red-deep);
  margin:12px 0 18px;line-height:1.55;
}
.name-input{
  width:100%;box-sizing:border-box;font-size:16px;font-weight:700;color:var(--fg);
  padding:12px 16px;border:2px solid rgba(218,41,28,.3);border-radius:12px;
  outline:none;background:#fff;text-align:center;
  transition:border-color .15s, box-shadow .15s;
}
.name-input:focus{border-color:var(--brand-red);box-shadow:0 0 0 4px rgba(255,199,44,.28)}
.name-input::placeholder{color:#B8A89A;font-weight:600}
.name-go{
  margin-top:16px;width:100%;cursor:pointer;border:none;
  font-size:15px;font-weight:800;color:#fff;letter-spacing:.04em;
  background:linear-gradient(90deg,var(--brand-red),var(--brand-red-deep));
  border-radius:999px;padding:13px 0;
  box-shadow:0 8px 22px rgba(218,41,28,.28);
  transition:transform .18s, box-shadow .18s;
}
.name-go:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(218,41,28,.38)}
.name-note{margin-top:12px;font-size:11px;color:var(--muted)}
.name-skip{
  display:block;margin:10px auto 0;cursor:pointer;
  background:none;border:none;padding:0;
  font-size:12px;color:var(--muted);text-decoration:underline;
}
.name-skip:hover{color:var(--brand-red)}

/* 分享卡预览浮层：长按/右键保存（不依赖 a.download，兼容 iframe/移动端） */
.share-overlay{
  position:fixed;inset:0;z-index:70;
  display:flex;align-items:center;justify-content:center;
  background:rgba(38,24,14,.55);backdrop-filter:blur(6px);
  opacity:0;visibility:hidden;transition:opacity .3s, visibility .3s;
  overflow:auto;
}
.share-overlay.show{opacity:1;visibility:visible}
.share-card{
  background:var(--bg);border-radius:20px;padding:20px 20px 18px;
  max-width:min(88vw,560px);text-align:center;
  box-shadow:0 30px 80px rgba(30,15,5,.5);
  border-top:6px solid var(--brand-red);
}
.share-q{font-size:14px;font-weight:800;color:var(--brand-red-deep);margin-bottom:14px}
.share-img{
  display:block;width:100%;max-width:420px;margin:0 auto;
  border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.18);
  -webkit-user-drag:element;
}
.share-down,.share-close{
  cursor:pointer;border:none;border-radius:999px;
  font-size:14px;font-weight:800;letter-spacing:.04em;padding:10px 22px;
  margin:14px 6px 0;transition:.18s;
}
.share-down{color:#fff;background:linear-gradient(90deg,var(--brand-red),var(--brand-red-deep))}
.share-down:hover{transform:translateY(-2px);box-shadow:0 10px 24px rgba(218,41,28,.3)}
.share-close{color:var(--muted);background:rgba(42,31,26,.08)}
.share-close:hover{background:rgba(42,31,26,.14)}
@keyframes bob{0%,100%{transform:translate(-50%,0);opacity:.84}50%{transform:translate(-50%,7px);opacity:1}}
.progress{
  position:fixed;top:52px;left:0;height:3px;z-index:30;width:0;transition:width .1s;
  background:linear-gradient(90deg,#FFE08A,var(--brand-yellow));
}
.scene{opacity:0;transform:translateY(36px);transition:opacity .8s ease,transform .8s ease}
.scene.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){
  .scene{opacity:1;transform:none;transition:none}
  .scrollhint{animation:none}
  .arches-hero .ga{animation:none}
}

/* ===============================================================
   人格预告屏：大字悬念 + 偏下侧中间的「揭晓」按钮
   =============================================================== */
.scene.teaser{justify-content:center;align-items:center;text-align:center}
.scene.teaser .kicker::after{left:50%;transform:translateX(-50%)}
.teaser-big{
  font-size:clamp(34px,7vw,70px);font-weight:800;line-height:1.15;
  letter-spacing:-.03em;color:var(--brand-red-deep);
  margin-bottom:16px;max-width:760px;
}
.teaser-lines{max-width:560px;align-items:center}
.teaser-lines p{border-left:none;text-align:center;background:transparent;
  backdrop-filter:none;padding:0;color:#6B5A4E}
.teaser-btn{
  cursor:pointer;border:none;font-size:16px;font-weight:800;letter-spacing:.04em;
  color:#fff;background:linear-gradient(90deg,var(--brand-red),var(--brand-red-deep));
  border-radius:999px;padding:15px 34px;
  margin-top:clamp(56px,14vh,150px);
  box-shadow:0 10px 30px rgba(218,41,28,.32);
  transition:transform .18s, box-shadow .18s, background .18s;
  position:relative;z-index:5;
}
.teaser-btn:hover{
  transform:translateY(-3px);
  box-shadow:0 16px 42px rgba(218,41,28,.42);
  background:linear-gradient(90deg,var(--brand-red-deep),var(--brand-red));
}
.teaser-btn:active{transform:translateY(-1px);box-shadow:0 8px 24px rgba(218,41,28,.3)}

/* ===============================================================
   翻页过渡：模拟真实书页翻起——先掀角、再加速翻过、最后落下
   =============================================================== */
.scene.page-flip{
  z-index:6;transform-origin:left center;
  transform-style:preserve-3d;
  animation:pageFlipOut .7s cubic-bezier(.4,.08,.2,.95) forwards;
}
.scene.page-flip::after{
  content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(90deg, rgba(22,14,8,.55), rgba(22,14,8,.16) 52%, rgba(22,14,8,0) 78%);
  opacity:0;
  animation:pageFlipShade .7s cubic-bezier(.4,.08,.2,.95) forwards;
}
@keyframes pageFlipOut{
  0%   {transform:perspective(1050px) rotateY(0deg) rotateX(0deg);}
  18%  {transform:perspective(1050px) rotateY(-9deg) rotateX(-6deg);}
  55%  {transform:perspective(1050px) rotateY(-74deg) rotateX(-2deg);}
  100% {transform:perspective(1050px) rotateY(-118deg) rotateX(0deg);opacity:.3;}
}
@keyframes pageFlipShade{
  0%  {opacity:0}
  30% {opacity:.45}
  62% {opacity:.82}
  100%{opacity:.22}
}
@media (prefers-reduced-motion:reduce){
  .scene.page-flip{animation:none;z-index:auto}
  .scene.page-flip::after{animation:none;opacity:0}
}

.foot{
  text-align:center;font-size:11px;color:var(--muted);padding:40px 20px 66px;
  line-height:2;background:var(--bg-alt);
  border-top:1px solid rgba(218,41,28,.1);
}
.foot .ga{margin:0 auto 16px}

/* 数据来源徽章 */
.mockbadge,.realbadge{
  position:fixed;top:60px;right:14px;z-index:30;font-size:11px;font-weight:700;
  border-radius:999px;padding:6px 14px;backdrop-filter:blur(6px);
}
.mockbadge{color:#8A5A00;background:rgba(255,199,44,.55);border:1px solid rgba(218,41,28,.3)}
.realbadge{color:#1B7A3E;background:rgba(160,224,180,.6);border:1px solid rgba(27,122,62,.32)}

@media (max-width:640px){
  .ga.wm{width:76px;top:6vh;right:5vw}
  .scene{padding:9vh 6vw 8vh}
}

/* ===============================================================
   麦麦人格屏：人格名做成"证书/奖章"式的品牌卡片
   =============================================================== */
.scene.persona{background-color:#FFFDF8}
.persona-card{
  position:relative;max-width:760px;margin-top:6px;
  padding:0;border-radius:26px;overflow:hidden;
  box-shadow:0 22px 60px rgba(160,110,60,.20);
  border:1px solid rgba(218,41,28,.14);
}
.persona-card .band{
  height:14px;width:100%;
}
.persona-card .inner{
  background:rgba(255,255,255,.92);padding:clamp(22px,3.4vw,36px);
  backdrop-filter:blur(4px);
}
/* ---- 隐藏人格：暗色底 + 青蓝辉光，与普通证书卡形成"彩蛋"反差 ---- */
.scene.persona.hidden{background-color:#0B1020}
.scene.persona.hidden .kicker{color:#7FE3F0}
.scene.persona.hidden .kicker::after{background:#7FE3F0}
.persona-card.hidden{
  border-color:rgba(0,188,212,.42);
  box-shadow:0 22px 70px rgba(0,188,212,.34),0 0 0 1px rgba(127,227,240,.18);
}
.persona-card.hidden .inner{
  background:linear-gradient(160deg,#101A33,#0B1020 60%);
  backdrop-filter:none;
}
.persona-card.hidden .persona-title{color:#EAF6FF;border-bottom-color:rgba(127,227,240,.22)}
.persona-card.hidden .persona-count .num{color:#7FE3F0}
.persona-card.hidden .persona-count .u{color:rgba(234,246,255,.6)}
.persona-card.hidden .lines p{
  background:rgba(127,227,240,.10);color:#DCEBFA;border-left-color:#00BCD4;
}
.persona-card.hidden .persona-subs .lbl{color:rgba(220,235,250,.55)}
.persona-card.hidden .persona-subs .sub{
  background:rgba(127,227,240,.16);color:#BFE9F5;border-color:rgba(127,227,240,.34);
}
.persona-card.hidden .persona-roster summary{color:#9FD8E6;border-color:rgba(127,227,240,.3)}
.persona-card.hidden .persona-roster summary:hover{background:#00BCD4;color:#06121C;border-color:#00BCD4}
.persona-card.hidden .persona-roster .roster{background:rgba(127,227,240,.06);border-color:rgba(127,227,240,.16)}
.persona-card.hidden .persona-roster .roster div{border-bottom-color:rgba(127,227,240,.12)}
.persona-card.hidden .persona-roster .roster b{color:#7FE3F0}
.persona-card.hidden .persona-roster .roster em{color:rgba(220,235,250,.5)}
.persona-card.hidden .persona-roster .roster .n{color:#EAF6FF}
/* 保存图片按钮（卡片内右侧，用户要求） */
.save-btn{
  display:block;width:fit-content;
  margin:20px 4px 20px auto;cursor:pointer;
  font-size:14px;font-weight:800;letter-spacing:.04em;
  color:var(--brand-red);background:#fff;
  border:2px solid var(--brand-red);border-radius:999px;
  padding:10px 22px;transition:.18s;
}
.save-btn:hover{color:#fff;background:var(--brand-red);box-shadow:0 8px 22px rgba(218,41,28,.28)}
.persona-card.hidden .save-btn{
  color:#7FE3F0;border-color:rgba(127,227,240,.5);background:rgba(127,227,240,.06);
}
.persona-card.hidden .save-btn:hover{color:#06121C;background:#00BCD4;border-color:#00BCD4}
.persona-card.hidden .formula{color:rgba(220,235,250,.5)}
/* 解锁横幅 */
.hidden-banner{
  display:inline-flex;align-items:center;gap:8px;
  font-size:12px;font-weight:800;letter-spacing:.16em;
  color:#06121C;background:linear-gradient(90deg,#7FE3F0,#00BCD4);
  border-radius:999px;padding:7px 16px;margin-bottom:16px;
  box-shadow:0 6px 22px rgba(0,188,212,.5);
  animation:pulseGlow 2.4s ease-in-out infinite;
}
@keyframes pulseGlow{
  0%,100%{box-shadow:0 6px 22px rgba(0,188,212,.45)}
  50%{box-shadow:0 6px 34px rgba(127,227,240,.85)}
}
@media (prefers-reduced-motion:reduce){
  .hidden-banner{animation:none}
}
.persona-title{
  font-size:clamp(38px,7.8vw,74px);font-weight:800;line-height:1.04;
  letter-spacing:-.04em;color:var(--brand-red-deep);
  display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  padding-bottom:16px;margin-bottom:18px;
  border-bottom:2px solid rgba(218,41,28,.14);
}
.persona-count{
  display:flex;align-items:baseline;gap:9px;
  margin-left:auto;            /* 推到标题行右侧（用户要求） */
  transform:translateY(2px);
}
.persona-count .num{
  font-size:clamp(24px,4.2vw,40px);font-weight:800;letter-spacing:-.03em;
  color:var(--brand-red);line-height:1;
}
.persona-count .u{
  font-size:clamp(12px,1.7vw,14.5px);font-weight:700;color:var(--muted);
  letter-spacing:.06em;
}
.persona-card .lines p{background:rgba(255,251,245,.9)}
.persona-card .lines p b{color:var(--brand-red);font-weight:800}
.persona-card.hidden .lines p b{color:#7FE3F0}
.persona-subs{
  display:flex;flex-wrap:wrap;gap:9px;margin-top:18px;
  padding-top:16px;border-top:1px dashed rgba(218,41,28,.2);
}
.persona-subs .lbl{
  font-size:12px;font-weight:800;color:var(--muted);letter-spacing:.14em;
  align-self:center;margin-right:2px;
}
/* 副人格胶囊：点击展开"迷你证书"（同主人格的信息结构） */
.persona-subs .sub{display:inline-block}
.persona-subs .sub summary{
  cursor:pointer;list-style:none;user-select:none;
  font-size:13px;font-weight:700;border-radius:999px;padding:7px 15px;
  background:var(--brand-yellow);color:#5A3A00;
  box-shadow:0 3px 10px rgba(255,199,44,.4);transition:.15s;
}
.persona-subs .sub summary::-webkit-details-marker{display:none}
.persona-subs .sub summary:hover{background:var(--brand-red);color:#fff}
.persona-subs .sub[open] summary{
  background:var(--brand-red);color:#fff;
  box-shadow:0 5px 16px rgba(218,41,28,.3);
}
.sub-detail{
  margin-top:10px;background:rgba(255,251,245,.97);
  border:1.5px solid rgba(255,199,44,.6);border-radius:14px;
  padding:14px 16px;max-width:460px;box-shadow:var(--shadow);
}
.sub-detail .sub-name{
  font-size:19px;font-weight:800;color:var(--brand-red-deep);letter-spacing:-.01em;
  display:block;margin-bottom:8px;
}
.sub-detail .sub-count{
  display:flex;align-items:baseline;gap:7px;margin-bottom:10px;
  padding-bottom:9px;border-bottom:1.5px dashed rgba(218,41,28,.18);
}
.sub-detail .sub-count .num{font-size:24px;font-weight:800;color:var(--brand-red)}
.sub-detail .sub-count .u{font-size:12px;font-weight:700;color:var(--muted)}
.sub-detail .sub-lines{display:flex;flex-direction:column;gap:7px}
.sub-detail .sub-lines p{
  font-size:13px;line-height:1.65;color:#4A3B33;
  background:rgba(255,199,44,.13);border-left:3px solid rgba(255,199,44,.85);
  border-radius:0 9px 9px 0;padding:7px 11px;
}
.sub-detail .sub-trg{margin-top:9px;font-size:11px;color:var(--muted);line-height:1.6}
/* 隐藏人格屏内的副人格展开卡（暗色变体） */
.persona-card.hidden .sub-detail{
  background:rgba(16,26,51,.95);border-color:rgba(127,227,240,.3);
}
.persona-card.hidden .sub-detail .sub-name{color:#EAF6FF}
.persona-card.hidden .sub-detail .sub-lines p{
  background:rgba(127,227,240,.1);color:#DCEBFA;border-left-color:#00BCD4;
}
.persona-card.hidden .sub-detail .sub-trg{color:rgba(220,235,250,.55)}
/* 人格候补清单（可回溯） */
.persona-roster{margin-top:14px;font-size:12.5px}
.persona-roster summary{
  cursor:pointer;color:var(--muted);user-select:none;font-weight:600;
  border:1px solid rgba(218,41,28,.3);border-radius:999px;padding:6px 16px;
  display:inline-block;background:rgba(255,255,255,.7);transition:.2s;
}
.persona-roster summary:hover{color:#fff;background:var(--brand-red);border-color:var(--brand-red)}
.persona-roster .roster{
  margin-top:11px;display:grid;gap:6px;
}
.persona-roster .roster div{
  background:#fff;border:1px solid var(--line);border-radius:9px;
  padding:8px 13px;display:flex;justify-content:space-between;gap:14px;
  align-items:baseline;
}
.persona-roster .roster b{color:var(--brand-red-deep);font-size:13px}
.persona-roster .roster em{
  font-style:normal;color:var(--muted);font-size:11px;text-align:right;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
}
.persona-roster .roster .n{color:var(--fg);font-weight:700;white-space:nowrap}
"""


# ---------------------------------------------------------------------------
# 分屏渲染
# ---------------------------------------------------------------------------

def _md_bold(t: str) -> str:
    """把文案里的 **xxx** 渲染成 <b>xxx</b>（先转义，再替换，避免 XSS）。

    人格文案里大量使用 **救薯** / **玉米粉碎机** 这类强调，
    若直接 escape 会把星号原样打出来，观感很差。
    """
    safe = escape(t)
    while "**" in safe:
        first = safe.find("**")
        second = safe.find("**", first + 2)
        if second == -1:
            break
        safe = safe[:first] + "<b>" + safe[first + 2:second] + "</b>" + safe[second + 2:]
    return safe


def _render_teaser_scene(s: Dict[str, Any], idx: int) -> str:
    """人格预告屏：大字悬念 + 偏下侧中间的「揭晓」按钮，点击跳转到人格屏。"""
    lines_html = "".join(
        f'<p{" class=small" if i > 0 else ""}>{_md_bold(t)}</p>'
        for i, t in enumerate(s.get("lines", []))
    )
    return f"""
  <section class="scene teaser" data-idx="{idx}">
    {arch_watermark()}
    <div class="kicker">{escape(s.get('title', ''))}</div>
    <div class="teaser-big">{escape(s.get('big', ''))}</div>
    <div class="lines teaser-lines">{lines_html}</div>
    <button class="teaser-btn" id="teaser-btn">揭晓我的麦麦人格 →</button>
  </section>"""


def render_scene(s: Dict[str, Any], idx: int, total: int) -> str:
    kind = s.get("kind", "")

    # ---- 麦麦人格屏：专属卡片式版面 ----
    if kind == "persona":
        return _render_persona_scene(s, idx)

    # ---- 人格预告屏：悬念 + 底部按钮跳转 ----
    if kind == "persona_teaser":
        return _render_teaser_scene(s, idx)

    # ---- 正文 ----
    lines_html = "".join(
        f'<p{" class=small" if i > 1 else ""}>{_md_bold(t)}</p>'
        for i, t in enumerate(s.get("lines", []))
    )

    # ---- 大标题：长文本（门店名）降字号，其余用品牌红大字 ----
    big_cls = "big plain"
    big_style = ""
    if kind == "place":
        big_style = ' style="font-size:clamp(24px,4.8vw,46px);letter-spacing:-.01em"'
    elif kind == "opening":
        big_cls = "big hero-name"
    elif kind == "closing":
        big_cls = "big"

    big_txt = escape(str(s.get("big", "")))
    unit_txt = f'<span class="unit">{escape(str(s["unit"]))}</span>' if s.get("unit") else ""
    # 开场屏的名字是"署名槽"：署名层只在首次打开（从未提交过）时出现一次，
    # 不绑定点击事件 —— 大字正处翻页热区，绑定点击会频繁误触弹层（用户反馈）
    big_id = ' id="owner-name"' if kind == "opening" else ""
    big_html = f'<h1 class="{big_cls}"{big_style}{big_id}>{big_txt}{unit_txt}</h1>'

    # ---- 屏级装饰：开场/结尾放品牌签名级金拱门，其余放水印 ----
    scene_cls = ["scene"]
    ornament = ""
    if kind == "opening":
        scene_cls.append("hero")
        ornament = (
            '<div class="arches-hero">'
            + golden_arches(size="min(40vw,230px)", color="var(--brand-yellow)")
            + "</div>"
        )
    elif kind == "closing":
        scene_cls.append("finale")
        ornament = (
            '<div class="arches-hero">'
            + golden_arches(size="min(34vw,200px)", color="var(--brand-yellow)")
            + "</div>"
        )
    else:
        ornament = arch_watermark()

    # 开场屏右下角的版权署名
    credit_html = ('<div class="credit">本作品由水牛先生开发，请勿盗用</div>'
                   if kind == "opening" else "")

    return f"""
  <section class="{' '.join(scene_cls)}" data-idx="{idx}">
    {ornament}
    <div class="kicker">{escape(s.get('title',''))}</div>
    {big_html}
    <div class="lines">{lines_html}</div>
    {credit_html}
  </section>"""


def _render_persona_scene(s: Dict[str, Any], idx: int) -> str:
    """麦麦人格屏：人格名做成品牌证书卡片，附候补清单（可回溯）。

    隐藏人格（`hidden=True`）走暗色底 + 青蓝辉光的"彩蛋"样式，
    并在标题上方给出「隐藏人格解锁」横幅 —— 与普通证书卡形成强烈反差。
    """
    is_hidden = bool(s.get("hidden"))
    cover = s.get("cover", "linear-gradient(135deg,#DA291C,#FFC72C)")
    name = escape(str(s.get("big", "")))
    unit_txt = str(s.get("unit", ""))
    # unit 形如 "18 杯 · 单品型"：只取数字+单位部分展示（类型印章已按用户要求移除）
    parts = unit_txt.split(" · ")
    cnt = parts[0] if parts else unit_txt

    lines_html = "".join(
        f'<p{" class=small" if i > 1 else ""}>{_md_bold(t)}</p>'
        for i, t in enumerate(s.get("lines", []))
    )

    # 副人格胶囊：点击展开迷你证书（封号 + 类型 + 数量 + 文案 + 触发条件）。
    # details 在点击翻页的排除名单里，展开/收起不会误触发翻页。
    subs_html = ""
    subs = s.get("subs", [])
    if subs:
        chips = "".join(
            f"""<details class="sub">
  <summary>{escape(x["name"])} · {escape(str(x["count"]))} {escape(x["unit"])}</summary>
  <div class="sub-detail">
    <b class="sub-name">{escape(x["name"])}</b>
    <div class="sub-count"><span class="num">{escape(str(x["count"]))}</span>
      <span class="u">{escape(x["unit"])} · 本年度累计</span></div>
    <div class="sub-lines">{''.join(f'<p>{_md_bold(t)}</p>' for t in x.get("lines", []))}</div>
    <div class="sub-trg">触发条件：{_md_bold(x.get("trigger", ""))}</div>
  </div>
</details>"""
            for x in subs
        )
        subs_html = f'<div class="persona-subs"><span class="lbl">副人格</span>{chips}</div>'

    # 候补清单：人格池所有命中项 + 触发条件 + 实测数量
    roster_html = ""
    cands = s.get("candidates", [])
    if cands:
        rows = "".join(
            f'<div><b>{escape(c["name"])}</b>'
            f'<em>{escape(c["trigger"])}</em>'
            f'<span class="n">{c["count"]} {escape(c["unit"])}</span></div>'
            for c in cands
        )
        basis = s.get("basis", {})
        items = basis.get("items", {})
        item_rows = "、".join(f"{escape(k)}×{v}" for k, v in list(items.items())[:12])
        hidden_note = (
            "隐藏人格的触发条件特殊，**不参与**上方候选清单的公开排名，"
            "只有满足条件时才会揭晓。" if is_hidden else ""
        )
        roster_html = f"""
        <details class="persona-roster">
          <summary>↺ 人格是怎么判的（{len(cands)} 项命中）</summary>
          <div class="roster">{rows}</div>
          <div class="formula" style="margin-top:10px">
            本年度商品明细：{item_rows or '（无）'}<br>
            人格取"累计数量最高"的一项为「主人格」，其余为「副人格」；
            数量并列时，名字更具体的人格优先。{hidden_note}
          </div>
        </details>"""
    elif s.get("note"):
        roster_html = f'<div class="formula">{escape(s["note"])}</div>'

    # 隐藏人格：横幅 + 暗色皮肤
    hidden_cls = " hidden" if is_hidden else ""
    banner_html = ('<div class="hidden-banner">★ 隐藏人格解锁 ★</div>'
                   if is_hidden else "")
    title = "你的麦麦人格是" if not is_hidden else "你解锁了一个隐藏人格"

    return f"""
  <section class="scene persona{hidden_cls}" data-idx="{idx}">
    {arch_watermark()}
    <div class="kicker">{escape(s.get('title', title) if not is_hidden else title)}</div>
    <div class="persona-card{hidden_cls}">
      <div class="band" style="background:{cover}"></div>
      <div class="inner">
        {banner_html}
        <div class="persona-title">
          <span>{name}</span>
          <span class="persona-count">
            <span class="num">{escape(cnt)}</span>
            <span class="u">本年度累计</span>
          </span>
        </div>
        <div class="lines">{lines_html}</div>
        {subs_html}
        {roster_html}
        <button class="save-btn" id="save-btn">保存我的麦麦人格图片</button>
      </div>
    </div>
  </section>"""


# ---------------------------------------------------------------------------
# 整页组装
# ---------------------------------------------------------------------------

def render_story_html(story: Dict[str, Any], mock: bool = True) -> str:
    scenes = story["scenes"]
    total = len(scenes)
    body = "".join(render_scene(s, i, total) for i, s in enumerate(scenes))
    member_suffix = escape(str(story.get("member_suffix", "")))

    # 人格数据：供「保存图片」按钮的 Canvas 绘制使用（零依赖导出分享卡）
    persona_scene = next((s for s in scenes if s.get("kind") == "persona"), None)
    persona_data = "null"
    if persona_scene:
        unit_txt = str(persona_scene.get("unit", ""))
        _parts = unit_txt.split(" · ")
        _cnt = _parts[0] if _parts else unit_txt
        _kind = _parts[1] if len(_parts) > 1 else ""
        persona_data = json.dumps({
            "name": persona_scene.get("big", ""),
            "count": _cnt,
            "kind": _kind,
            "hidden": bool(persona_scene.get("hidden")),
            "year": str(story.get("year", "")),
            "lines": persona_scene.get("lines", []),
            "subs": [{"name": x.get("name", ""), "count": x.get("count", 0),
                      "unit": x.get("unit", "")}
                     for x in persona_scene.get("subs", [])],
            "roster": [{"name": x.get("name", ""), "n": x.get("count", 0),
                        "unit": x.get("unit", ""), "kind": x.get("kind", "")}
                       for x in persona_scene.get("candidates", [])[:3]],
            "note": persona_scene.get("note", ""),
        }, ensure_ascii=False)

    badge = ('<div class="mockbadge">演示数据</div>') if mock else \
            ('<div class="realbadge">✓ 真实数据</div>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(str(story['year']))} 麦麦年度报告 · {escape(story['owner'])}</title>
<style>{STORY_CSS}</style>
</head>
<body>
  <div class="progress" id="prog"></div>
  <div class="topbar">
    <button class="backbtn" id="backbtn" aria-label="返回上一页" title="返回上一页">←</button>
    {golden_arches(size="30px", color="var(--brand-yellow)", width=13.5)}
    <span class="brand">{escape(str(story['year']))} 麦麦年度报告 <em>MCD ANNUAL REPORT</em></span>
  </div>
  {badge}
  {body}
  <div class="foot">
    {arch_divider(color="var(--brand-red)", opacity=.85)}
    麦麦年度报告 MCD Annual Report · 基于麦当劳中国官方 MCP · 使用腾讯 WorkBuddy 完成<br>
    本项目为参赛作品，非麦当劳官方产品。<br>
    本作品由水牛先生开发，请勿盗用<br>
    页面所有图形（含金拱门符号与背景纹理）均为本工程代码生成，未使用任何官方图片素材。<br>
    数据没有提供的指标不展示、不估算。
  </div>
  <div class="name-overlay" id="name-overlay">
    <div class="name-card">
      {golden_arches(size="64px", color="var(--brand-yellow)")}
      <div class="name-q">这份 2026 麦麦年度报告<br>署上你的名字</div>
      <input class="name-input" id="name-input" maxlength="12"
             placeholder="输入你的昵称（可留空）" autocomplete="off">
      <button class="name-go" id="name-go">开启我的年报 →</button>
      <button class="name-skip" id="name-skip">跳过，直接看年报</button>
      <div class="name-note">昵称只保存在你自己的浏览器里，不会上传</div>
    </div>
  </div>
  <div class="share-overlay" id="share-overlay">
    <div class="share-card">
      <div class="share-q">长按图片保存到相册</div>
      <img class="share-img" id="share-img" alt="我的麦麦人格">
      <button class="share-down" id="share-down">下载 PNG</button>
      <button class="share-close" id="share-close">关闭</button>
    </div>
  </div>
  <div class="scrollhint" id="hint">点击进入下一页 ▾</div>
<script>
(function(){{
  var MEMBER_SUFFIX = '{member_suffix}';   // 会员 ID 尾号，跳过署名时兜底
  var PERSONA = {persona_data};             // 人格数据，供保存图片 Canvas 绘制
  var scenes = Array.prototype.slice.call(document.querySelectorAll('.scene'));
  var prog = document.getElementById('prog');
  var hint = document.getElementById('hint');
  var backBtn = document.getElementById('backbtn');
  var io = new IntersectionObserver(function(entries){{
    entries.forEach(function(e){{
      if(e.isIntersecting) e.target.classList.add('in');
    }});
  }}, {{threshold:0.22}});
  scenes.forEach(function(s){{ io.observe(s); }});
  // 首屏立即显示
  if(scenes[0]) scenes[0].classList.add('in');

  window.addEventListener('scroll', function(){{
    var h = document.documentElement.scrollHeight - window.innerHeight;
    var p = h > 0 ? (window.scrollY / h) * 100 : 0;
    prog.style.width = p + '%';
    // 翻页提示：滚过首屏或已到最后一屏时隐藏
    //（用 class 而非 inline opacity —— bob 动画的 opacity 会覆盖 inline 样式）
    if(hint) hint.classList.toggle('off', window.scrollY > 120 || curIndex() >= scenes.length - 1);
    if(backBtn) backBtn.disabled = curIndex() === 0;
  }}, {{passive:true}});

  // 当前所在屏（以顶边越过 80px 为准）
  function curIndex(){{
    var cur = 0;
    scenes.forEach(function(s,i){{
      var r = s.getBoundingClientRect();
      if(r.top <= 80) cur = i;
    }});
    return cur;
  }}
  var reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var flipping = false;
  // animate=true 时，当前屏像纸一样翻起，翻到一半滚到下一屏（仅点击翻页用）
  function goNext(animate){{
    if(flipping) return;
    var cur = curIndex();
    if(cur + 1 >= scenes.length) return;
    var curScene = scenes[cur];
    if(animate && !reduceMotion){{
      flipping = true;
      curScene.classList.remove('page-flip');
      void curScene.offsetWidth;   // 强制重排，确保动画重新触发
      curScene.classList.add('page-flip');
      setTimeout(function(){{
        scenes[cur+1].scrollIntoView({{behavior:'smooth'}});
      }}, 380);
      setTimeout(function(){{
        curScene.classList.remove('page-flip');
        flipping = false;
      }}, 800);
    }} else {{
      scenes[cur+1].scrollIntoView({{behavior:'smooth'}});
    }}
  }}
  function goPrev(){{
    var cur = curIndex();
    if(cur - 1 >= 0) scenes[cur-1].scrollIntoView({{behavior:'smooth'}});
  }}

  // 左上角返回按钮：误点翻页后一键回上一页
  if(backBtn){{
    backBtn.addEventListener('click', function(e){{
      e.stopPropagation();
      goPrev();
    }});
    backBtn.disabled = true;   // 初始在第一屏，返回按钮置灰
  }}

  // 人格预告屏的「揭晓」按钮：跳转到人格屏
  var teaserBtn = document.getElementById('teaser-btn');
  if(teaserBtn){{
    teaserBtn.addEventListener('click', function(e){{
      e.stopPropagation();
      var t = document.querySelector('.scene.persona');
      if(t) t.scrollIntoView({{behavior:'smooth'}});
    }});
  }}

  // 昵称署名：只在**首次打开且从未提交过**时出现一次（提交后不再弹，
  // 哪怕提交的是空）。之前"点击开场屏名字弹层"的行为已删除 ——
  // 大字正处翻页热区，绑定点击会频繁误触（用户反馈：第二页也会弹出署名）。
  var OWNER_KEY = 'mcd-ledger-owner';
  var ownerEl = document.getElementById('owner-name');
  var defaultOwner = ownerEl ? ownerEl.textContent.trim() : '';
  var nameOverlay = document.getElementById('name-overlay');
  var nameInput = document.getElementById('name-input');
  var nameGo = document.getElementById('name-go');
  var nameSkip = document.getElementById('name-skip');
  var savedOwner = null;
  try {{ savedOwner = localStorage.getItem(OWNER_KEY); }} catch(err) {{}}
  // 署名兜底优先级：用户输入名 > 会员 ID 尾号（麦友 3118）> 生成时默认署名
  function resolveName(v){{
    if(v) return v;
    if(MEMBER_SUFFIX) return '麦友 ' + MEMBER_SUFFIX;
    return defaultOwner;
  }}
  function commitName(useInput){{
    // 「开启」读取输入框；「跳过」忽略已输入的内容，直接用会员尾号兜底
    var v = (useInput && nameInput) ? nameInput.value.trim() : '';
    try {{ localStorage.setItem(OWNER_KEY, v); }} catch(err) {{}}
    if(ownerEl) ownerEl.textContent = resolveName(v);
    if(nameOverlay) nameOverlay.classList.remove('show');
  }}
  if(nameGo){{
    nameGo.addEventListener('click', function(e){{
      e.stopPropagation();
      commitName(true);
    }});
  }}
  if(nameSkip){{
    nameSkip.addEventListener('click', function(e){{
      e.stopPropagation();
      commitName(false);   // 跳过 = 忽略输入框 + 空提交，同样不会再弹
    }});
  }}
  if(nameInput){{
    nameInput.addEventListener('keydown', function(e){{
      e.stopPropagation();               // 输入时的按键不触发全局翻页
      if(e.key === 'Enter'){{ e.preventDefault(); commitName(true); }}
    }});
  }}
  if(nameOverlay){{
    nameOverlay.addEventListener('click', function(e){{ e.stopPropagation(); }});
  }}
  if(savedOwner !== null){{
    // 提交过（含跳过的空值）就不再弹层；空值用会员尾号兜底
    if(ownerEl) ownerEl.textContent = resolveName(savedOwner);
  }} else if(nameOverlay){{
    // 仅首次（从未提交过）弹出这一次
    nameOverlay.classList.add('show');
    if(nameInput) setTimeout(function(){{ nameInput.focus(); }}, 120);
  }}

  // 点击切换：点屏幕任意处进入下一页（滚轮仍可正常滚动）。
  // 折叠面板（人格判定清单）、顶部导航条、署名输入层等可交互区域不触发翻页。
  function navByTap(e){{
    var t = e.target;
    if(t && t.closest && t.closest('details, summary, a, button, pre, input, select, textarea, label, .topbar, .progress, .name-overlay, .share-overlay')) return;
    goNext(true);
  }}
  window.addEventListener('click', navByTap);
  // 移动端：触摸轻点即时翻页（pointer 事件比 click 合成更早、更可靠）。
  // 通过起止位移区分"轻点"与"滑动/拖动"，滑动时不翻页（避免干扰正常滚动）。
  if(window.PointerEvent){{
    var navSX = 0, navSY = 0, navDown = false;
    window.addEventListener('pointerdown', function(e){{
      navSX = e.clientX; navSY = e.clientY; navDown = true;
    }}, {{passive:true}});
    window.addEventListener('pointerup', function(e){{
      if(!navDown) return;
      navDown = false;
      if(Math.abs(e.clientX - navSX) > 10 || Math.abs(e.clientY - navSY) > 10) return;
      navByTap(e);
    }});
  }}

  // 键盘翻页（保持平滑滚动，不播翻页动画）
  window.addEventListener('keydown', function(e){{
    if(e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' '){{
      e.preventDefault();
      goNext(false);
    }} else if(e.key === 'ArrowUp' || e.key === 'PageUp'){{
      e.preventDefault();
      goPrev();
    }}
  }});

  // 保存图片：Canvas 绘制分享卡并下载（零依赖）
  // 金拱门：直接用 Path2D 复用与 SVG 完全相同的路径字符串，
  // 再用 translate/scale 变换，杜绝两边造型偏差。
  var ARCH_D = {json.dumps(_ARCH_PATH)};
  var ARCH_D2 = {json.dumps(_ARCH_PATH_2)};
  var ARCH_TRANS = {json.dumps(_ARCH_TRANSFORM)};
  function archPath(){{
    var p = new Path2D();
    p.addPath(new Path2D(ARCH_D));
    var m = ARCH_TRANS.match(/translate\\(([-\\d.]+)[ ,]+([-\\d.]+)\\)/);
    if(m){{
      var t = new Path2D(ARCH_D2);
      p.addPath(t, new DOMMatrix().translate(parseFloat(m[1]), parseFloat(m[2])));
    }}
    return p;
  }}
  var _ARCH_CACHE = null;
  // s 为缩放系数：以 SVG 的 108x66 viewBox 为基准
  function drawArch(g, x, y, s, color, width){{
    if(!_ARCH_CACHE) _ARCH_CACHE = archPath();
    g.save();
    g.translate(x, y);
    g.scale(s, s);
    g.strokeStyle = color;
    g.lineWidth = width / s;      // 线宽保持视觉宽度，不随缩放变粗
    g.lineCap = 'butt';
    g.lineJoin = 'miter';
    g.stroke(_ARCH_CACHE);
    g.restore();
  }}
  function wrapText(g, text, maxWidth){{
    var out = []; var line = '';
    var punct = '。，！？、；：）」』';
    for(var i = 0; i < text.length; i++){{
      var ch = text[i];
      if(g.measureText(line + ch).width > maxWidth && line){{
        if(punct.indexOf(ch) >= 0){{
          line += ch; out.push(line); line = ''; continue;   // 标点不悬挂行首
        }}
        out.push(line); line = ch;
      }} else {{ line += ch; }}
    }}
    if(line) out.push(line);
    return out;
  }}
  // Canvas 圆角矩形路径
  function rr(g, x, y, w, h, r){{
    g.beginPath();
    g.moveTo(x + r, y);
    g.lineTo(x + w - r, y); g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r); g.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    g.lineTo(x + r, y + h); g.quadraticCurveTo(x, y + h, x, y + h - r);
    g.lineTo(x, y + r); g.quadraticCurveTo(x, y, x + r, y);
    g.closePath();
  }}

  // 分享卡：结构与「麦麦人格」网页卡片一一对应
  //   顶部 kicker「你的麦麦人格是」 → 红黄渐变色带 → 卡片
  //   卡内：人格名 + 右侧「N单 本年度累计」 → 分隔线 → 逐条面板（左侧高亮竖线）
  //        → 档案说明框（黄底） → 保存按钮同款胶囊（静态装饰）
  //   卡外底部：金拱门 + 版权行
  function drawShareCard(){{
    var D = PERSONA || {{name:'麦门永存', count:'1 单', kind:'', hidden:false,
                         year:'2026', lines:[], subs:[], roster:[], note:''}};
    var W = 1080;
    var c = document.createElement('canvas');
    var g = c.getContext('2d');       // 先用临时 context 量文字，再定画布尺寸
    var PAD = 56;                    // 画布左右留白
    var CX = W / 2;
    var FONT = '"PingFang SC","Microsoft YaHei","Heiti SC",sans-serif';

    // ---- 主卡片几何 ----
    var CARD_X = PAD, CARD_Y = 150, CARD_W = W - PAD*2, CARD_R = 34;
    var IN_X = CARD_X + 44;                       // 卡内左内边距
    var IN_W = CARD_W - 88;

    // 先量内容高度，再按实际高度画卡片底（避免死高度导致的底部留白或内容溢出）
    // 逐条面板高度
    var PANEL_FONT = '38px ' + FONT;
    g.font = PANEL_FONT;
    var panelHeights = (D.lines || []).slice(0, 4).map(function(ln){{
      var t = ln.replace(/\\*\\*/g, '');
      return wrapText(g, t, IN_W - 72).length * 58 + 40;
    }});
    // 档案框高度
    var NOTE_FONT = '29px ' + FONT, nrows = [], nh = 0;
    if(D.note){{
      g.font = NOTE_FONT;
      nrows = wrapText(g, String(D.note), IN_W - 64);
      nh = nrows.length * 46 + 48;
    }}

    // 内容总高：色带 + 名称行 + 分隔线 + 各面板 + 档案框 + 卡内底部留白
    // （不含保存按钮——那是网页控件，不入图）
    var CONTENT_TOP = 20 + 108 + 44 + 46;
    var tall = CONTENT_TOP;
    panelHeights.forEach(function(ph){{ tall += ph + 20; }});
    if(nh) tall += 14 + nh;
    tall += 20 + 56;                  // 档案框之后留白 + 卡内底部留白
    var CARD_H = Math.max(680, tall);

    // 画布总高 = kicker 区 + 卡片 + 卡外金拱门 + 版权行
    // 金拱门按 viewBox 0 0 108 66 等比缩放，故宽高即 108s × 66s
    var ARCH_S = 1.15, ARCH_W = 108 * ARCH_S, ARCH_H = 66 * ARCH_S;
    var archTop = CARD_Y + CARD_H + 78;
    var copyrightY = archTop + ARCH_H + 74;
    var H = Math.ceil(copyrightY + 46);

    c.width = W; c.height = H;
    g = c.getContext('2d');           // 尺寸变更后需重新取 context

    // ---- 背景：暖白底 + 淡网格贴纸 ----
    g.fillStyle = '#FFF8EC'; g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(180,140,96,.13)'; g.lineWidth = 2;
    for(var gx = 40; gx < W; gx += 60){{
      g.beginPath(); g.moveTo(gx, 0); g.lineTo(gx, H); g.stroke();
    }}
    for(var gy = 40; gy < H; gy += 60){{
      g.beginPath(); g.moveTo(0, gy); g.lineTo(W, gy); g.stroke();
    }}

    // ---- 顶部 kicker（左对齐） + 短黄下划线 ----
    g.textAlign = 'left';
    g.fillStyle = '#B4471F'; g.font = 'bold 36px ' + FONT;
    g.fillText('你的麦麦人格是', PAD, 86);
    g.strokeStyle = '#FFC72C'; g.lineWidth = 8; g.lineCap = 'butt';
    g.beginPath(); g.moveTo(PAD, 108); g.lineTo(PAD + 118, 108); g.stroke();

    // 卡片投影
    g.save();
    g.shadowColor = 'rgba(150,90,40,.18)'; g.shadowBlur = 40; g.shadowOffsetY = 14;
    rr(g, CARD_X, CARD_Y, CARD_W, CARD_H, CARD_R);
    g.fillStyle = '#FFFFFF'; g.fill();
    g.restore();

    // 卡片顶部的红→黄渐变色带（与网页 .band 对应）
    g.save();
    rr(g, CARD_X, CARD_Y, CARD_W, CARD_H, CARD_R); g.clip();
    var grad = g.createLinearGradient(CARD_X, 0, CARD_X + CARD_W, 0);
    grad.addColorStop(0, '#DA291C'); grad.addColorStop(1, '#FFC72C');
    g.fillStyle = grad; g.fillRect(CARD_X, CARD_Y, CARD_W, 20);
    g.restore();

    var y = CARD_Y + 20;

    // ---- 人格名（左） + 数量（右，同一行基线） ----
    y += 108;
    g.textAlign = 'left';
    g.fillStyle = '#A81C11'; g.font = 'bold 112px ' + FONT;
    g.fillText(D.name || '', IN_X, y);

    g.textAlign = 'right';
    g.fillStyle = '#DA291C'; g.font = 'bold 68px ' + FONT;
    var cntTxt = (D.count || '').replace(/\\s+/g, ' ');
    g.fillText(cntTxt, CARD_X + CARD_W - 44, y);
    g.fillStyle = '#8A6A50'; g.font = 'bold 30px ' + FONT;
    g.fillText('本年度累计', CARD_X + CARD_W - 44, y + 40);

    // ---- 分隔线 ----
    y += 44;
    g.strokeStyle = 'rgba(218,41,28,.28)'; g.lineWidth = 3;
    g.beginPath(); g.moveTo(IN_X, y); g.lineTo(IN_X + IN_W, y); g.stroke();

    // ---- 逐条文案面板：淡黄底 + 左侧竖高亮线 ----
    y += 46;
    g.font = PANEL_FONT;
    (D.lines || []).slice(0, 4).forEach(function(ln, li){{
      var t = ln.replace(/\\*\\*/g, '');
      var rows = wrapText(g, t, IN_W - 72);
      var ph = panelHeights[li];
      // 面板底（越靠后的装饰线越淡，呼应网页里的渐变竖线）
      var alpha = [1, .72, .48, .3][Math.min(li, 3)];
      g.fillStyle = '#FFFDF6';
      rr(g, IN_X, y, IN_W, ph, 22); g.fill();
      // 左侧竖高亮线
      g.save();
      rr(g, IN_X, y, IN_W, ph, 22); g.clip();
      g.globalAlpha = alpha;
      g.fillStyle = '#FFC72C';
      g.fillRect(IN_X, y, 9, ph);
      g.restore();
      // 文本
      g.textAlign = 'left'; g.fillStyle = '#4A3B33'; g.font = PANEL_FONT;
      var ty = y + 56;
      rows.forEach(function(l){{ g.fillText(l, IN_X + 38, ty); ty += 58; }});
      y += ph + 20;
    }});

    // ---- 档案说明框（黄底，对应网页 .formula） ----
    if(D.note){{
      y += 14;
      g.font = NOTE_FONT;
      g.fillStyle = '#FFF3D4';
      rr(g, IN_X, y, IN_W, nh, 20); g.fill();
      g.fillStyle = '#7A6449'; g.font = NOTE_FONT;
      var ny = y + 52;
      nrows.forEach(function(l){{ g.fillText(l, IN_X + 32, ny); ny += 46; }});
      y += nh;
    }}

    // 注：不再绘制「保存我的麦麦人格图片」按钮胶囊。
    // 那是网页上的交互控件（返回按钮、真实数据徽标同理），
    // 保存出来的图片应只保留卡片内容本身。
    y += 20;   // 档案框与卡片下沿之间的呼吸留白

    // ---- 卡外底部：金拱门 + 版权（画布已在开头按此预留高度） ----
    drawArch(g, CX - ARCH_W/2, archTop, ARCH_S, '#DA291C', 24);
    g.textAlign = 'center'; g.fillStyle = '#8A7A6E'; g.font = '26px ' + FONT;
    g.fillText('本作品由水牛先生开发，请勿盗用', CX, copyrightY);
    return c;
  }}
  var saveBtn = document.getElementById('save-btn');
  if(saveBtn){{
    saveBtn.addEventListener('click', function(e){{
      e.stopPropagation();
      var c = drawShareCard();
      var url = c.toDataURL('image/png');
      var img = document.getElementById('share-img');
      var ov = document.getElementById('share-overlay');
      if(img) img.src = url;
      if(ov) ov.classList.add('show');
    }});
  }}
  var shareDown = document.getElementById('share-down');
  if(shareDown){{
    shareDown.addEventListener('click', function(e){{
      e.stopPropagation();
      var img = document.getElementById('share-img');
      if(!img || !img.src) return;
      var a = document.createElement('a');
      a.download = '我的麦麦人格.png';
      a.href = img.src;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }});
  }}
  var shareClose = document.getElementById('share-close');
  if(shareClose){{
    shareClose.addEventListener('click', function(e){{
      e.stopPropagation();
      document.getElementById('share-overlay').classList.remove('show');
    }});
  }}
  var shareOverlay = document.getElementById('share-overlay');
  if(shareOverlay){{
    shareOverlay.addEventListener('click', function(e){{
      if(e.target === shareOverlay) shareOverlay.classList.remove('show');
    }});
  }}
}})();
</script>
</body>
</html>"""


def generate_story(output: str = "annual_report.story.html",
                   mock: bool = True,
                   orders=None, coupons=None, points=None,
                   account: Dict[str, Any] | None = None,
                   year: int | None = None, owner: str = "麦门用户",
                   today: date | None = None) -> str:
    from ledger_engine import build_story

    if orders is None:
        from mock_loader import (load_mock_coupons, load_mock_orders,
                                 load_mock_points)
        orders = load_mock_orders()
        coupons = coupons if coupons is not None else load_mock_coupons()
        points = points if points is not None else load_mock_points()

    story = build_story(orders, coupons or [], points, account=account,
                        year=year, owner=owner, today=today)
    html = render_story_html(story, mock=mock)

    out = output if os.path.isabs(output) else os.path.join(os.getcwd(), output)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    json_path = os.path.splitext(out)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    print(f"[OK] 叙事版 HTML  → {out}")
    print(f"[OK] 叙事版 JSON  → {json_path}")
    print(f"[OK] 共 {len(story['scenes'])} 屏")
    return out


if __name__ == "__main__":
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    generate_story(output=os.path.join(ROOT, "annual_report.story.demo.html"),
                   mock=True, year=2026, owner="演示用户",
                   today=date(2026, 10, 10))
