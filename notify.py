# -*- coding: utf-8 -*-
"""
半自动发布的"最后一公里"：把当日卡片、文案、视频推送到手机，
人工花两分钟转发到微博 / 小红书 / 抖音 / B站。

支持两个通道，配了哪个环境变量就推哪个（GitHub Secrets 注入）：
  WECOM_WEBHOOK   企业微信群机器人 webhook 完整 URL
  TG_BOT_TOKEN + TG_CHAT_ID   Telegram 机器人

用法：python notify.py [YYYY-MM-DD]
"""

import io
import os
import re
import sys
import json
import base64
import hashlib
import pathlib
import datetime

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(__file__).parent


# ---------------- 企业微信群机器人 ----------------

def _wecom_key(webhook: str) -> str:
    return re.search(r"key=([\w-]+)", webhook).group(1)


def wecom_text(webhook: str, text: str):
    requests.post(webhook, json={"msgtype": "text",
                                 "text": {"content": text[:2000]}}, timeout=15)


def wecom_image(webhook: str, path: pathlib.Path):
    data = path.read_bytes()
    if len(data) <= 2 * 1024 * 1024:  # 图片消息限 2MB
        requests.post(webhook, json={
            "msgtype": "image",
            "image": {"base64": base64.b64encode(data).decode(),
                      "md5": hashlib.md5(data).hexdigest()},
        }, timeout=30)
    else:
        wecom_file(webhook, path)


def wecom_file(webhook: str, path: pathlib.Path):
    """通过 upload_media 发文件消息（限 20MB）。"""
    if path.stat().st_size > 20 * 1024 * 1024:
        print(f"[warn] {path.name} 超过企业微信 20MB 限制，跳过")
        return
    key = _wecom_key(webhook)
    up = ("https://qyapi.weixin.qq.com/cgi-bin/webhook/"
          f"upload_media?key={key}&type=file")
    with path.open("rb") as f:
        r = requests.post(up, files={"media": (path.name, f)}, timeout=120)
    media_id = r.json().get("media_id")
    if not media_id:
        print(f"[warn] 企业微信上传失败: {r.text[:200]}")
        return
    requests.post(webhook, json={"msgtype": "file",
                                 "file": {"media_id": media_id}}, timeout=15)


# ---------------- Telegram ----------------

def tg_api(token: str, method: str, **kwargs):
    return requests.post(f"https://api.telegram.org/bot{token}/{method}",
                         timeout=120, **kwargs)


def tg_send(token: str, chat: str, text: str,
            photo: pathlib.Path | None, video: pathlib.Path | None):
    tg_api(token, "sendMessage", data={"chat_id": chat, "text": text[:4000]})
    if photo and photo.exists():
        with photo.open("rb") as f:
            r = tg_api(token, "sendPhoto",
                       data={"chat_id": chat}, files={"photo": f})
        if not r.json().get("ok"):   # 长图可能被拒，退化为文件
            with photo.open("rb") as f:
                tg_api(token, "sendDocument",
                       data={"chat_id": chat}, files={"document": f})
    if video and video.exists():
        with video.open("rb") as f:
            tg_api(token, "sendVideo",
                   data={"chat_id": chat}, files={"video": f})


# ---------------- 主流程 ----------------

def main():
    date = (datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
            else datetime.date.today())
    d = date.isoformat()
    card = ROOT / "output" / f"card_{d}.png"
    video = ROOT / "output" / f"video_{d}.mp4"
    weibo = ROOT / "output" / f"weibo_{d}.txt"
    xhs = ROOT / "output" / f"xhs_{d}.txt"
    snap = ROOT / "data" / f"{d}.json"

    rows = json.loads(snap.read_text(encoding="utf-8")) if snap.exists() else []
    buyable = sum(1 for r in rows
                  if r.get("buyable", r.get("status") != "暂停申购"))
    changed = sum(1 for r in rows if r.get("change") in ("up", "down"))
    summary = (
        f"📊 {date.month}月{date.day}日 额度日报已生成\n"
        f"可买 {buyable}/{len(rows)} 只，较昨日变化 {changed} 条\n"
        f"——以下依次为：长图卡片 / 播报视频 / 微博文案 / 小红书文案，"
        f"请转发到各平台"
    )

    webhook = os.environ.get("WECOM_WEBHOOK", "").strip()
    tg_token = os.environ.get("TG_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not webhook and not (tg_token and tg_chat):
        print("未配置 WECOM_WEBHOOK 或 TG_BOT_TOKEN/TG_CHAT_ID，跳过推送")
        return

    weibo_txt = weibo.read_text(encoding="utf-8") if weibo.exists() else ""
    xhs_txt = xhs.read_text(encoding="utf-8") if xhs.exists() else ""

    if webhook:
        wecom_text(webhook, summary)
        if card.exists():
            wecom_image(webhook, card)
        if video.exists():
            wecom_file(webhook, video)
        if weibo_txt:
            wecom_text(webhook, "【微博文案】\n" + weibo_txt)
        if xhs_txt:
            wecom_text(webhook, "【小红书文案】\n" + xhs_txt)
        print("已推送到企业微信")

    if tg_token and tg_chat:
        tg_send(tg_token, tg_chat,
                summary + "\n\n【微博文案】\n" + weibo_txt
                + "\n\n【小红书文案】\n" + xhs_txt,
                card if card.exists() else None,
                video if video.exists() else None)
        print("已推送到 Telegram")


if __name__ == "__main__":
    main()
