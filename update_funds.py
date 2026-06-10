# -*- coding: utf-8 -*-
"""
从天天基金官方代码表自动生成 funds.py，避免手工维护名单出错
（曾把 011323 国泰智能汽车股票C 误当成天弘标普500A）。

筛选规则：
  1. 名称含 标普500 / 纳斯达克100 / 纳指100
  2. 类型为 指数型-海外股票（被动指数；剔除 QDII-FOF、主动型）
  3. 剔除场内 ETF（代码 159 / 51 开头，无场外申购额度概念）
  4. 剔除美元份额（美元/美钞/美汇/现汇/现钞），只保留人民币份额

用法：python update_funds.py   # 重新生成 funds.py
"""

import io
import re
import sys
import json
import pathlib

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"}
URL = "https://fund.eastmoney.com/js/fundcode_search.js"

# 展示用短名称：去掉这些冗余词（顺序敏感，长的在前）
STRIP_WORDS = [
    "ETF发起式联接", "ETF发起联接", "ETF联接", "指数发起式", "指数发起",
    "发起式联接", "发起式", "发起", "指数", "(QDII-LOF)", "(QDII-FOF)",
    "(QDII)", "(人民币)", "人民币",
]


def short_name(name: str) -> str:
    s = name
    for w in STRIP_WORDS:
        s = s.replace(w, "")
    s = s.replace("等权重", "等权").replace("纳斯达克100", "纳指100")
    return s


def classify(name: str):
    if "标普500" in name:
        return "标普500"
    return "纳指100"


def main():
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    data = json.loads(re.search(r"\[\[.*\]\]", r.text, re.S).group(0))

    rows = []
    for code, _, name, ftype, _ in data:
        if not re.search(r"标普500|纳斯达克100|纳指100", name):
            continue
        if ftype != "指数型-海外股票":
            continue
        if code.startswith(("159", "51")):
            continue
        if re.search(r"美元|美钞|美汇|现汇|现钞", name):
            continue
        if "等权" in name:  # 标普500等权重跟踪的是另一条指数，不在监控范围
            continue
        rows.append({"code": code, "name": short_name(name),
                     "full_name": name, "index": classify(name)})

    order = {"标普500": 0, "纳指100": 1}
    rows.sort(key=lambda x: (order[x["index"]], x["name"], x["code"]))

    lines = [
        "# -*- coding: utf-8 -*-",
        '"""',
        "监控的基金清单（由 update_funds.py 自动生成，请勿手工编辑）。",
        "数据源：天天基金官方基金代码表 fundcode_search.js",
        "范围：标普500 / 纳指100 被动指数场外基金，人民币份额（不含等权重）。",
        '"""',
        "",
        "FUNDS = [",
    ]
    cur = None
    for x in rows:
        if x["index"] != cur:
            cur = x["index"]
            lines.append(f"    # ---- {cur} ----")
        lines.append(
            f'    {{"code": "{x["code"]}", "name": "{x["name"]}", '
            f'"index": "{x["index"]}", "full_name": "{x["full_name"]}"}},')
    lines += ["]", ""]

    out = pathlib.Path(__file__).parent / "funds.py"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {out}，共 {len(rows)} 只：")
    for x in rows:
        print(f'  {x["code"]} {x["index"]:<7} {x["name"]:<16} {x["full_name"]}')


if __name__ == "__main__":
    main()
