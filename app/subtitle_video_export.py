from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Sequence

from subtitle_editing import validate_cue_sequence
from subtitle_io import SubtitleCue, TranslatedCue


ProgressFn = Callable[[int, int, str], None]
LogFn = Callable[[str], None]


def video_output_path(source: Path, output_folder: str = "") -> Path:
    source = Path(source).resolve()
    folder = Path(output_folder).expanduser().resolve() if output_folder else source.parent
    if not folder.is_dir():
        raise ValueError(f"Output folder does not exist: {folder}")
    stem = f"{source.stem}_burmese_subs"
    candidate = folder / f"{stem}.mp4"
    suffix = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{suffix}.mp4"
        suffix += 1
    if candidate == source:
        raise ValueError("Subtitle export must not overwrite the source video")
    return candidate


def _probe_video(ffprobe: str, source: Path) -> tuple[int, int, float]:
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height:format=duration", "-of", "json", str(source),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise RuntimeError(f"Could not inspect source video:\n{result.stderr[-2000:]}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(payload["format"]["duration"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"FFprobe returned incomplete video information: {exc}") from exc
    if width < 1 or height < 1 or duration <= 0:
        raise ValueError("Source video has invalid dimensions or duration")
    return width, height, duration


def make_ffmpeg_export_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    cues: Sequence[TranslatedCue],
    image_paths: Sequence[Path],
    frame_size: tuple[int, int],
    vertical_position: int,
) -> list[str]:
    if len(cues) != len(image_paths):
        raise ValueError("Subtitle image count does not match translated cue count")
    width, height = frame_size
    if width < 1 or height < 1:
        raise ValueError("Video frame dimensions must be positive")
    if not 0 <= int(vertical_position) <= 100:
        raise ValueError("Subtitle vertical position must be between 0 and 100")
    command = [ffmpeg, "-nostdin", "-n", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    for path in image_paths:
        command.extend(["-i", str(path)])
    graph = []
    current = "[0:v:0]"
    for index, (cue, _image_path) in enumerate(zip(cues, image_paths), 1):
        start, end = cue.source.start_ms / 1000, cue.source.end_ms / 1000
        if end <= start:
            raise ValueError(f"Subtitle cue {cue.source.index} has an invalid time range")
        output_label = f"sub{index}"
        y_position = max(0, min(1, int(vertical_position) / 100))
        graph.append(
            f"{current}[{index}:v]overlay=x='(W-w)/2':"
            f"y='max(0,min(H-h,H*{y_position:.4f}-h/2))':"
            f"enable='between(t\\,{start:.3f}\\,{end:.3f})':eof_action=repeat[{output_label}]"
        )
        current = f"[{output_label}]"
    graph.append(f"{current}format=yuv420p[vout]")
    command.extend([
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-c:a", "copy", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", str(output),
    ])
    return command


def _load_renderer():
    renderer_path = Path(__file__).resolve().parents[1] / "services" / "text_overlay_service.py"
    if not renderer_path.is_file():
        raise FileNotFoundError(f"Myanmar text renderer not found: {renderer_path}")
    spec = importlib.util.spec_from_file_location("subtitle_text_overlay_service", renderer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Myanmar text renderer: {renderer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_video_subtitle_pngs


def _render_progress_output(
    process: subprocess.Popen,
    *,
    duration: float,
    stop_event: threading.Event,
    progress: ProgressFn | None,
    log: LogFn | None,
) -> None:
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    output_ended = False
    recent_errors: list[str] = []
    try:
        while not output_ended or process.poll() is None:
            if stop_event.is_set():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                raise InterruptedError("Video subtitle export cancelled")
            try:
                line = lines.get(timeout=0.15)
            except queue.Empty:
                continue
            if line is None:
                output_ended = True
            elif line.startswith("out_time="):
                timestamp = line.partition("=")[2]
                try:
                    hours, minutes, seconds = timestamp.split(":")
                    elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    if progress:
                        progress(min(99, round(elapsed * 100 / duration)), 100, "Rendering video subtitles")
                except ValueError:
                    pass
            elif line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    elapsed = int(line.partition("=")[2]) / 1_000_000
                    if progress:
                        progress(min(99, round(elapsed * 100 / duration)), 100, "Rendering video subtitles")
                except ValueError:
                    pass
            elif line.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=", "progress=")):
                continue
            elif line:
                recent_errors.append(line)
                del recent_errors[:-20]
                if log:
                    log(line)
        reader.join(timeout=1)
        if process.returncode:
            raise RuntimeError(
                "FFmpeg subtitle export failed:\n" + "\n".join(recent_errors[-15:])
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def export_burned_subtitles(
    ffmpeg: str,
    ffprobe: str,
    source: Path,
    source_cues: Sequence[SubtitleCue],
    cues: Sequence[TranslatedCue],
    output: Path,
    *,
    font_percent: int = 5,
    vertical_position: int = 86,
    stop_event: threading.Event,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
    render_pngs: Callable[[list[str], Path, dict], list[Path]] | None = None,
) -> Path:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise ValueError("Subtitle export must not overwrite the source video")
    if output.exists():
        raise FileExistsError(f"Output file already exists: {output}")
    if not source.is_file():
        raise FileNotFoundError(f"Source video not found: {source}")
    validate_cue_sequence(source_cues, cues)
    if not cues or any(not item.translation.strip() for item in cues):
        raise ValueError("Translate and save every subtitle segment before export")
    percent = int(font_percent)
    if not 3 <= percent <= 10:
        raise ValueError("Font size must be between 3% and 10% of the video short edge")
    width, height, duration = _probe_video(ffprobe, source)
    if stop_event.is_set():
        raise InterruptedError("Video subtitle export cancelled")
    renderer = render_pngs or _load_renderer()
    short_edge = min(width, height)
    font_size = max(12, round(short_edge * percent / 100))
    panel_width = max(240, round(width * 0.90))
    panel_height = max(96, round(font_size * 5.2))
    render_options = {
        "panel_width": panel_width,
        "video_title_panel_height": panel_height,
        "font_size": font_size,
        "min_title_font_size": max(12, round(font_size * 0.72)),
        "max_title_lines": 3,
        "panel_bg_alpha": 0.72,
        "panel_radius": max(8, round(short_edge * 0.018)),
        "title_horizontal_padding": max(12, round(panel_width * 0.035)),
        "title_vertical_padding": max(8, round(font_size * 0.24)),
        "stroke_px": max(1, round(font_size * 0.035)),
        "font_weight": 700,
    }
    with tempfile.TemporaryDirectory(prefix=".subtitle-video-", dir=output.parent) as directory:
        if progress:
            progress(1, 100, "Rendering Myanmar subtitle cards")
        translations = [item.translation for item in cues]
        if render_pngs is None:
            images = renderer(
                translations,
                Path(directory),
                render_options,
                stop_event=stop_event,
                progress=(
                    lambda done, total, label: progress(
                        1 + round(3 * done / max(total, 1)), 100, label,
                    )
                    if progress else None
                ),
            )
        else:
            images = renderer(translations, Path(directory), render_options)
        if stop_event.is_set():
            raise InterruptedError("Video subtitle export cancelled")
        rendered_video = Path(directory) / "rendered_output.mp4"
        command = make_ffmpeg_export_command(
            ffmpeg, source, rendered_video, cues, images, (width, height), vertical_position,
        )
        if progress:
            progress(5, 100, "Starting video render")
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        _render_progress_output(
            process, duration=duration, stop_event=stop_event, progress=progress, log=log,
        )
        if not rendered_video.is_file() or rendered_video.stat().st_size < 1000:
            raise RuntimeError("FFmpeg completed without producing a valid output video")
        if stop_event.is_set():
            raise InterruptedError("Video subtitle export cancelled")
        try:
            os.link(rendered_video, output)
        except FileExistsError as exc:
            raise FileExistsError(f"Output file already exists: {output}") from exc
        rendered_video.unlink()
    if progress:
        progress(100, 100, "Subtitle video export complete")
    return output
