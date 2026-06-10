# -*- coding: utf-8 -*-
"""
30秒竖版播报视频（抖音 / B站）：
  当日长图卡片自上而下缓慢滚动 + edge-tts 中文配音。

流程：
  1. 从 data/{date}.json 生成播报文稿（≈30秒口播量）
  2. edge-tts 合成配音 mp3（微软晓晓，免费、无需密钥）
  3. ffmpeg 把 output/card_{date}.png 做成 1080x1920 滚动视频并混入配音
     （ffmpeg 优先用系统的，否则用 imageio-ffmpeg 自带二进制）

用法：python video.py [YYYY-MM-DD]
产出：output/video_{date}.mp4
"""

import io
import re
import sys
import json
import shutil
import asyncio
import pathlib
import datetime
import subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = pathlib.Path(__file__).parent
VOICE = "zh-CN-XiaoxiaoNeural"
HEAD_HOLD = 2.0   # 开头停留秒数（露出标题区）
TAIL_HOLD = 2.0   # 结尾停留秒数


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _fmt_limit_speech(status, limit):
    if status == "开放申购" and limit is None:
        return "不限额"
    if limit is None:
        return "额度见公告"
    if limit >= 10000:
        return f"{limit / 10000:g}万元"
    return f"{limit:g}元"


def _group_speech(rows, idx_name):
    g = [r for r in rows if r["index"] == idx_name]
    buyable = [r for r in g if r.get("buyable", r["status"] != "暂停申购")]
    if not buyable:
        return f"{idx_name}全部暂停申购"
    best = buyable[0]  # rows 已按宽松度排序
    n = len(buyable)
    return (f"{idx_name}有{n}只可买，最宽松的是{best['name']}，"
            f"单日可买{_fmt_limit_speech(best['status'], best['limit'])}")


def build_narration(rows, date: datetime.date) -> str:
    total = len(rows)
    buyable_n = sum(1 for r in rows
                    if r.get("buyable", r["status"] != "暂停申购"))
    ups = [r for r in rows if r.get("change") == "up"]
    downs = [r for r in rows if r.get("change") == "down"]
    if ups or downs:
        bits = []
        if ups:
            bits.append(f"{len(ups)}只放宽" + (f"，包括{ups[0]['name']}" if len(ups) <= 2 else ""))
        if downs:
            bits.append(f"{len(downs)}只收紧" + (f"，包括{downs[0]['name']}" if len(downs) <= 2 else ""))
        change_txt = "较昨日" + "，".join(bits) + "。"
    else:
        change_txt = "额度与昨日持平。"

    return (
        f"{date.month}月{date.day}日，美股指数基金额度播报。"
        f"标普500和纳指100场外基金共{total}只，今日{buyable_n}只可以买入。"
        f"{_group_speech(rows, '标普500')}。"
        f"{_group_speech(rows, '纳指100')}。"
        f"{change_txt}"
        f"完整名单见画面。数据来自天天基金及基金公司公告，不构成投资建议。"
    )


def tts(text: str, mp3_path: pathlib.Path):
    import edge_tts

    async def run():
        await edge_tts.Communicate(text, VOICE, rate="+8%").save(str(mp3_path))

    asyncio.run(run())


def media_duration(ffmpeg: str, path: pathlib.Path) -> float:
    p = subprocess.run([ffmpeg, "-i", str(path)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        raise RuntimeError(f"无法读取时长: {path}")
    h, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def render(ffmpeg: str, card_png: pathlib.Path, mp3: pathlib.Path | None,
           out_mp4: pathlib.Path):
    from PIL import Image
    img_h = Image.open(card_png).height

    dur = (media_duration(ffmpeg, mp3) + 1.0) if mp3 else 30.0
    scroll = max(img_h - 1920, 0)
    scroll_t = max(dur - HEAD_HOLD - TAIL_HOLD, 1.0)
    # y(t)：先停 HEAD_HOLD 秒，再匀速滚到底，最后停 TAIL_HOLD 秒
    y_expr = f"{scroll}*min(max(t-{HEAD_HOLD},0)/{scroll_t},1)"
    vf = (f"crop=1080:1920:0:'{y_expr}'" if scroll > 0
          else f"pad=1080:1920:0:(1920-{img_h})/2:0x0A2E22")

    cmd = [ffmpeg, "-y", "-loop", "1", "-i", str(card_png)]
    if mp3:
        cmd += ["-i", str(mp3)]
    cmd += ["-filter_complex", f"[0:v]{vf},format=yuv420p[v]",
            "-map", "[v]"]
    if mp3:
        cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-t", f"{dur:.2f}", "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-movflags", "+faststart", str(out_mp4)]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败:\n{p.stderr[-2000:]}")


def main():
    date = (datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
            else datetime.date.today())
    snap = ROOT / "data" / f"{date.isoformat()}.json"
    card = ROOT / "output" / f"card_{date.isoformat()}.png"
    out = ROOT / "output" / f"video_{date.isoformat()}.mp4"
    if not snap.exists() or not card.exists():
        sys.exit(f"缺少 {snap.name} 或 {card.name}，请先运行 main.py")

    rows = json.loads(snap.read_text(encoding="utf-8"))
    text = build_narration(rows, date)
    print("播报文稿:", text)

    ffmpeg = find_ffmpeg()
    mp3 = ROOT / "output" / f"voice_{date.isoformat()}.mp3"
    try:
        tts(text, mp3)
    except Exception as exc:
        print(f"[warn] TTS 失败（{exc}），输出无声视频")
        mp3 = None

    render(ffmpeg, card, mp3, out)
    print(f"完成：{out}（{media_duration(ffmpeg, out):.1f} 秒）")


if __name__ == "__main__":
    main()
