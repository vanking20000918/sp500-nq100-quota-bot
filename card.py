# -*- coding: utf-8 -*-
"""
每日额度卡片渲染器（Pillow，无需浏览器）。

设计要点：
- 1080 宽长图，小红书/微博/B站动态通吃，抖音可作视频底图
- "美元绿"渐变深色底 + 暖金限额数字，状态一眼可辨
- 每组一块圆角面板；头部有"今日可买 x/n"徽章和"今日最宽松"亮点条
- 每行下方的"额度松紧条"是这张卡的记忆点：
  条越长额度越宽松（对数刻度），不可买则熄灭
"""

import datetime
import pathlib
import math
import re

from PIL import Image, ImageDraw, ImageFont

# ---------- 配色 ----------
C_BG_TOP  = "#071F17"   # 背景渐变·顶
C_BG_BOT  = "#0E3D2C"   # 背景渐变·底
C_PANEL   = "#0E3829"   # 分组面板
C_PANEL_L = "#1E5040"   # 面板描边
C_LINE    = "#1B4A38"   # 分隔线
C_TEXT    = "#F2EFE6"   # 暖白
C_MUTED   = "#8FAE9F"   # 次要文字
C_GOLD    = "#E8B84B"   # 限额数字
C_OPEN    = "#4CC38A"   # 开放
C_LIMIT   = "#E8B84B"   # 限大额
C_PAUSE   = "#E5604C"   # 暂停
C_BAR_BG  = "#143F2F"   # 松紧条底
C_DIM     = "#54705F"   # 不可买基金的弱化色
C_BADGE_BG = "#11402E"  # 徽章底色


def _find_font():
    """按平台找可用的中文字体 (bold_path, regular_path, ttc_index)。"""
    candidates = [
        # Windows: 微软雅黑
        (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", 0),
        # Linux: Noto CJK
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        # macOS: 苹方
        ("/System/Library/Fonts/PingFang.ttc",
         "/System/Library/Fonts/PingFang.ttc", 0),
    ]
    for bold, reg, idx in candidates:
        if pathlib.Path(bold).exists() and pathlib.Path(reg).exists():
            return bold, reg, idx
    raise FileNotFoundError("未找到可用的中文字体，请在 card.py 的 _find_font 中补充字体路径")


FONT_PATH, FONT_PATH_REG, SC = _find_font()

W = 1080
PX = 36         # 面板外边距
M = 64          # 内容边距
SX = 620        # 状态列 x
ROW_H = 104
HEADER_H = 408  # 品牌行+日期+副标题+亮点条
GROUP_HEAD = 136  # 面板内：上留白24+组头44+间隔14+列头34+下留白20
GROUP_GAP = 28
FOOTER_H = 216


def _calc_height(rows):
    n_groups = len({r["index"] for r in rows})
    body = n_groups * (GROUP_HEAD + GROUP_GAP) + len(rows) * ROW_H
    return max(HEADER_H + body + FOOTER_H, 1350)


def _font(size, bold=True):
    return ImageFont.truetype(FONT_PATH if bold else FONT_PATH_REG, size, index=SC)


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(c1, c2, t):
    """c1 向 c2 混合 t (0~1)，返回 hex。"""
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _fmt_limit(status, limit):
    if status == "暂停申购":
        return "暂停"
    if status in ("开放申购",) and limit is None:
        return "不限"
    if limit is None:
        return "见公告"
    if limit >= 10000:
        v = limit / 10000
        return f"{v:g}万元"
    return f"{limit:g}元"


def _tightness(status, limit):
    """额度宽松度 0~1，对数刻度：100元≈0.1，不限=1，暂停=0。"""
    if status == "暂停申购":
        return 0.0
    if limit is None:
        return 1.0
    lo, hi = math.log10(100), math.log10(1_000_000)
    x = (math.log10(max(limit, 100)) - lo) / (hi - lo)
    return max(0.08, min(x, 0.95))


def _status_style(status):
    return {
        "开放申购": (C_OPEN, "开放"),
        "限大额": (C_LIMIT, "限大额"),
        "暂停大额申购": (C_LIMIT, "限大额"),
        "暂停申购": (C_PAUSE, "暂停"),
    }.get(status, (C_MUTED, status or "未知"))


def _change_mark(change):
    """change: 'up'放宽 / 'down'收紧 / 'new' / None"""
    return {
        "up":   ("▲ 放宽", C_OPEN),
        "down": ("▼ 收紧", C_PAUSE),
        "new":  ("● 新增", C_GOLD),
    }.get(change, ("— 持平", C_MUTED))


def _vgradient(img):
    d = ImageDraw.Draw(img)
    top, bot = _rgb(C_BG_TOP), _rgb(C_BG_BOT)
    h = img.height
    for yy in range(h):
        k = yy / max(h - 1, 1)
        d.line([(0, yy), (W, yy)],
               fill=tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))


def _draw_limit(d, right_x, y, text, fill):
    """限额右对齐绘制：数字大字号、单位小字号；非数字文案统一 36 号。"""
    m = re.match(r"^([\d.]+)(.+)$", text)
    if not m:
        f = _font(36)
        w = d.textlength(text, font=f)
        d.text((right_x - w, y + 2), text, font=f, fill=fill)
        return
    num, unit = m.group(1), m.group(2)
    nf, uf = _font(46), _font(24)
    nw, uw = d.textlength(num, font=nf), d.textlength(unit, font=uf)
    d.text((right_x - uw, y + 22), unit, font=uf, fill=fill)
    d.text((right_x - uw - 6 - nw, y - 6), num, font=nf, fill=fill)


def _pick_best(rows):
    """今日最宽松的可买基金（用于头部亮点条）。"""
    best, best_key = None, -2.0
    for r in rows:
        if not r.get("buyable", r["status"] != "暂停申购"):
            continue
        limit = r.get("limit")
        k = float("inf") if (r["status"] == "开放申购" and limit is None) \
            else (-1.0 if limit is None else limit)
        if k > best_key:
            best, best_key = r, k
    return best


def render_card(rows: list[dict], date: datetime.date, out_path: str):
    """
    rows: [{name, code, index, status, limit, buyable, change}]，change 可为 None
    """
    H = _calc_height(rows)
    img = Image.new("RGB", (W, H), C_BG_TOP)
    _vgradient(img)
    d = ImageDraw.Draw(img)

    # 头部装饰：右上角两道淡环
    ring = _mix(C_BG_TOP, C_OPEN, 0.10)
    d.ellipse((W - 260, -120, W + 80, 220), outline=ring, width=3)
    d.ellipse((W - 180, -60, W + 20, 140), outline=ring, width=2)

    total = len(rows)
    buyable_n = sum(1 for r in rows
                    if r.get("buyable", r["status"] != "暂停申购"))

    # ---------- 头部 ----------
    y = 64
    # 品牌行：金色竖条 + 标题
    d.rounded_rectangle((M, y + 2, M + 10, y + 36), 5, fill=C_GOLD)
    d.text((M + 26, y), "标普500&纳斯达克100额度哨兵", font=_font(30), fill=C_GOLD)
    # 右侧徽章：今日可买 x/n
    badge = f"今日可买 {buyable_n}/{total}"
    bf = _font(26)
    bw = d.textlength(badge, font=bf)
    bx1, bx0 = W - M, W - M - bw - 40
    d.rounded_rectangle((bx0, y - 6, bx1, y + 42), 24, fill=C_BADGE_BG,
                        outline=C_OPEN, width=2)
    d.text((bx0 + 20, y + 1), badge, font=bf, fill=C_OPEN)
    y += 58

    weekdays = "一二三四五六日"
    date_str = f"{date.month}月{date.day}日"
    d.text((M, y), date_str, font=_font(84), fill=C_TEXT)
    dw = d.textlength(date_str, font=_font(84))
    d.text((M + dw + 24, y + 42), f"星期{weekdays[date.weekday()]} · 每日播报",
           font=_font(32), fill=C_MUTED)
    y += 116
    d.text((M, y), "标普500 / 纳指100 场外被动型基金 · 今日申购额度",
           font=_font(28, bold=False), fill=C_MUTED)
    y += 56

    # 亮点条：今日最宽松
    best = _pick_best(rows)
    d.rounded_rectangle((PX, y, W - PX, y + 68), 18,
                        fill=_mix(C_PANEL, C_GOLD, 0.06),
                        outline=_mix(C_PANEL_L, C_GOLD, 0.25), width=2)
    star_f, hl_f = _font(30), _font(27)
    d.text((M, y + 16), "★", font=star_f, fill=C_GOLD)
    if best:
        head = f"今日最宽松：{best['name']}（{best['code']}）单日可买 "
        val = _fmt_limit(best["status"], best["limit"])
        d.text((M + 48, y + 17), head, font=hl_f, fill=C_TEXT)
        hw = d.textlength(head, font=hl_f)
        d.text((M + 48 + hw, y + 17), val, font=hl_f, fill=C_GOLD)
    else:
        d.text((M + 48, y + 17), "今日监控基金全线暂停申购", font=hl_f, fill=C_PAUSE)
    y += 68 + 36

    # ---------- 分组面板 ----------
    groups = []
    for r in rows:  # 按名单出现顺序动态分组
        if not groups or groups[-1][0] != r["index"]:
            groups.append((r["index"], []))
        groups[-1][1].append(r)

    for idx_name, g in groups:
        panel_h = GROUP_HEAD + len(g) * ROW_H
        d.rounded_rectangle((PX, y, W - PX, y + panel_h), 24,
                            fill=C_PANEL, outline=C_PANEL_L, width=2)
        gy = y + 24

        # 组头：金色竖条 + 组名 + 右侧可买统计
        d.rounded_rectangle((M, gy + 4, M + 8, gy + 38), 4, fill=C_GOLD)
        d.text((M + 24, gy), idx_name, font=_font(30), fill=C_TEXT)
        g_buy = sum(1 for r in g
                    if r.get("buyable", r["status"] != "暂停申购"))
        stat_n, stat_rest = f"{g_buy}", f" / {len(g)} 只可买"
        sf = _font(24)
        sw = d.textlength(stat_n + stat_rest, font=sf)
        d.text((W - M - sw, gy + 7), stat_n, font=sf, fill=C_OPEN)
        nw = d.textlength(stat_n, font=sf)
        d.text((W - M - sw + nw, gy + 7), stat_rest, font=sf, fill=C_MUTED)
        gy += 44 + 14

        # 列头
        hf = _font(22, bold=False)
        d.text((M, gy), "基金 / 额度松紧条", font=hf, fill=C_DIM)
        d.text((SX, gy), "申购状态", font=hf, fill=C_DIM)
        right_label = "今日单人可买上限 · 较昨日"
        rw = d.textlength(right_label, font=hf)
        d.text((W - M - rw, gy), right_label, font=hf, fill=C_DIM)
        gy += 34

        for i, r in enumerate(g):
            if i:  # 行分隔线
                d.line((M, gy - 6, W - M, gy - 6), fill=C_LINE, width=1)

            buyable = r.get("buyable", r["status"] != "暂停申购")
            color, label = _status_style(r["status"])
            if not buyable:
                if r["status"] != "暂停申购":
                    label = "暂不开放"
                color = C_DIM

            # 基金名 + 代码（不可买整体弱化）
            d.text((M, gy), r["name"], font=_font(34),
                   fill=C_TEXT if buyable else C_MUTED)
            d.text((M, gy + 46), r["code"], font=_font(24, bold=False),
                   fill=C_MUTED if buyable else C_DIM)

            # 状态：光环 + 圆点 + 文字
            d.ellipse((SX - 6, gy + 8, SX + 24, gy + 38),
                      fill=_mix(C_PANEL, color, 0.22))
            d.ellipse((SX, gy + 14, SX + 18, gy + 32), fill=color)
            d.text((SX + 36, gy + 4), label, font=_font(28), fill=color)

            # 限额（右对齐，数字大/单位小）；暂停不显示数字，避免误导
            limit_str = "—" if r["status"] == "暂停申购" else _fmt_limit(
                r["status"], r["limit"])
            _draw_limit(d, W - M, gy, limit_str,
                        C_GOLD if buyable else C_DIM)

            # 较昨日
            mark, mcolor = _change_mark(r.get("change"))
            if not buyable and r.get("change") not in ("up", "down", "new"):
                mcolor = C_DIM
            mf = _font(22, bold=False)
            mw = d.textlength(mark, font=mf)
            d.text((W - M - mw, gy + 54), mark, font=mf, fill=mcolor)

            # 额度松紧条（签名元素）：不可买熄灭
            bar_y = gy + 86
            bar_w = 500
            d.rounded_rectangle((M, bar_y, M + bar_w, bar_y + 10), 5, fill=C_BAR_BG)
            t = _tightness(r["status"], r["limit"]) if buyable else 0.0
            if t > 0:
                fill_w = max(int(bar_w * t), 14)
                d.rounded_rectangle((M, bar_y, M + fill_w, bar_y + 10),
                                    5, fill=color)
                d.ellipse((M + fill_w - 7, bar_y - 2, M + fill_w + 7, bar_y + 12),
                          fill=_mix(color, "#FFFFFF", 0.35))
            gy += ROW_H

        y += panel_h + GROUP_GAP

    # ---------- 页脚 ----------
    fy = H - FOOTER_H + 36
    d.line((PX, fy, W - PX, fy), fill=C_LINE, width=2)
    fy += 24
    # 图例：松紧条示意
    d.rounded_rectangle((M, fy + 8, M + 110, fy + 18), 5, fill=C_BAR_BG)
    d.rounded_rectangle((M, fy + 8, M + 76, fy + 18), 5, fill=C_OPEN)
    d.text((M + 130, fy - 2), "松紧条越长 = 今日可买额度越宽松（对数刻度）",
           font=_font(22, bold=False), fill=C_MUTED)
    fy += 44
    d.text((M, fy), "数据来源：天天基金网公开页面 / 基金公司公告（以公告为准）",
           font=_font(22, bold=False), fill=C_MUTED)
    fy += 38
    d.text((M, fy),
           f"仅为公开信息整理，不构成投资建议 · 生成于 {datetime.datetime.now():%H:%M}",
           font=_font(22, bold=False), fill=C_MUTED)

    pathlib.Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
