# -*- coding: utf-8 -*-
"""
每日主流程 V2：
  python main.py          # 真实抓取
  python main.py --mock   # 用模拟数据跑通流程

产出（output/ 目录）：
  cover_YYYY-MM-DD.png     封面卡（视频封面用，信息流钩子）
  card_YYYY-MM-DD.png      额度详情长图（完整名单，档位聚类版）
  text_YYYY-MM-DD.txt      通用文案（不分平台）
同时把当日快照写入 data/，用于次日对比"放宽/收紧"。
"""

import sys
import json
import pathlib
import datetime

from funds import FUNDS
import fetcher
import card

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output"


def load_snapshot(date: datetime.date):
    p = DATA / f"{date.isoformat()}.json"
    if p.exists():
        return {r["code"]: r for r in json.loads(p.read_text(encoding="utf-8"))}
    return {}


def diff_change(today_row, yesterday):
    """对比昨日：额度变大/状态变开放=up，变小/暂停=down，新基金=new。"""
    prev = yesterday.get(today_row["code"])
    if prev is None:
        return "new" if yesterday else None
    rank = {"暂停申购": 0, "暂停大额申购": 1, "限大额": 1, "开放申购": 2}
    a, b = rank.get(prev.get("status"), 1), rank.get(today_row.get("status"), 1)
    if b != a:
        return "up" if b > a else "down"
    pl, tl = prev.get("limit"), today_row.get("limit")
    if pl == tl:
        return None
    if tl is None:
        return "up"
    if pl is None:
        return "down"
    return "up" if tl > pl else "down"


def fmt(row):
    return card._fmt_limit(row["status"], row["limit"])


STATUS_RANK = {"开放申购": 2, "暂停大额申购": 1, "限大额": 1, "暂停申购": 0}


def sort_rows(rows):
    """组内排序：可买在前，额度从宽到窄，限额未知(见公告)次之，暂停垫底。"""
    group_order = {}
    for r in rows:
        group_order.setdefault(r["index"], len(group_order))

    def key(r):
        limit = r.get("limit")
        if r.get("status") == "开放申购" and limit is None:
            lk = float("inf")          # 不限额最宽松
        elif limit is None:
            lk = -1.0                  # 见公告排在有数字的后面
        else:
            lk = limit
        return (group_order[r["index"]],
                0 if r.get("buyable", True) else 1,
                -STATUS_RANK.get(r.get("status"), 1),
                -lk,
                r["name"])

    return sorted(rows, key=key)


def write_copy(rows, date, changes_exist):
    """生成通用文案（不分平台，发哪儿都用这一份）。"""
    date_str = f"{date.month}月{date.day}日"
    lines_by_index = {}
    for r in rows:
        mark = {"up": "⬆️", "down": "⬇️", "new": "🆕"}.get(r.get("change"), "")
        lines_by_index.setdefault(r["index"], []).append(
            f"{r['name']}({r['code']})：{fmt(r)} {mark}".rstrip()
        )

    body = []
    for idx, lines in lines_by_index.items():
        body.append(f"【{idx}】")
        body.extend(lines)
        body.append("")
    body_txt = "\n".join(body).strip()

    headline = "今日有额度变化⚠️" if changes_exist else "今日额度与昨日持平"

    text = (
        f"{date_str} 标普500/纳指100 场外申购额度日报📋 {headline}\n\n"
        f"{body_txt}\n\n"
        "⬆️=较昨日放宽 ⬇️=收紧\n"
        "每个交易日更新，定投党建议收藏～\n"
        "数据来自天天基金及基金公司公告，以公告为准。仅为信息整理，不构成投资建议。\n\n"
        "#指数基金 #定投 #纳斯达克100 #标普500 #QDII #基金限购"
    )

    (OUT / f"text_{date.isoformat()}.txt").write_text(text, encoding="utf-8")


def main():
    mock = "--mock" in sys.argv
    today = datetime.date.today()
    DATA.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    rows = fetcher.load_mock() if mock else fetcher.fetch_all(FUNDS)

    failed = [r for r in rows if not r["ok"]]
    rows = [r for r in rows if r["ok"]]
    for f in failed:
        print(f"[warn] {f['code']} {f['name']} 抓取失败: {f['error']}")

    rows = sort_rows(rows)
    yesterday = load_snapshot(today - datetime.timedelta(days=1))
    for r in rows:
        r["change"] = diff_change(r, yesterday)
        prev = yesterday.get(r["code"])
        # 昨日限额随行带上，卡片/视频展示"100元 → 10元"用
        r["prev_limit"] = prev.get("limit") if prev else None
    changes_exist = any(r["change"] in ("up", "down") for r in rows)

    # 当日快照
    (DATA / f"{today.isoformat()}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    cover_path = OUT / f"cover_{today.isoformat()}.png"
    card_path = OUT / f"card_{today.isoformat()}.png"
    card.render_cover(rows, today, str(cover_path))
    card.render_card(rows, today, str(card_path))
    write_copy(rows, today, changes_exist)

    print(f"完成：{cover_path}")
    print(f"      {card_path}")
    print(f"      {OUT / f'text_{today.isoformat()}.txt'}")


if __name__ == "__main__":
    main()
