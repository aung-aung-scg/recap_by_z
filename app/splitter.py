"""Splitter: one video -> parts of N minutes, each with the chosen frame (Original / 16:9 / 9:16 / 1:1 with a
blurred background), an optional text box and an optional "Part 1" label.

Smart cut: when a part's time is up in the middle of speech, the cut waits for the next pause (up to
`max_extra` seconds later, 20 by default) so no sentence is cut in two; off = exact N-minute cuts.
Every part is re-encoded, so cuts land exactly on the planned time (stream copy would jump to key frames).
No UI here: the Splitter tab (splitter_tab.py) calls split_video() from a thread.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import numpy as np

from core import _visual_filters, ffmpeg_encoders, frame_layout, output_canvas, probe_video_size

LogFn = Callable[[str], None]

LEVEL_RATE = 8000             # audio is read at 8 kHz mono: enough to hear where speech stops
LEVEL_FRAME = 0.05            # one loudness value per 50 ms
PAUSE_BELOW_SPEECH_DB = 18.0  # silence: this much quieter than the video's speech level …
PAUSE_ABOVE_FLOOR_DB = 6.0    # … or, under background music, close to the quietest sound around the cut
GOOD_PAUSE_SEC = 0.3          # a pause this long is taken as the end of a sentence; shorter = a breath
MIN_TAIL_SEC = 20.0           # a last piece shorter than this (and than a quarter part) joins the part before it
SPLIT_STATE = ".split_state.json"


MM_DIGITS = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")


def part_label(template: str, n: int, total: int) -> str:
    """"Part {n}" -> "Part 2"; {mm} = the number in Myanmar digits (အပိုင်း {mm} -> အပိုင်း ၂); {total} = how many
    parts, in Myanmar digits too when the label uses {mm} ("အပိုင်း {mm}/{total}" -> "အပိုင်း ၂/၅", not "၂/5")."""
    text = str(template or "")
    total_text = str(total).translate(MM_DIGITS) if "{mm}" in text else str(total)
    return text.replace("{n}", str(n)).replace("{mm}", str(n).translate(MM_DIGITS))         .replace("{total}", total_text).strip()


def audio_levels(ffmpeg: str, source: str | Path) -> np.ndarray | None:
    """Loudness (dBFS) of every 50 ms of the video's sound; None when it has no sound."""
    cmd = [ffmpeg, "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", str(LEVEL_RATE),
           "-f", "s16le", "pipe:1"]
    hop = int(LEVEL_RATE * LEVEL_FRAME)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    levels: list[np.ndarray] = []
    rest = np.zeros(0, dtype=np.float32)
    try:
        while True:
            chunk = proc.stdout.read(hop * 2 * 4000)      # ~200 s of sound at a time
            if not chunk:
                break
            data = np.concatenate([rest, np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768.0])
            usable = len(data) // hop * hop
            frames = data[:usable].reshape(-1, hop)
            rest = data[usable:]
            levels.append(10.0 * np.log10(np.mean(frames * frames, axis=1) + 1e-10))
    finally:
        proc.stdout.close()
        proc.wait()
    if not levels:
        return None
    return np.concatenate(levels)


def speech_level(levels: np.ndarray) -> float:
    """How loud the speech of this video is (90th percentile of its sounding 50 ms frames)."""
    sounding = levels[levels > -70.0]
    return float(np.percentile(sounding, 90)) if len(sounding) else -20.0


def quiet_point(levels: np.ndarray, start: float, end: float, speech_db: float) -> tuple[float, str]:
    """Where to cut between start (the part's time is up) and end (start + the extra seconds allowed).

    Speech already over at `start` (a pause of 0.3 s+ running through it) -> cut in that pause. Otherwise the
    longest pause before `end` - the likeliest end of a sentence - taking the earliest when several are nearly as
    long; no pause at all (music, shouting) -> the quietest moment. Returns (seconds, "pause" | "breath" |
    "quietest")."""
    i0 = max(0, int(round(start / LEVEL_FRAME)))
    i1 = min(len(levels) - 1, int(round(end / LEVEL_FRAME)))
    if i1 <= i0:
        return start, "exact"
    floor = float(np.percentile(levels[i0:i1 + 1], 10))
    quiet = levels <= max(speech_db - PAUSE_BELOW_SPEECH_DB, floor + PAUSE_ABOVE_FLOOR_DB)
    lo, hi = max(0, i0 - int(3.0 / LEVEL_FRAME)), min(len(levels) - 1, i1 + int(3.0 / LEVEL_FRAME))
    runs: list[tuple[int, int]] = []
    i = lo
    while i <= hi:
        if not quiet[i]:
            i += 1
            continue
        a = b = i
        while b + 1 <= hi and (quiet[b + 1] or (b + 2 <= hi and quiet[b + 2])):   # one loud 50 ms blip is no end
            b += 1
        runs.append((a, b))
        i = b + 1
    good = round(GOOD_PAUSE_SEC / LEVEL_FRAME)

    def middle(a: int, b: int) -> float:
        return round(((max(a, i0) + b) / 2.0 + 0.5) * LEVEL_FRAME, 3)     # never before the part's time is up

    for a, b in runs:
        if a <= i0 <= b and b - a + 1 >= good and b - i0 >= 3:      # and still 0.2 s of it left to cut in
            return middle(a, b), "pause"
    later = [(a, b) for a, b in runs if i0 <= a <= i1]
    if later:
        longest = max(b - a + 1 for a, b in later)
        if longest >= 2:
            a, b = next(r for r in later if r[1] - r[0] + 1 >= 0.8 * longest)
            return middle(a, b), "pause" if b - a + 1 >= good else "breath"
    power = np.convolve(10.0 ** (levels[i0:i1 + 1] / 10.0), np.ones(4) / 4, mode="same")
    j = i0 + int(np.argmin(power))
    return round((j + 0.5) * LEVEL_FRAME, 3), "quietest"


def plan_parts(duration: float, part_seconds: float, *, smart: bool = True, max_extra: float = 20.0,
               levels: np.ndarray | None = None, min_tail: float = MIN_TAIL_SEC) -> list[dict[str, Any]]:
    """[{n, start, end, cut}] covering the whole video; cut = how the part ends ("exact", "pause", "breath",
    "quietest", "end")."""
    duration, part_seconds = float(duration), max(5.0, float(part_seconds))
    speech_db = speech_level(levels) if levels is not None else 0.0
    parts: list[dict[str, Any]] = []
    start = 0.0
    while start + part_seconds < duration - 0.05:
        target = start + part_seconds
        if smart and levels is not None:
            cut, how = quiet_point(levels, target, min(target + max(0.0, float(max_extra)), duration), speech_db)
        else:
            cut, how = target, "exact"
        if duration - cut < min(min_tail, part_seconds / 4.0):   # a few seconds left: they join this part
            break
        parts.append({"n": len(parts) + 1, "start": round(start, 3), "end": round(cut, 3), "cut": how})
        start = cut
    parts.append({"n": len(parts) + 1, "start": round(start, 3), "end": round(duration, 3), "cut": "end"})
    return parts


def probe_duration(ffprobe: str, source: str | Path) -> float:
    p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=noprint_wrappers=1:nokey=1", str(source)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe could not read the video length: {p.stderr[-600:]}")


def _has_audio(ffprobe: str, source: str | Path) -> bool:
    p = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
                        "csv=p=0", str(source)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return bool(p.stdout.strip())


def encoder_args(encoder: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def render_text_png(text: str, output: Path, font_size: int, max_width: int, box: bool = True) -> Path:
    """Myanmar-safe text (Chromium shaping, white with a black outline like the Recap tab's text), cut to the
    text itself, on a dark rounded box when `box` is on."""
    from PIL import Image, ImageDraw
    from core import _render_extra_text_png

    raw = output.with_name(output.stem + ".raw.png")
    _render_extra_text_png(text, raw, font_size, 0.0, max_width=max_width)
    with Image.open(raw) as img:
        img = img.convert("RGBA")
        bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if bbox:
            img = img.crop(bbox)
        pad_x, pad_y = max(8, int(font_size * 0.45)), max(5, int(font_size * 0.22))
        panel = Image.new("RGBA", (img.width + 2 * pad_x, img.height + 2 * pad_y), (0, 0, 0, 0))
        if box:
            ImageDraw.Draw(panel).rounded_rectangle((0, 0, panel.width - 1, panel.height - 1),
                                                    radius=max(6, int(font_size * 0.35)), fill=(0, 0, 0, 120))
        panel.alpha_composite(img, (pad_x, pad_y))
        panel.save(output)
    raw.unlink(missing_ok=True)
    return output


def render_part(ffmpeg: str, source: str | Path, start: float, end: float, output: Path, *,
                layout: dict[str, Any], overlays: list[dict[str, Any]], encoder: str, has_audio: bool,
                on_time: Callable[[float], None] | None = None, stop: threading.Event | None = None,
                procs: list | None = None) -> None:
    """One part: exact start/end, frame layout, PNG overlays at their 0..1 centre positions, AAC sound."""
    vf, _zoom = _visual_filters(False, 1.0, layout)
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
           "-t", f"{max(0.05, end - start):.3f}", "-i", str(source)]       # -t before -i: limits this input
    graph = [f"[0:v]{vf}[base]"]
    current = "[base]"
    for i, item in enumerate(overlays, start=1):
        cmd += ["-i", str(item["png"])]
        opacity = max(0.1, min(1.0, float(item.get("opacity", 1.0))))
        alpha = f",colorchannelmixer=aa={opacity:.3f}" if opacity < 0.999 else ""
        graph.append(f"[{i}:v]format=rgba{alpha}[ov{i}]")
        x, y = float(item["pos"][0]), float(item["pos"][1])
        graph.append(f"{current}[ov{i}]overlay=x='W*{x:.6f}-w/2':y='H*{y:.6f}-h/2':eof_action=repeat[v{i}]")
        current = f"[v{i}]"
    graph.append(f"{current}format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]"]
    sound = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.stem + ".partial" + output.suffix)

    def run(codec: list[str]) -> tuple[int, str]:
        full = cmd + sound + codec + ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(temp)]
        proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace")
        if procs is not None:
            procs.append(proc)
        err: list[str] = []
        reader = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
        reader.start()
        for line in proc.stdout:
            if stop is not None and stop.is_set():
                proc.kill()
                break
            if line.startswith("out_time_ms=") and on_time is not None:
                try:
                    on_time(int(line.split("=", 1)[1]) / 1_000_000.0)
                except ValueError:
                    pass
        code = proc.wait()
        reader.join(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
        if procs is not None and proc in procs:
            procs.remove(proc)
        return code, "".join(err)

    code, err = run(encoder_args(encoder))
    if code != 0 and encoder != "libx264" and not (stop is not None and stop.is_set()):
        code, err = run(encoder_args("libx264"))       # NVENC busy / missing on this PC: CPU encoder
    if stop is not None and stop.is_set():
        temp.unlink(missing_ok=True)
        raise InterruptedError("Stopped")
    if code != 0 or not temp.is_file() or temp.stat().st_size < 2000:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg could not make {output.name}: {err[-1500:]}")
    temp.replace(output)


def parts_folder(source: Path, output_root: str | Path | None) -> Path:
    base = Path(output_root) if output_root and str(output_root).strip() else source.parent
    return base / f"{source.stem}_parts"


def _fingerprint(source: Path, part: dict[str, Any], settings: dict[str, Any], label: str) -> str:
    stat = source.stat()
    data = {"src": str(source.resolve()), "size": stat.st_size, "mtime": int(stat.st_mtime),
            "start": part["start"], "end": part["end"], "label": label,
            **{k: settings.get(k) for k in ("ratio", "fill", "text", "text_size", "text_pos", "text_opacity",
                                            "text_box", "label_on", "label_size", "label_pos", "label_opacity",
                                            "label_box")}}
    return hashlib.sha1(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def split_video(source: str | Path, settings: dict[str, Any], *, ffmpeg: str, ffprobe: str, log: LogFn,
                progress: Callable[[float, str], None] | None = None, stop: threading.Event | None = None,
                procs: list | None = None,
                on_plan: Callable[[list[dict[str, Any]]], None] | None = None) -> list[Path]:
    """Cut one video into parts with the given settings; returns the part files.

    settings: minutes, smart_cut, max_extra, ratio, fill, text, text_size, text_pos, text_opacity, text_box,
    label_on, label_template, label_size, label_pos, label_opacity, label_box, output_root.
    Parts already made with the same settings are kept (a stopped run goes on where it stopped).
    """
    source = Path(source).resolve()
    duration = probe_duration(ffprobe, source)
    sw, sh = probe_video_size(ffprobe, source)
    has_audio = _has_audio(ffprobe, source)
    smart = bool(settings.get("smart_cut", True))
    levels = None
    if smart and has_audio:
        log("🔊 Reading the sound to find the pauses…")
        levels = audio_levels(ffmpeg, source)
    elif smart:
        log("ℹ️ No sound in this video — exact cuts")
    parts = plan_parts(duration, float(settings.get("minutes", 3)) * 60.0, smart=smart,
                       max_extra=float(settings.get("max_extra", 20)), levels=levels)
    folder = parts_folder(source, settings.get("output_root"))
    folder.mkdir(parents=True, exist_ok=True)
    total = len(parts)
    log(f"✂️ {source.name}: {total} part(s) → {folder}")
    for p in parts:
        log(f"   Part {p['n']}: {_clock(p['start'])} → {_clock(p['end'])} ({p['end'] - p['start']:.1f} s, {p['cut']})")
    if on_plan is not None:
        on_plan(parts)

    ratio, fill = str(settings.get("ratio") or "Original"), str(settings.get("fill") or "blur")
    layout = frame_layout(ratio, fill, sw, sh, canvas=output_canvas(ratio, sw, sh))
    cw = int(layout["cw"])
    encoders = ffmpeg_encoders(ffmpeg)
    encoder = "h264_nvenc" if "h264_nvenc" in encoders else "libx264"
    log(f"🎬 Frame {ratio} ({layout['cw']}x{layout['ch']}){' · ' + fill if ratio != 'Original' else ''} · encoder {encoder}")

    work = folder / ".overlays"
    work.mkdir(exist_ok=True)
    fixed: list[dict[str, Any]] = []
    text = str(settings.get("text") or "").strip()
    if text:
        png = render_text_png(text, work / "text_box.png", int(settings.get("text_size", 42)), int(cw * 0.86),
                              bool(settings.get("text_box", True)))
        fixed.append({"png": png, "pos": settings.get("text_pos") or [0.5, 0.86],
                      "opacity": settings.get("text_opacity", 1.0)})

    state_file = folder / SPLIT_STATE
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    done: list[Path] = []
    finished = 0.0
    for p in parts:
        if stop is not None and stop.is_set():
            raise InterruptedError("Stopped")
        out = folder / f"{source.stem}_part_{p['n']:02d}.mp4"
        label = part_label(str(settings.get("label_template") or "Part {n}"), p["n"], total) \
            if settings.get("label_on") else ""
        key = _fingerprint(source, p, settings, label)
        length = p["end"] - p["start"]
        if out.is_file() and state.get(out.name) == key:
            log(f"♻️ Part {p['n']}/{total} already made — kept")
            done.append(out)
            finished += length
            continue
        overlays = list(fixed)
        if label:
            png = render_text_png(label, work / f"label_{p['n']:02d}.png", int(settings.get("label_size", 48)),
                                  int(cw * 0.6), bool(settings.get("label_box", True)))
            overlays.append({"png": png, "pos": settings.get("label_pos") or [0.5, 0.1],
                             "opacity": settings.get("label_opacity", 1.0)})
        log(f"🎞️ Part {p['n']}/{total} …")

        def on_time(sec: float, base=finished, n=p["n"]) -> None:
            if progress is not None:
                progress(min(1.0, (base + min(sec, length)) / max(0.1, duration)), f"Part {n}/{total}")

        render_part(ffmpeg, source, p["start"], p["end"], out, layout=layout, overlays=overlays, encoder=encoder,
                    has_audio=has_audio, on_time=on_time, stop=stop, procs=procs)
        state[out.name] = key
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        done.append(out)
        finished += length
        log(f"✅ {out.name}")
    # parts this tool made earlier for a different plan (e.g. 3-min parts before 5-min ones) are removed
    keep = {x.name for x in done}
    for name in [n for n in state if n not in keep]:
        (folder / name).unlink(missing_ok=True)
        state.pop(name, None)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress is not None:
        progress(1.0, "Done")
    return done


def _clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    frac = int(round((seconds - int(seconds)) * 10)) % 10
    return f"{h}:{m:02d}:{s:02d}.{frac}" if h else f"{m:02d}:{s:02d}.{frac}"
