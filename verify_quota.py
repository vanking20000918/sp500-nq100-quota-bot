# -*- coding: utf-8 -*-
"""
独立核对脚本：逐只基金抓 F10 费率页（与主流程的基金主页不同源），
比对三项并报告差异：
  1. 页面标题里的基金名称 vs funds.py 的 full_name（防代码-名称错配）
  2. F10「申购状态」表格 vs 快照 status
  3. F10「交易状态」行 / 「日累计申购限额」表格 vs 快照 limit

用法：python verify_quota.py [data/YYYY-MM-DD.json]
"""

import io
import re
import sys
import json
import time
import pathlib
import datetime

import requests

import fetcher
from funds import FUNDS

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# F10 页标题形如 "华夏标普500ETF发起式联接(QDII)A(人民币)(018064)基金费率 ..."
TITLE_RE = re.compile(r"<title>\s*(.+?)\((\d{6})\)")


def f10_truth(html: str):
    """从 F10 页提取 (标题名称, 状态, 限额)。"""
    title = TITLE_RE.search(html)
    name, title_code = (title.group(1).strip(), title.group(2)) if title else (None, None)

    block = fetcher._extract_trade_block(html)
    status = fetcher._parse_status(block) if block else None
    limit = fetcher._parse_limit(block) if block else None

    if status is None:
        m = fetcher.F10_STATUS_RE.search(html)
        if m:
            status = fetcher._parse_status(m.group(1))
    if limit is None:
        m = fetcher.F10_LIMIT_RE.search(html)
        if m:
            limit = float(m.group(1).replace(",", "").replace("，", ""))
            if m.group(2):
                limit *= 10000
    return name, title_code, status, limit


def main():
    snap_path = (pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else
                 pathlib.Path("data") / f"{datetime.date.today().isoformat()}.json")
    snap = {r["code"]: r for r in json.loads(snap_path.read_text(encoding="utf-8"))}

    sess = requests.Session()
    bad = 0
    for f in FUNDS:
        code = f["code"]
        row = snap.get(code)
        if row is None:
            print(f"MISS {code} {f['name']}  快照中缺失（抓取失败？）")
            bad += 1
            continue
        url = f"https://fundf10.eastmoney.com/jjfl_{code}.html"
        try:
            resp = sess.get(url, headers=fetcher.HEADERS, timeout=15)
            resp.encoding = resp.apparent_encoding or "utf-8"
            page_name, title_code, status, limit = f10_truth(resp.text)
        except requests.RequestException as exc:
            print(f"ERR  {code} {f['name']}  f10 请求失败: {exc}")
            bad += 1
            continue

        problems = []
        full = f.get("full_name", f["name"])
        if title_code and title_code != code:
            problems.append(f"代码不符: 页面[{title_code}] 名单[{code}]")
        if page_name and page_name != full:
            problems.append(f"名称不符: 页面[{page_name}] 名单[{full}]")
        if status != row["status"]:
            problems.append(f"状态不符: f10[{status}] 快照[{row['status']}]")
        if limit != row["limit"]:
            problems.append(f"限额不符: f10[{limit}] 快照[{row['limit']}]")

        if problems:
            bad += 1
            print(f"FAIL {code} {f['name']}  " + "；".join(problems))
        else:
            print(f"OK   {code} {f['name']:<14} {row['status']} limit={row['limit']}")
        time.sleep(1.0)

    print(f"\n核对完成：{len(FUNDS)} 只，{bad} 项异常" if bad else
          f"\n核对完成：{len(FUNDS)} 只全部一致")


if __name__ == "__main__":
    main()
