# -*- coding: utf-8 -*-
"""诊断脚本：抓取每只基金页面存入 debug/，并打印申购状态/限额关键词附近的上下文。"""
import io
import re
import sys
import time
import pathlib

import requests

from funds import FUNDS
from fetcher import HEADERS

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DEBUG = pathlib.Path(__file__).parent / "debug"
DEBUG.mkdir(exist_ok=True)

KEYWORDS = ["购买状态", "申购状态", "单日累计", "限大额", "暂停大额", "暂停申购", "开放申购", "限额"]

sess = requests.Session()
for f in FUNDS:
    code = f["code"]
    print("=" * 70)
    print(code, f["name"])
    for name, url in [("main", f"https://fund.eastmoney.com/{code}.html"),
                      ("f10", f"https://fundf10.eastmoney.com/jjfl_{code}.html")]:
        try:
            r = sess.get(url, headers=HEADERS, timeout=15)
            r.encoding = r.apparent_encoding or "utf-8"
            html = r.text
        except Exception as e:
            print(f"  [{name}] 请求失败: {e}")
            continue
        (DEBUG / f"{code}_{name}.html").write_text(html, encoding="utf-8")
        # 去掉 script/style 后找关键词上下文
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        seen = set()
        print(f"  [{name}] {url}  len={len(html)}")
        for kw in KEYWORDS:
            for m in re.finditer(re.escape(kw), text):
                ctx = text[max(0, m.start() - 120): m.end() + 160]
                ctx = re.sub(r"\s+", " ", ctx)
                if ctx in seen:
                    continue
                seen.add(ctx)
                print(f"    <{kw}> ...{ctx}...")
    time.sleep(1.5)
