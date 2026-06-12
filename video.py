# -*- coding: utf-8 -*-
"""
播报视频 V2（抖音 / B站，1080x1920 竖版）：
  5 幕大字分镜替代长图慢滚 —— 封面 → 各指数档位榜 → 较昨日变动 → 落版。
  每幕一张 PNG 帧（card.render_scene_*），edge-tts 分段配音，
  幕时长 = 该段配音时长 + 0.5s，ffmpeg 逐幕合成后 concat 拼接。

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

import card

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "output"
VOICE = "zh-CN-XiaoxiaoNeural"
PAD = 0.5          # 每幕配音后的留白秒数
MIN_DUR = 2.8      # 每幕最短时长


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


def _buyable(r):
    return r.get("buyable", r["status"] != "暂停申购")


def build_scenes(rows, date: datetime.date):
    """返回 [{kind, narration, subtitle, default_dur, ...}]，与帧渲染一一对应。"""
    total = len(rows)
    buyable_n = sum(1 for r in rows if _buyable(r))
    ups = [r for r in rows if r.get("change") == "up"]
    downs = [r for r in rows if r.get("change") == "down"]

    groups = []
    for r in rows:
        if not groups or groups[-1][0] != r["index"]:
            groups.append((r["index"], []))
        groups[-1][1].append(r)

    scenes = [{
        "kind": "cover",
        "narration": (f"{date.month}月{date.day}日，美股指数基金额度播报。"
                      f"{total}只基金，今日{buyable_n}只可以买入。"),
        "subtitle": f"{date.month}月{date.day}日 · 今日可买 {buyable_n}/{total}",
        "default_dur": 4.0,
    }]

    watermarks = {"标普500": "S&P 500", "纳指100": "NASDAQ-100"}
    for idx_name, g in groups:
        g_buy = [r for r in g if _buyable(r)]
        if not g_buy:
            narration = f"{idx_name}今日全部暂停申购。"
            subtitle = f"{idx_name}：全部暂停申购"
        else:
            best = g_buy[0]   # rows 已按宽松度排序
            val = _fmt_limit_speech(best["status"], best["limit"])
            _, tiers = card._tier_model(g)
            tier_txt = f"分{len(tiers)}个档位，" if len(tiers) > 1 else ""
            narration = (f"{idx_name}有{len(g_buy)}只可买，{tier_txt}"
                         f"最宽松的是{best['name']}，单日可买{val}。")
            subtitle = f"{idx_name}：{len(g_buy)} 只可买，最宽松单日 {val}"
        scenes.append({
            "kind": "group", "idx_name": idx_name, "g": g,
            "watermark": watermarks.get(idx_name, ""),
            "narration": narration, "subtitle": subtitle,
            "default_dur": 7.0,
        })

    if ups or downs:
        bits = []
        if downs:
            bits.append(f"{card._merged_names(downs)}收紧")
        if ups:
            bits.append(f"{card._merged_names(ups)}放宽")
        first = (downs or ups)[0]
        delta = ""
        if first.get("prev_limit") is not None and first.get("limit") is not None:
            delta = f"，从{first['prev_limit']:g}元变为{first['limit']:g}元"
        narration = f"注意，{'，'.join(bits)}{delta}，其余持平。"
        subtitle = ("▼ " if downs else "▲ ") + \
            card._merged_names(downs or ups) + ("收紧" if downs else "放宽")
    else:
        narration = "所有基金额度与昨日持平。"
        subtitle = "额度与昨日持平"
    scenes.append({"kind": "changes", "narration": narration,
                   "subtitle": subtitle, "default_dur": 5.5})

    scenes.append({
        "kind": "outro",
        "narration": "完整名单见图文版。数据来自天天基金及基金公司公告，不构成投资建议。",
        "subtitle": "完整名单见图文版 · 明早 8:30 见",
        "default_dur": 5.0,
    })
    return scenes


def render_frames(scenes, rows, date, tmp: pathlib.Path):
    n = len(scenes)
    for i, s in enumerate(scenes):
        png = tmp / f"scene_{i}.png"
        if s["kind"] == "cover":
            card.render_scene_cover(rows, date, str(png), i, n, s["subtitle"])
        elif s["kind"] == "group":
            card.render_scene_group(s["idx_name"], s["g"], s["watermark"],
                                    str(png), i, n, s["subtitle"])
        elif s["kind"] == "changes":
            card.render_scene_changes(rows, str(png), i, n, s["subtitle"])
        else:
            card.render_scene_outro(str(png), i, n, s["subtitle"])
        s["png"] = png


def tts_all(scenes, tmp: pathlib.Path):
    """逐幕合成配音；任一失败则全部静音（保证视频仍能产出）。"""
    try:
        import edge_tts

        async def run():
            for i, s in enumerate(scenes):
                mp3 = tmp / f"scene_{i}.mp3"
                await edge_tts.Communicate(
                    s["narration"], VOICE, rate="+8%").save(str(mp3))
                s["mp3"] = mp3

        asyncio.run(run())
        return True
    except Exception as exc:
        print(f"[warn] TTS 失败（{exc}），输出无声视频")
        for s in scenes:
            s["mp3"] = None
        return False


def media_duration(ffmpeg: str, path: pathlib.Path) -> float:
    p = subprocess.run([ffmpeg, "-i", str(path)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        raise RuntimeError(f"无法读取时长: {path}")
    h, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败:\n{p.stderr[-2000:]}")


def render_scene_mp4(ffmpeg, s, dur, out_mp4):
    cmd = [ffmpeg, "-y", "-loop", "1", "-i", str(s["png"])]
    if s.get("mp3"):
        cmd += ["-i", str(s["mp3"])]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += [
        "-filter_complex", "[0:v]format=yuv420p[v];[1:a]apad[a]",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{dur:.2f}", "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
        str(out_mp4),
    ]
    _run(cmd)


def main():
    date = (datetime.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
            else datetime.date.today())
    snap = ROOT / "data" / f"{date.isoformat()}.json"
    if not snap.exists():
        sys.exit(f"缺少 {snap.name}，请先运行 main.py")
    rows = json.loads(snap.read_text(encoding="utf-8"))

    out = OUT / f"video_{date.isoformat()}.mp4"
    tmp = OUT / f".scenes_{date.isoformat()}"
    tmp.mkdir(parents=True, exist_ok=True)

    scenes = build_scenes(rows, date)
    print("播报文稿:")
    for s in scenes:
        print("  -", s["narration"])

    render_frames(scenes, rows, date, tmp)
    ffmpeg = find_ffmpeg()
    has_audio = tts_all(scenes, tmp)

    parts = []
    for i, s in enumerate(scenes):
        if s.get("mp3"):
            dur = max(media_duration(ffmpeg, s["mp3"]) + PAD, MIN_DUR)
        else:
            dur = s["default_dur"]
        mp4 = tmp / f"scene_{i}.mp4"
        render_scene_mp4(ffmpeg, s, dur, mp4)
        parts.append(mp4)

    lst = tmp / "concat.txt"
    lst.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in parts),
                   encoding="utf-8")
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", "-movflags", "+faststart", str(out)])

    print(f"完成：{out}（{media_duration(ffmpeg, out):.1f} 秒，"
          f"{'有' if has_audio else '无'}配音，{len(scenes)} 幕）")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
