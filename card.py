# -*- coding: utf-8 -*-
"""
每日额度卡片渲染器 V2（Pillow，无需浏览器）。

产出三类图：
  render_cover(rows, date, path)   1080x1440 封面卡 —— 信息流第一眼钩子
                                   （日期 + 可买环形图 + 最宽松TOP3 + 今日变动）
  render_card(rows, date, path)    1080 宽详情长图 —— 可买基金按"额度档位"聚类，
                                   暂停基金折叠成弱化芯片，整图高度比 V1 减约 60%
  render_scene_*(...)              1080x1920 视频分幕帧，供 video.py 合成播报视频

设计系统（与 V1 同品牌，投放级美化）：
  - "美元绿"深色渐变底 + 暖金渐变大数字（金融海报感）
  - 大数字优先用 Barlow Condensed（assets/fonts/ 下，OFL 开源），缺失自动回退中文粗体
  - 品牌装饰环 / 径向辉光 / 英文 microcopy
"""

import datetime
import math
import pathlib
import re

from PIL import Image, ImageDraw, ImageFont

# ---------- 配色 ----------
C_BG_TOP   = "#06231A"
C_BG_BOT   = "#0B3526"
C_PANEL    = "#0E3829"
C_PANEL_BD = "#245646"
C_LINE     = "#1B4A38"
C_TEXT     = "#F2EFE6"
C_MUTED    = "#8FAE9F"
C_DIM      = "#54705F"
C_GOLD     = "#E8B84B"
C_GOLD_HI  = "#F7DC94"
C_GOLD_LO  = "#C9912D"
C_GREEN    = "#4CC38A"
C_GREEN_HI = "#9FE8C4"
C_RED      = "#E5604C"
C_BAR_BG   = "#12382A"
C_CHIP_ON     = "#123E2D"
C_CHIP_ON_BD  = "#2A5C4A"
C_CHIP_OFF    = "#0B2C21"
C_CHIP_OFF_BD = "#16463A"
C_CHIP_OFF_TX = "#7E9C8D"
C_DONUT_REST  = "#16482F"
C_DONUT_HOLE  = "#0A2C20"

W = 1080      # 长图/封面宽
PX = 36       # 面板外边距
P_PAD = 30    # 面板内边距
M = 64        # 内容边距
CHIP_H = 84

ROOT = pathlib.Path(__file__).parent


# ---------- 字体 ----------

def _find_font():
    """按平台找可用的中文字体 (bold_path, regular_path, ttc_index)。"""
    candidates = [
        (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/System/Library/Fonts/PingFang.ttc",
         "/System/Library/Fonts/PingFang.ttc", 0),
    ]
    for bold, reg, idx in candidates:
        if pathlib.Path(bold).exists() and pathlib.Path(reg).exists():
            return bold, reg, idx
    raise FileNotFoundError("未找到可用的中文字体，请在 card.py 的 _find_font 中补充字体路径")


FONT_PATH, FONT_PATH_REG, SC = _find_font()

_COND_CANDIDATES = [
    ROOT / "assets" / "fonts" / "BarlowCondensed-Bold.ttf",
    ROOT / "assets" / "fonts" / "BarlowCondensed-SemiBold.ttf",
]
_NUM_RE = re.compile(r"^[\d.]+$")


def _font(size, bold=True):
    return ImageFont.truetype(FONT_PATH if bold else FONT_PATH_REG, size, index=SC)


def _cond(size):
    """大数字字体：Barlow Condensed，缺失回退中文粗体（仅用于数字/拉丁字符）。"""
    for p in _COND_CANDIDATES:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return _font(size)


def _num_font(text, cond_size, cjk_size):
    """数字串用压缩字体；含中文（不限/见公告）用中文粗体，防止豆腐块。"""
    return _cond(cond_size) if _NUM_RE.match(text) else _font(cjk_size)


# ---------- 基础绘制 ----------

_DUMMY = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def _tw(text, font):
    return _DUMMY.textlength(text, font=font)


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(c1, c2, t):
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vgradient(img, top=C_BG_TOP, bot=C_BG_BOT):
    d = ImageDraw.Draw(img)
    a, b = _rgb(top), _rgb(bot)
    h, w = img.height, img.width
    for yy in range(h):
        k = yy / max(h - 1, 1)
        d.line([(0, yy), (w, yy)],
               fill=tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))


def _glow(img, cx, cy, r, color, alpha=24):
    """径向辉光：中心最亮向外衰减。"""
    if r <= 0:
        return
    g = Image.radial_gradient("L").resize((r * 2, r * 2))
    g = g.point(lambda v: int((255 - v) * alpha / 255))
    solid = Image.new("RGB", g.size, _rgb(color))
    img.paste(solid, (int(cx - r), int(cy - r)), g)


def _rings(img, cx, cy):
    """品牌装饰环（右上角两道淡环）。"""
    d = ImageDraw.Draw(img)
    d.ellipse((cx - 220, cy - 220, cx + 220, cy + 220),
              outline=_mix(C_BG_BOT, C_GREEN, 0.13), width=3)
    d.ellipse((cx - 125, cy - 125, cx + 125, cy + 125),
              outline=_mix(C_BG_BOT, C_GOLD, 0.16), width=2)


def _grad_rect(img, box, c1, c2, radius=0, vertical=True):
    """渐变填充圆角矩形。"""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    n = h if vertical else w
    for i in range(n):
        c = _mix(c1, c2, i / max(n - 1, 1))
        if vertical:
            gd.line([(0, i), (w, i)], fill=c)
        else:
            gd.line([(i, 0), (i, h)], fill=c)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    img.paste(grad, (x0, y0), mask)


def _gold_bar(img, x, y, w, h):
    _grad_rect(img, (x, y, x + w, y + h), C_GOLD_HI, C_GOLD_LO, radius=h // 2)


def _grad_text(img, pos, text, font, c_top=C_GOLD_HI, c_bot=C_GOLD_LO):
    """渐变文字（蒙版填充），返回文字宽度（用于排版）。"""
    bbox = _DUMMY.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w <= 0 or h <= 0:
        return 0
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-bbox[0], -bbox[1]), text, font=font, fill=255)
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    for yy in range(h):
        gd.line([(0, yy), (w, yy)], fill=_mix(c_top, c_bot, yy / max(h - 1, 1)))
    img.paste(grad, (int(pos[0]) + bbox[0], int(pos[1]) + bbox[1]), mask)
    return _tw(text, font)


def _spaced_text(d, pos, text, font, fill, spacing):
    """手动 letter-spacing（用于英文 microcopy / 水印）。"""
    x, y = pos
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += _tw(ch, font) + spacing
    return x - pos[0] - spacing


def _spaced_w(text, font, spacing):
    return sum(_tw(ch, font) for ch in text) + spacing * (len(text) - 1)


def _donut(img, cx, cy, r, frac, ring_w, color=C_GREEN):
    """环形图（4x 超采样抗锯齿）。"""
    ss = 4
    size = r * 2 * ss
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((0, 0, size - 1, size - 1), fill=C_DONUT_REST)
    if frac > 0:
        d.pieslice((0, 0, size - 1, size - 1), -90, -90 + 360 * min(frac, 1.0),
                   fill=color)
    hr = (r - ring_w) * ss
    d.ellipse((size / 2 - hr, size / 2 - hr, size / 2 + hr, size / 2 + hr),
              fill=C_DONUT_HOLE)
    layer = layer.resize((r * 2, r * 2), Image.LANCZOS)
    img.paste(layer, (int(cx - r), int(cy - r)), layer)


def _grad_border(img, w_px=4):
    """封面描金边框：竖向 金→绿→金 渐变描边。"""
    w, h = img.size
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    stops = ("#D8B055", "#2E6B4F", "#A8843B")
    for yy in range(h):
        t = yy / max(h - 1, 1)
        c = _mix(stops[0], stops[1], t * 2) if t < 0.5 \
            else _mix(stops[1], stops[2], (t - 0.5) * 2)
        gd.line([(0, yy), (w, yy)], fill=c)
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle((0, 0, w - 1, h - 1), fill=255)
    md.rectangle((w_px, w_px, w - 1 - w_px, h - 1 - w_px), fill=0)
    img.paste(grad, (0, 0), mask)


# ---------- 业务模型 ----------

def _buyable(r):
    return r.get("buyable", r["status"] != "暂停申购")


def _fmt_limit(status, limit):
    if status == "暂停申购":
        return "暂停"
    if status in ("开放申购",) and limit is None:
        return "不限"
    if limit is None:
        return "见公告"
    if limit >= 10000:
        return f"{limit / 10000:g}万元"
    return f"{limit:g}元"


def _fmt_num(limit):
    """档位数字拆分 (数字串, 单位)。"""
    if limit >= 10000:
        return f"{limit / 10000:g}", "万元"
    return f"{limit:g}", "元"


def _bar_frac(limit):
    if limit is None:
        return 0.95
    return min(max((math.log10(max(limit, 1)) - 0.5) / 4.5, 0.10), 0.95)


_CLS_RE = re.compile(r"^(.*?(?:500|100))([A-Z])$")


def _tier_model(g):
    """组内可买基金按额度档位聚类。返回 (buyable, tiers)。
    tier: {num, unit, frac, funds, label}，按宽松度从高到低。"""
    buyable = [r for r in g if _buyable(r)]
    keymap, tiers = {}, []
    for r in buyable:
        if r["status"] == "开放申购" and r.get("limit") is None:
            k = ("inf", 0)
        elif r.get("limit") is None:
            k = ("notice", 0)
        else:
            k = ("num", r["limit"])
        if k not in keymap:
            keymap[k] = {"key": k, "funds": []}
            tiers.append(keymap[k])
        keymap[k]["funds"].append(r)
    order = {"inf": 0, "num": 1, "notice": 2}
    tiers.sort(key=lambda t: (order[t["key"][0]], -t["key"][1]))
    for t in tiers:
        kind, limit = t["key"]
        if kind == "inf":
            t["num"], t["unit"], t["frac"] = "不限", "", 0.95
        elif kind == "notice":
            t["num"], t["unit"], t["frac"] = "见公告", "", 0.15
        else:
            t["num"], t["unit"] = _fmt_num(limit)
            t["frac"] = _bar_frac(limit)
        t["label"] = f"限大额 · {len(t['funds'])} 只" if kind != "inf" \
            else f"开放申购 · {len(t['funds'])} 只"
    return buyable, tiers


def _fund_chip(r):
    """可买基金芯片。"""
    kind = {"down": "down", "up": "up"}.get(r.get("change"), "on")
    sub = r["code"]
    prev = r.get("prev_limit")
    if kind in ("down", "up") and prev is not None and r.get("limit") is not None:
        sub = f"{r['code']} · {prev:g}→{r['limit']:g}元"
    return {"title": r["name"], "sub": sub, "kind": kind}


def _merged_off_chips(g):
    """暂停/暂不开放基金：同基金 A/C 份额合并成一枚弱化芯片。"""
    sus = [r for r in g if not _buyable(r)]
    keymap, ordered = {}, []
    for r in sus:
        tag = "见公告" if r["status"] != "暂停申购" else ""
        m = _CLS_RE.match(r["name"])
        base = m.group(1) if m else r["name"]
        key = (base, tag)
        if key not in keymap:
            keymap[key] = {"base": base, "tag": tag, "cls": [], "codes": [],
                           "down": False}
            ordered.append(keymap[key])
        e = keymap[key]
        if m:
            e["cls"].append(m.group(2))
        e["codes"].append(r["code"])
        if r.get("change") == "down":
            e["down"] = True
    chips = []
    for e in ordered:
        if len(e["cls"]) == 1:
            title = e["base"] + e["cls"][0]
        elif e["cls"]:
            title = e["base"] + " " + "/".join(e["cls"])
        else:
            title = e["base"]
        if e["tag"]:
            title += " · " + e["tag"]
        chips.append({"title": title, "sub": " / ".join(e["codes"]),
                      "kind": "down" if e["down"] else "off"})
    return chips


_CHIP_STYLE = {
    "on":   (C_CHIP_ON, C_CHIP_ON_BD, C_TEXT, C_MUTED),
    "off":  (C_CHIP_OFF, C_CHIP_OFF_BD, C_CHIP_OFF_TX, C_DIM),
    "down": ("#1A3A2D", "#7A453B", C_TEXT, C_RED),
    "up":   ("#16422F", "#3F7A5A", C_TEXT, C_GREEN),
}


def _chips(img, chips, x0, y0, max_w, gap=12):
    """流式排布芯片；img=None 时只测量。返回总高度。"""
    if not chips:
        return 0
    tf, sf, af = _font(26), _font(18, bold=False), _font(22)
    d = ImageDraw.Draw(img) if img is not None else None
    x, y = x0, y0
    for c in chips:
        mark = c.get("kind") in ("down", "up")
        w = int(max(_tw(c["title"], tf), _tw(c["sub"], sf))) + 32 + (30 if mark else 0)
        if x + w > x0 + max_w and x > x0:
            x, y = x0, y + CHIP_H + gap
        if d:
            bg, bd, tc, sc = _CHIP_STYLE[c.get("kind", "off")]
            d.rounded_rectangle((x, y, x + w, y + CHIP_H), 12,
                                fill=bg, outline=bd, width=1)
            d.text((x + 16, y + 12), c["title"], font=tf, fill=tc)
            if mark:
                arrow = "▼" if c["kind"] == "down" else "▲"
                ac = C_RED if c["kind"] == "down" else C_GREEN
                d.text((x + 16 + _tw(c["title"], tf) + 8, y + 15),
                       arrow, font=af, fill=ac)
            d.text((x + 16, y + 48), c["sub"], font=sf, fill=sc)
        x += w + gap
    return y + CHIP_H - y0


def _stats(rows):
    total = len(rows)
    buyable_n = sum(1 for r in rows if _buyable(r))
    ups = [r for r in rows if r.get("change") == "up"]
    downs = [r for r in rows if r.get("change") == "down"]
    return total, buyable_n, ups, downs


def _pick_best(rows):
    for r in rows:          # rows 已按宽松度排序（main.sort_rows）
        if _buyable(r):
            return r
    return None


def _merged_names(rows_, cap=2):
    """变动基金名合并展示：摩根纳指100 A/C 等。"""
    keymap, ordered = {}, []
    for r in rows_:
        m = _CLS_RE.match(r["name"])
        base = m.group(1) if m else r["name"]
        if base not in keymap:
            keymap[base] = []
            ordered.append(base)
        if m:
            keymap[base].append(m.group(2))
    names = []
    for base in ordered[:cap]:
        cls = keymap[base]
        names.append(base + (" " + "/".join(cls) if len(cls) > 1
                             else (cls[0] if cls else "")))
    txt = "、".join(names)
    if len(ordered) > cap:
        txt += f" 等{len(rows_)}只"
    return txt


# ---------- 通用页头元素 ----------

def _brand_row(img, d, y, total, buyable_n, en_text, badge_text=None):
    """品牌行 + 英文 microcopy + 右侧徽章。返回下一个 y。"""
    _gold_bar(img, M, y + 2, 10, 36)
    d.text((M + 28, y), "标普500&纳斯达克100额度哨兵", font=_font(30), fill=C_GOLD)
    enf = _cond(20)
    _spaced_text(d, (M + 28, y + 48), en_text, enf,
                 _mix(C_BG_BOT, C_MUTED, 0.65), 5)
    badge = badge_text or f"今日可买 {buyable_n}/{total}"
    bf = _font(26)
    bw = _tw(badge, bf)
    bx1, bx0 = W - M, W - M - bw - 44
    d.rounded_rectangle((bx0, y - 6, bx1, y + 44), 25,
                        fill=_mix(C_BG_TOP, C_GREEN, 0.10),
                        outline=C_GREEN, width=2)
    d.text((bx0 + 22, y + 3), badge, font=bf, fill=C_GREEN)
    return y + 86


# ============================================================
# 封面卡 1080 x 1440
# ============================================================

def render_cover(rows, date, out_path):
    H = 1440
    img = Image.new("RGB", (W, H), C_BG_TOP)
    _vgradient(img)
    _glow(img, 180, 300, 300, C_GOLD, alpha=18)
    _rings(img, W - 40, -20)
    d = ImageDraw.Draw(img)

    total, buyable_n, ups, downs = _stats(rows)
    weekdays = "一二三四五六日"

    # 品牌行（徽章显示日期）
    y = 64
    _brand_row(img, d, y, total, buyable_n,
               "DAILY QUOTA WATCH · S&P 500 / NASDAQ-100",
               badge_text=f"{date.month}月{date.day}日 · 星期{weekdays[date.weekday()]}")

    # 主标题 + 副标题 + 状态胶囊
    y = 188
    d.text((M, y), "今日额度", font=_font(96), fill=C_TEXT)
    _gold_bar(img, M + 4, y + 128, 120, 8)
    d.text((M, y + 158), "标普500 / 纳指100 场外被动型基金 · 申购上限",
           font=_font(27, bold=False), fill=C_MUTED)
    py = y + 212
    p1 = f"暂停 {total - buyable_n} 只"
    pf = _font(25)
    p1w = _tw(p1, pf) + 48
    d.rounded_rectangle((M, py, M + p1w, py + 56), 14,
                        fill=C_PANEL, outline=C_PANEL_BD, width=1)
    d.text((M + 24, py + 13), p1, font=pf, fill=C_MUTED)
    if downs or ups:
        bits = []
        if ups:
            bits.append(f"▲ {len(ups)} 只放宽")
        if downs:
            bits.append(f"▼ {len(downs)} 只收紧")
        p2 = " · ".join(bits)
        c2 = C_GREEN if (ups and not downs) else C_RED
    else:
        p2, c2 = "— 与昨日持平", C_MUTED
    p2w = _tw(p2, pf) + 48
    x2 = M + p1w + 16
    d.rounded_rectangle((x2, py, x2 + p2w, py + 56), 14,
                        fill=_mix(C_PANEL, c2, 0.08),
                        outline=_mix(C_PANEL_BD, c2, 0.45), width=1)
    d.text((x2 + 24, py + 13), p2, font=pf, fill=c2)

    # 右侧环形图
    cx, cy, r = W - M - 134, 320, 134
    _glow(img, cx, cy, r + 70, C_GREEN, alpha=26)
    _donut(img, cx, cy, r, buyable_n / max(total, 1), 34)
    nf, sfr = _cond(84), _cond(34)
    num = str(buyable_n)
    restxt = f"/{total}"
    tot_w = _tw(num, nf) + 6 + _tw(restxt, sfr)
    nx = cx - tot_w / 2
    _grad_text(img, (nx, cy - 64), num, nf, C_GREEN_HI, C_GREEN)
    d.text((nx + _tw(num, nf) + 6, cy - 22), restxt, font=sfr, fill=C_MUTED)
    lf = _font(24)
    d.text((cx - _tw("今日可买", lf) / 2, cy + 28), "今日可买", font=lf, fill=C_MUTED)

    # TOP3 面板
    ty = 508
    panel_h = 422
    d.rounded_rectangle((PX, ty, W - PX, ty + panel_h), 28,
                        fill=C_PANEL, outline=C_PANEL_BD, width=1)
    _gold_bar(img, M, ty + 34, 8, 32)
    d.text((M + 24, ty + 32), "今日最宽松 TOP3", font=_font(32), fill=C_TEXT)
    note = "单人单日 可买上限"
    nf2 = _font(22, bold=False)
    d.text((W - M - _tw(note, nf2), ty + 40), note, font=nf2, fill=C_DIM)
    d.line((M, ty + 88, W - M, ty + 88), fill=_mix(C_LINE, C_GOLD, 0.25), width=1)

    best3 = [r for r in rows if _buyable(r)][:3]
    medals = [(C_GOLD_HI, C_GOLD_LO, "#06231A"),
              ("#E2EAE5", "#9FB2A8", "#15302A"),
              ("#DCAE80", "#B17B43", "#2A1A0C")]
    if best3:
        row_h = 106
        for i, r in enumerate(best3):
            ry = ty + 100 + i * row_h
            m1, m2, mt = medals[i]
            _grad_rect(img, (M, ry + 18, M + 50, ry + 68), m1, m2, radius=25)
            mf = _cond(30)
            d.text((M + 25 - _tw(str(i + 1), mf) / 2, ry + 28), str(i + 1),
                   font=mf, fill=mt)
            d.text((M + 76, ry + 8), r["name"], font=_font(36), fill=C_TEXT)
            extra = " · 同档还有同公司份额" if False else ""
            d.text((M + 76, ry + 60),
                   f"{r['code']} · {r['status']}{extra}",
                   font=_font(22, bold=False), fill=C_MUTED)
            val = _fmt_limit(r["status"], r["limit"])
            mnum = re.match(r"^([\d.]+)(.+)$", val)
            if mnum:
                numtxt, unit = mnum.group(1), mnum.group(2)
                uf = _font(28)
                vnf = _cond(72)
                ux = W - M - _tw(unit, uf)
                d.text((ux, ry + 40), unit, font=uf, fill=C_GOLD)
                _grad_text(img, (ux - 8 - _tw(numtxt, vnf), ry + 6), numtxt, vnf)
            else:
                vf = _font(40)
                d.text((W - M - _tw(val, vf), ry + 24), val, font=vf, fill=C_GOLD)
            if i < len(best3) - 1:
                d.line((M, ry + row_h - 4, W - M, ry + row_h - 4),
                       fill=C_LINE, width=1)
    else:
        d.text((M, ty + 140), "今日监控基金全线暂停申购",
               font=_font(34), fill=C_RED)

    # 变动条
    sy = ty + panel_h + 26
    if downs and not ups:
        sc, label = C_RED, "▼ 今日收紧"
        first = downs[0]
        detail = _merged_names(downs)
        if first.get("prev_limit") is not None and first.get("limit") is not None:
            detail += f"：{first['prev_limit']:g}元 → {first['limit']:g}元"
    elif ups and not downs:
        sc, label = C_GREEN, "▲ 今日放宽"
        first = ups[0]
        detail = _merged_names(ups)
        if first.get("prev_limit") is not None and first.get("limit") is not None:
            detail += f"：{first['prev_limit']:g}元 → {first['limit']:g}元"
    elif ups and downs:
        sc, label = C_GOLD, "今日变动"
        detail = f"▲ {len(ups)} 只放宽 · ▼ {len(downs)} 只收紧，详见第 2 张图"
    else:
        sc, label = C_MUTED, "— 额度与昨日持平"
        detail = ""
    d.rounded_rectangle((PX, sy, W - PX, sy + 86), 20,
                        fill=_mix(C_PANEL, sc, 0.08),
                        outline=_mix(C_PANEL_BD, sc, 0.45), width=1)
    hf = _font(28)
    d.text((M, sy + 24), label, font=hf, fill=sc)
    if detail:
        d.text((M + _tw(label, hf) + 24, sy + 26), detail,
               font=_font(26), fill=C_TEXT)

    # 页脚：免责声明 + CTA 胶囊
    fy = H - 64 - 64
    d.text((M, fy), "数据来源：天天基金网公开页面 / 基金公司公告",
           font=_font(21, bold=False), fill=C_DIM)
    d.text((M, fy + 34), "仅为公开信息整理，不构成投资建议",
           font=_font(21, bold=False), fill=C_DIM)
    cta = f"完整 {total} 只名单 · 第 2 张图 →"
    cf = _font(26)
    cw = _tw(cta, cf) + 68
    _grad_rect(img, (W - M - cw, fy - 2, W - M, fy + 62),
               "#F2CD74", "#DCA93C", radius=32)
    d.text((W - M - cw + 34, fy + 13), cta, font=cf, fill="#0A2C20")

    _grad_border(img, 4)
    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


# ============================================================
# 详情长图（档位聚类版）
# ============================================================

def _panel(img, y0, idx_name, g):
    """绘制(或测量)一个指数分组面板，返回面板高度。img=None 时只测量。"""
    d = ImageDraw.Draw(img) if img is not None else None
    x0, x1 = PX + P_PAD, W - PX - P_PAD
    buyable, tiers = _tier_model(g)
    y = y0 + 28

    # 组头
    if d:
        _gold_bar(img, x0, y + 2, 8, 34)
        d.text((x0 + 24, y), idx_name, font=_font(32), fill=C_TEXT)
        note = "按额度档位 · 单人单日上限"
        d.text((x0 + 24 + _tw(idx_name, _font(32)) + 20, y + 10), note,
               font=_font(21, bold=False), fill=C_DIM)
        stat_n, stat_rest = f"{len(buyable)}", f" / {len(g)} 只可买"
        snf, srf = _cond(32), _font(24)
        sw = _tw(stat_n, snf) + _tw(stat_rest, srf)
        d.text((x1 - sw, y + 2), stat_n, font=snf, fill=C_GREEN)
        d.text((x1 - sw + _tw(stat_n, snf), y + 8), stat_rest,
               font=srf, fill=C_MUTED)
        d.line((x0, y + 54, x1, y + 54), fill=_mix(C_LINE, C_GOLD, 0.22), width=1)
    y += 70

    # 档位行
    chip_x0 = x0 + 230 + 32
    chips_max_w = x1 - chip_x0
    if tiers:
        for ti, t in enumerate(tiers):
            chips = [_fund_chip(r) for r in t["funds"]]
            chips_h = _chips(None, chips, chip_x0, 0, chips_max_w)
            row_h = max(124, chips_h) + 44
            if d:
                ry = y + 22
                nf = _num_font(t["num"], 68, 44)
                if _NUM_RE.match(t["num"]):
                    nw = _grad_text(img, (x0 + 8, ry), t["num"], nf)
                else:
                    d.text((x0 + 8, ry + 12), t["num"], font=nf, fill=C_GOLD)
                    nw = _tw(t["num"], nf)
                if t["unit"]:
                    d.text((x0 + 8 + nw + 6, ry + 38), t["unit"],
                           font=_font(24), fill=C_GOLD)
                bar_y = ry + 84
                d.rounded_rectangle((x0 + 8, bar_y, x0 + 208, bar_y + 10), 5,
                                    fill=C_BAR_BG)
                _grad_rect(img, (x0 + 8, bar_y,
                                 x0 + 8 + int(200 * t["frac"]), bar_y + 10),
                           C_GOLD_LO, C_GOLD_HI, radius=5, vertical=False)
                d.text((x0 + 8, bar_y + 22), t["label"],
                       font=_font(20, bold=False), fill=C_MUTED)
                _chips(img, chips, chip_x0, ry, chips_max_w)
                if ti < len(tiers) - 1:
                    d.line((x0, y + row_h - 1, x1, y + row_h - 1),
                           fill=C_LINE, width=1)
            y += row_h
    else:
        if d:
            d.text((x0 + 8, y + 16), "今日全部暂停申购", font=_font(30), fill=C_RED)
        y += 72

    # 暂停折叠区
    off_chips = _merged_off_chips(g)
    if off_chips:
        if d:
            d.line((x0, y + 4, x1, y + 4), fill=C_LINE, width=1)
            label = f"暂停 / 暂不开放 · {len(g) - len(buyable)} 只"
            lf = _font(22)
            d.text((x0 + 8, y + 22), label, font=lf, fill=C_DIM)
            lx = x0 + 8 + _tw(label, lf) + 18
            d.line((lx, y + 38, x1 - 8, y + 38), fill=C_LINE, width=1)
        y += 62
        h = _chips(img, off_chips, x0 + 8, y, x1 - x0 - 16)
        y += h + 24

    return y - y0 + 8


def render_card(rows, date, out_path):
    """详情长图：rows = [{name, code, index, status, limit, buyable, change,
    prev_limit?}]，按 main.sort_rows 排序。"""
    groups = []
    for r in rows:
        if not groups or groups[-1][0] != r["index"]:
            groups.append((r["index"], []))
        groups[-1][1].append(r)

    HEADER_H = 396
    FOOTER_H = 190
    panel_hs = [_panel(None, 0, n, g) for n, g in groups]
    H = HEADER_H + sum(h + 28 for h in panel_hs) + FOOTER_H

    img = Image.new("RGB", (W, H), C_BG_TOP)
    _vgradient(img)
    _glow(img, 160, 240, 260, C_GOLD, alpha=14)
    _rings(img, W - 40, -20)
    d = ImageDraw.Draw(img)

    total, buyable_n, ups, downs = _stats(rows)
    weekdays = "一二三四五六日"

    # 头部
    y = 64
    y = _brand_row(img, d, y, total, buyable_n, f"FULL LIST · {total} FUNDS")
    date_str = f"{date.month}月{date.day}日"
    d.text((M, y), date_str, font=_font(84), fill=C_TEXT)
    d.text((M + _tw(date_str, _font(84)) + 24, y + 44),
           f"星期{weekdays[date.weekday()]} · 完整名单",
           font=_font(32), fill=C_MUTED)
    y += 124

    best = _pick_best(rows)
    d.rounded_rectangle((PX, y, W - PX, y + 70), 18,
                        fill=_mix(C_PANEL, C_GOLD, 0.10),
                        outline=_mix(C_PANEL_BD, C_GOLD, 0.35), width=1)
    d.text((M, y + 17), "★", font=_font(30), fill=C_GOLD)
    if best:
        head = f"今日最宽松：{best['name']}（{best['code']}）单日可买 "
        hl = _font(27)
        d.text((M + 48, y + 18), head, font=hl, fill=C_TEXT)
        d.text((M + 48 + _tw(head, hl), y + 18),
               _fmt_limit(best["status"], best["limit"]), font=hl, fill=C_GOLD)
    else:
        d.text((M + 48, y + 18), "今日监控基金全线暂停申购",
               font=_font(27), fill=C_RED)
    y += 70 + 36

    # 分组面板
    for (idx_name, g), ph in zip(groups, panel_hs):
        d.rounded_rectangle((PX, y, W - PX, y + ph), 28,
                            fill=C_PANEL, outline=C_PANEL_BD, width=1)
        _panel(img, y, idx_name, g)
        y += ph + 28

    # 页脚
    fy = H - FOOTER_H + 24
    d.line((M, fy, W - M, fy), fill=_mix(C_LINE, C_GOLD, 0.25), width=1)
    fy += 24
    d.rounded_rectangle((M, fy + 8, M + 110, fy + 18), 5, fill=C_BAR_BG)
    _grad_rect(img, (M, fy + 8, M + 76, fy + 18), "#2E8C61", C_GREEN,
               radius=5, vertical=False)
    d.text((M + 130, fy - 2), "条越长 = 今日可买额度越宽松（对数刻度）",
           font=_font(22, bold=False), fill=C_MUTED)
    fy += 42
    d.text((M, fy), "数据来源：天天基金网公开页面 / 基金公司公告（以公告为准）",
           font=_font(22, bold=False), fill=C_MUTED)
    fy += 36
    d.text((M, fy),
           f"仅为公开信息整理，不构成投资建议 · 生成于 {datetime.datetime.now():%H:%M}",
           font=_font(22, bold=False), fill=C_MUTED)

    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


# ============================================================
# 视频分幕帧 1080 x 1920
# ============================================================

VW, VH = 1080, 1920


def _scene_base(watermark=""):
    img = Image.new("RGB", (VW, VH), C_BG_TOP)
    _vgradient(img)
    _rings(img, VW - 30, -30)
    if watermark:
        d = ImageDraw.Draw(img)
        wf = _cond(52)
        wx = VW - 60 - _spaced_w(watermark, wf, 14)
        _spaced_text(d, (wx, VH - 300), watermark, wf,
                     _mix(C_BG_BOT, C_TEXT, 0.06), 14)
    return img


def _scene_chrome(img, idx, n, subtitle, accent_gold=True):
    """底部：分段进度条 + 字幕条。"""
    d = ImageDraw.Draw(img)
    seg_w, gap = 64, 12
    total_w = n * seg_w + (n - 1) * gap
    x = (VW - total_w) / 2
    by = VH - 230
    for i in range(n):
        if i == idx:
            _grad_rect(img, (x, by, x + seg_w, by + 10), C_GOLD_HI, C_GOLD_LO,
                       radius=5, vertical=False)
        else:
            d.rounded_rectangle((x, by, x + seg_w, by + 10), 5, fill="#1E5040")
        x += seg_w + gap
    sy = VH - 184
    d.rounded_rectangle((80, sy, VW - 80, sy + 104), 22,
                        fill="#061C15", outline="#1E5040", width=1)
    bar_c1, bar_c2 = (C_GOLD_HI, C_GOLD_LO) if accent_gold else (C_RED, C_RED)
    _grad_rect(img, (114, sy + 34, 122, sy + 70), bar_c1, bar_c2, radius=4)
    d.text((148, sy + 28), subtitle, font=_font(40), fill=C_TEXT)


def render_scene_cover(rows, date, out_path, idx, n, subtitle):
    img = _scene_base("SPX · NDX")
    _glow(img, 300, 1000, 360, C_GREEN, alpha=20)
    d = ImageDraw.Draw(img)
    total, buyable_n, ups, downs = _stats(rows)
    weekdays = "一二三四五六日"

    y = 420
    _gold_bar(img, 80, y + 4, 12, 44)
    d.text((80 + 30, y), "额度哨兵 · 每日播报", font=_font(40), fill=C_GOLD)
    y += 90
    d.text((80, y), f"{date.month}月{date.day}日", font=_font(140), fill=C_TEXT)
    y += 190
    d.text((80, y), f"星期{weekdays[date.weekday()]} · 美股指数基金额度",
           font=_font(50), fill=C_MUTED)
    y += 130

    cx, cy, r = 80 + 150, y + 150, 150
    _donut(img, cx, cy, r, buyable_n / max(total, 1), 36)
    nf, sfr = _cond(100), _cond(40)
    num, restxt = str(buyable_n), f"/{total}"
    tot_w = _tw(num, nf) + 8 + _tw(restxt, sfr)
    nx = cx - tot_w / 2
    _grad_text(img, (nx, cy - 78), num, nf, C_GREEN_HI, C_GREEN)
    d.text((nx + _tw(num, nf) + 8, cy - 26), restxt, font=sfr, fill=C_MUTED)
    lf = _font(28)
    d.text((cx - _tw("今日可买", lf) / 2, cy + 34), "今日可买", font=lf, fill=C_MUTED)

    px = cx + r + 60
    pf = _font(34)
    p1 = f"暂停 {total - buyable_n} 只"
    d.rounded_rectangle((px, cy - 80, px + _tw(p1, pf) + 56, cy - 12), 16,
                        fill=C_PANEL, outline=C_PANEL_BD, width=1)
    d.text((px + 28, cy - 66), p1, font=pf, fill=C_MUTED)
    if downs or ups:
        bits = []
        if ups:
            bits.append(f"▲ {len(ups)} 放宽")
        if downs:
            bits.append(f"▼ {len(downs)} 收紧")
        p2 = " · ".join(bits)
        c2 = C_GREEN if (ups and not downs) else C_RED
    else:
        p2, c2 = "— 与昨日持平", C_MUTED
    d.rounded_rectangle((px, cy + 12, px + _tw(p2, pf) + 56, cy + 80), 16,
                        fill=_mix(C_PANEL, c2, 0.08),
                        outline=_mix(C_PANEL_BD, c2, 0.45), width=1)
    d.text((px + 28, cy + 26), p2, font=pf, fill=c2)

    _scene_chrome(img, idx, n, subtitle)
    img.save(out_path)
    return out_path


def _tier_title(t):
    """分幕档位卡标题：≤2只列名称，更多列公司名。"""
    funds = t["funds"]
    if len(funds) == 1:
        return funds[0]["name"], f"{funds[0]['code']} · {funds[0]['status']}"
    if len(funds) == 2:
        m = _CLS_RE.match(funds[0]["name"])
        m2 = _CLS_RE.match(funds[1]["name"])
        if m and m2 and m.group(1) == m2.group(1):
            return f"{m.group(1)} {m.group(2)}/{m2.group(2)}", "共 2 只"
        return f"{funds[0]['name']} / {funds[1]['name']}", "共 2 只"
    comps, seen = [], set()
    for r in funds:
        c = re.split("标普|纳指", r["name"])[0]
        if c not in seen:
            seen.add(c)
            comps.append(c)
    title = " / ".join(comps[:2]) + (" 等" if len(comps) > 2 else "")
    return title, f"共 {len(funds)} 只"


def render_scene_group(idx_name, g, watermark, out_path, idx, n, subtitle):
    img = _scene_base(watermark)
    d = ImageDraw.Draw(img)
    buyable, tiers = _tier_model(g)

    y = 130
    _gold_bar(img, 80, y + 4, 12, 56)
    d.text((80 + 32, y), idx_name, font=_font(64), fill=C_TEXT)
    stat = f"{len(buyable)} / {len(g)} 只可买"
    sf = _font(38)
    d.text((VW - 80 - _tw(stat, sf), y + 22), stat, font=sf,
           fill=C_GREEN if buyable else C_DIM)

    sus_n = len(g) - len(buyable)
    shown = tiers[:4]
    card_h, gap = 172, 26
    block = len(shown) * (card_h + gap)
    if sus_n:
        block += 104 + gap
    y0 = 300 + max(0, (1320 - block) // 2)

    hi = len(shown) > 1   # 多档位时高亮最宽松档
    for ti, t in enumerate(shown):
        cy0 = y0 + ti * (card_h + gap)
        if ti == 0 and hi:
            _glow(img, VW / 2, cy0 + card_h / 2, 320, C_GOLD, alpha=12)
            d.rounded_rectangle((80, cy0, VW - 80, cy0 + card_h), 28,
                                fill=C_PANEL,
                                outline=_mix(C_PANEL_BD, C_GOLD, 0.6), width=3)
        else:
            d.rounded_rectangle((80, cy0, VW - 80, cy0 + card_h), 28,
                                fill=C_PANEL, outline=C_CHIP_ON_BD, width=2)
        title, sub = _tier_title(t)
        d.text((128, cy0 + 34), title, font=_font(48), fill=C_TEXT)
        if ti == 0 and hi:
            d.text((128, cy0 + 104), "★ 今日最宽松", font=_font(32), fill=C_GOLD)
        else:
            d.text((128, cy0 + 104), sub, font=_font(32), fill=C_MUTED)
        nf = _num_font(t["num"], 96, 56)
        uf = _font(42)
        ux = VW - 128 - (_tw(t["unit"], uf) if t["unit"] else 0)
        if t["unit"]:
            d.text((ux, cy0 + 86), t["unit"], font=uf, fill=C_GOLD)
        if _NUM_RE.match(t["num"]):
            _grad_text(img, (ux - 10 - _tw(t["num"], nf), cy0 + 26), t["num"], nf)
        else:
            d.text((ux - _tw(t["num"], nf), cy0 + 50), t["num"], font=nf,
                   fill=C_GOLD)

    if sus_n:
        sy0 = y0 + len(shown) * (card_h + gap)
        d.rounded_rectangle((80, sy0, VW - 80, sy0 + 104), 28,
                            outline="#2E5C49", width=3)
        txt = f"其余 {sus_n} 只暂停申购" if tiers else f"全部 {sus_n} 只暂停申购"
        tf = _font(40)
        d.text(((VW - _tw(txt, tf)) / 2, sy0 + 28), txt, font=tf, fill=C_DIM)

    _scene_chrome(img, idx, n, subtitle)
    img.save(out_path)
    return out_path


def render_scene_changes(rows, out_path, idx, n, subtitle):
    total, buyable_n, ups, downs = _stats(rows)
    img = _scene_base()
    if downs:
        _glow(img, VW / 2, 850, 420, C_RED, alpha=16)
    d = ImageDraw.Draw(img)

    y = 130
    bar_c = C_RED if downs else (C_GREEN if ups else C_MUTED)
    d.rounded_rectangle((80, y + 4, 92, y + 60), 6, fill=bar_c)
    d.text((112, y), "较昨日变动", font=_font(64), fill=C_TEXT)

    def change_card(cy0, rows_, color, tag):
        h = 360
        d.rounded_rectangle((80, cy0, VW - 80, cy0 + h), 32,
                            fill=_mix(C_PANEL, color, 0.06),
                            outline=_mix(C_PANEL_BD, color, 0.5), width=3)
        tf = _font(44)
        tw_ = _tw(tag, tf) + 64
        d.rounded_rectangle(((VW - tw_) / 2, cy0 + 40, (VW + tw_) / 2, cy0 + 110),
                            35, fill=_mix(C_PANEL, color, 0.16),
                            outline=_mix(C_PANEL_BD, color, 0.6), width=1)
        d.text(((VW - tw_) / 2 + 32, cy0 + 50), tag, font=tf, fill=color)
        names = _merged_names(rows_)
        nf = _font(60)
        d.text(((VW - _tw(names, nf)) / 2, cy0 + 134), names, font=nf, fill=C_TEXT)
        first = rows_[0]
        if first.get("prev_limit") is not None and first.get("limit") is not None:
            old = f"{first['prev_limit']:g}元"
            new = f"{first['limit']:g}元"
            of, af, vf = _cond(64), _font(50), _cond(96)
            tot = _tw(old, of) + 24 + _tw("→", af) + 24 + _tw(new, vf)
            x = (VW - tot) / 2
            d.text((x, cy0 + 250), old, font=of, fill=C_DIM)
            lw = _tw(old, of)
            d.line((x, cy0 + 290, x + lw, cy0 + 290), fill=C_DIM, width=4)
            d.text((x + lw + 24, cy0 + 252), "→", font=af, fill=C_MUTED)
            d.text((x + lw + 24 + _tw("→", af) + 24, cy0 + 228), new,
                   font=vf, fill=color)
        return h

    cards = []
    if downs:
        cards.append((downs, C_RED, "▼ 收紧"))
    if ups:
        cards.append((ups, C_GREEN, "▲ 放宽"))

    if cards:
        block = len(cards) * 400 + 90
        y0 = 300 + max(0, (1300 - block) // 2)
        for rows_, color, tag in cards:
            h = change_card(y0, rows_, color, tag)
            y0 += h + 40
        rest = total - len(ups) - len(downs)
        txt = f"其余 {rest} 只额度持平"
        tf = _font(42)
        d.text(((VW - _tw(txt, tf)) / 2, y0 + 20), txt, font=tf, fill=C_MUTED)
    else:
        txt = "额度与昨日持平"
        tf = _font(76)
        d.text(((VW - _tw(txt, tf)) / 2, 820), txt, font=tf, fill=C_TEXT)
        sub = f"今日可买 {buyable_n}/{total} 只，无放宽或收紧"
        sf2 = _font(40)
        d.text(((VW - _tw(sub, sf2)) / 2, 960), sub, font=sf2, fill=C_MUTED)

    _scene_chrome(img, idx, n, subtitle, accent_gold=not downs)
    img.save(out_path)
    return out_path


def render_scene_outro(out_path, idx, n, subtitle):
    img = _scene_base()
    _glow(img, VW / 2, 760, 380, C_GOLD, alpha=14)
    d = ImageDraw.Draw(img)

    y = 560
    brand = "标普500&纳指100 额度哨兵"
    bf = _font(48)
    bx = (VW - _tw(brand, bf) - 30) / 2
    _gold_bar(img, bx, y + 6, 12, 48)
    d.text((bx + 30, y), brand, font=bf, fill=C_GOLD)
    y += 130
    for line in ("每个交易日 8:30", "更新额度"):
        lf = _font(76)
        d.text(((VW - _tw(line, lf)) / 2, y), line, font=lf, fill=C_TEXT)
        y += 110
    y += 40
    cta = "关注，不错过额度放开"
    cf = _font(44)
    cw = _tw(cta, cf) + 96
    _grad_rect(img, ((VW - cw) / 2, y, (VW + cw) / 2, y + 88),
               "#F2CD74", "#DCA93C", radius=44)
    d.text(((VW - cw) / 2 + 48, y + 20), cta, font=cf, fill="#0A2C20")
    y += 150
    d.line(((VW - 200) / 2, y, (VW + 200) / 2, y),
           fill=_mix(C_LINE, C_GOLD, 0.3), width=2)
    y += 40
    for line in ("数据来自天天基金及基金公司公告", "不构成投资建议"):
        lf = _font(32, bold=False)
        d.text(((VW - _tw(line, lf)) / 2, y), line, font=lf, fill=C_MUTED)
        y += 52

    _scene_chrome(img, idx, n, subtitle)
    img.save(out_path)
    return out_path
