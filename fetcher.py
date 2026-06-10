# -*- coding: utf-8 -*-
"""
从天天基金抓取基金的申购状态与单日累计申购限额。

数据源（按顺序尝试）：
  1. 基金主页  https://fund.eastmoney.com/{code}.html
     页面含 "购买状态" 与 "该基金单日累计购买上限为 xxx 元" 等文案
  2. F10 费率页 https://fundf10.eastmoney.com/jjfl_{code}.html
     含 "申购状态" 表格，作为兜底

抓不到限额数字但状态为"限大额"时，limit 返回 None，文案中显示"见公告"。
解析失败时会把原始 HTML 存到 debug/ 目录，方便你更新正则。
"""

import re
import time
import json
import pathlib
import datetime

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

DEBUG_DIR = pathlib.Path(__file__).parent / "debug"

# 申购状态关键词，按"更具体的在前"排序避免误匹配
STATUS_PATTERNS = [
    "暂停大额申购",
    "暂停申购",
    "限大额",
    "开放申购",
    "认购期",
    "封闭期",
]

# 限额文案的几种常见写法（只在"交易状态"区块内匹配，避免误吃广告/股吧标题）
LIMIT_RES = [
    re.compile(r"单日累计(?:购买|申购)(?:上限|限额)[为：:]*\s*([\d,，.]+)\s*(万)?\s*元"),
    re.compile(r"单日(?:每个基金账户)?(?:的)?累计申购.{0,12}?([\d,，.]+)\s*(万)?\s*元"),
    re.compile(r"限额\s*([\d,，.]+)\s*(万)?\s*元"),
]

# F10 费率页的"申购状态"表格，作为交易状态区块缺失时的兜底
F10_STATUS_RE = re.compile(r"申购状态\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*<")
F10_LIMIT_RE = re.compile(
    r"日累计申购限额\s*</td>\s*<td[^>]*>\s*([\d,，.]+)\s*(万)?\s*元")


def _parse_limit(text: str):
    """从页面文本中提取限额（单位：元），找不到返回 None。"""
    for pattern in LIMIT_RES:
        m = pattern.search(text)
        if m:
            num = float(m.group(1).replace(",", "").replace("，", ""))
            if m.group(2):  # "万"
                num *= 10000
            return num
    return None


def _parse_status(text: str):
    for kw in STATUS_PATTERNS:
        if kw in text:
            return kw
    return None


def _extract_trade_block(html: str):
    """
    截取"交易状态"附近的纯文本。

    主页（buyWayStatic 区块）与 F10 页都用"交易状态："引出本基金的
    申购状态和单日限额，如：
      交易状态：暂停申购 (单日累计购买上限100.00元) 开放赎回
    整页搜索会误吃股吧帖子标题、公告列表、活期宝广告里的同类字样，
    所以状态/限额只在这个小窗口内解析。
    """
    for m in re.finditer("交易状态", html):
        window = re.sub(r"<[^>]+>", " ", html[m.start():m.start() + 500])
        if _parse_status(window):
            return window
    return None


def _save_debug(code: str, source: str, html: str):
    DEBUG_DIR.mkdir(exist_ok=True)
    path = DEBUG_DIR / f"{code}_{source}.html"
    path.write_text(html, encoding="utf-8")


def fetch_one(code: str, session: requests.Session | None = None) -> dict:
    """
    抓取单只基金，返回:
    {"code", "status", "limit", "source", "ok", "error"}
    limit 单位为元；状态开放申购时 limit 为 None 表示不限额。
    """
    sess = session or requests.Session()
    result = {"code": code, "status": None, "limit": None, "buyable": False,
              "source": None, "ok": False, "error": None}

    sources = [
        ("main", f"https://fund.eastmoney.com/{code}.html"),
        ("f10", f"https://fundf10.eastmoney.com/jjfl_{code}.html"),
    ]

    for name, url in sources:
        try:
            resp = sess.get(url, headers=HEADERS, timeout=15)
            resp.encoding = resp.apparent_encoding or "utf-8"
            html = resp.text
        except requests.RequestException as exc:
            result["error"] = f"{name}: {exc}"
            continue

        block = _extract_trade_block(html)
        status = _parse_status(block) if block else None
        limit = _parse_limit(block) if block else None

        if status is None and name == "f10":
            # F10 页兜底：申购状态表格
            m = F10_STATUS_RE.search(html)
            if m:
                status = _parse_status(m.group(1))
            m = F10_LIMIT_RE.search(html)
            if m:
                limit = float(m.group(1).replace(",", "").replace("，", ""))
                if m.group(2):
                    limit *= 10000

        if status is None:
            _save_debug(code, name, html)
            result["error"] = f"{name}: 交易状态区块中未识别到申购状态关键词"
            continue

        # 页面在暂停申购时也会标注单日上限，照实记录；开放申购无限额则为 None
        # buyable：暂停申购、或页面标注"暂不开放购买"（E/F/I 等特殊份额）视为不可买
        buyable = (status not in ("暂停申购", "认购期", "封闭期")
                   and "暂不开放购买" not in (block or ""))
        result.update(status=status, limit=limit, buyable=buyable,
                      source=name, ok=True, error=None)
        return result

    return result


def fetch_all(funds: list[dict], delay: float = 2.0) -> list[dict]:
    """批量抓取。delay 是请求间隔（秒），保持克制，每天只跑一次就够了。"""
    sess = requests.Session()
    rows = []
    for fund in funds:
        info = fetch_one(fund["code"], sess)
        rows.append({**fund, **info})
        time.sleep(delay)
    return rows


def load_mock() -> list[dict]:
    """本地开发用的模拟数据，跑通渲染和文案流程（不依赖具体名单）。"""
    from funds import FUNDS
    samples = [("限大额", 1000.0), ("限大额", 100.0), ("暂停申购", 100.0),
               ("开放申购", None), ("限大额", 100000.0)]
    rows = []
    for i, f in enumerate(FUNDS):
        status, limit = samples[i % len(samples)]
        rows.append({**f, "status": status, "limit": limit,
                     "buyable": status != "暂停申购",
                     "source": "mock", "ok": True, "error": None})
    return rows


if __name__ == "__main__":
    from funds import FUNDS
    data = fetch_all(FUNDS)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    today = datetime.date.today().isoformat()
    out = pathlib.Path(__file__).parent / "data" / f"{today}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
