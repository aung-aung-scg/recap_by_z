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


def resolve_output_folder(source: Path, output_folder: str = "") -> Path:
    source = Path(source).expanduser().resolve()
    folder = Path(output_folder).expanduser().resolve() if output_folder.strip() else source.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Could not create output folder {folder}: {exc}") from exc
    if not folder.is_dir():
        raise NotADirectoryError(f"Output folder is not a directory: {folder}")
    descriptor: int | None = None
    probe_path: str | None = None
    try:
        descriptor, probe_path = tempfile.mkstemp(prefix=".subtitle-write-test-", dir=folder)
        os.close(descriptor)
        descriptor = None
    except OSError as exc:
        raise PermissionError(f"Output folder is not writable: {folder}\n{exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if probe_path is not None:
            try:
                Path(probe_path).unlink()
            except OSError as exc:
                raise OSError(f"Could not clean up output-folder write test in {folder}: {exc}") from exc
    return folder


def video_output_path(source: Path, output_folder: str = "") -> Path:
    source = Path(source).resolve()
    folder = resolve_output_folder(source, output_folder)
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
    *,
    cover_original: bool = True,
    cover_style: str = "solid",
    background_opacity: int = 95,
    min_box_height_percent: int = 12,
    box_padding_percent: int = 2,
    blur_box: dict[str, float] | None = None,
    cover_height_pixels: int | None = None,
) -> list[str]:
    if len(cues) != len(image_paths):
        raise ValueError("Subtitle image count does not match translated cue count")
    width, height = frame_size
    if width < 1 or height < 1:
        raise ValueError("Video frame dimensions must be positive")
    if not 0 <= int(vertical_position) <= 100:
        raise ValueError("Subtitle vertical position must be between 0 and 100")
    validate_box_options(background_opacity, min_box_height_percent, box_padding_percent)
    style = _validate_cover_style(cover_style)
    command = [ffmpeg, "-nostdin", "-n", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    for path in image_paths:
        command.extend(["-i", str(path)])
    graph = []
    current = "[0:v:0]"
    if cover_original:
        current = _append_cover_filter(
            graph, current, style, width, height, vertical_position,
            min_box_height_percent, blur_box, cover_height_pixels,
        )
    overlay_height = cover_height_pixels or max(2, round(height * min_box_height_percent / 100))
    overlay_top = _centered_top(height, overlay_height, vertical_position)
    for index, (cue, _image_path) in enumerate(zip(cues, image_paths), 1):
        start, end = cue.source.start_ms / 1000, cue.source.end_ms / 1000
        if end <= start:
            raise ValueError(f"Subtitle cue {cue.source.index} has an invalid time range")
        output_label = f"sub{index}"
        graph.append(
            f"{current}[{index}:v]overlay=x='(W-w)/2':"
            f"y={overlay_top}:"
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


def _validate_cover_style(style: str) -> str:
    normalized = str(style).strip().casefold()
    if normalized not in {"solid", "blur", "delogo", "none"}:
        raise ValueError(f"Unsupported subtitle cover style: {style}")
    return normalized


def _centered_top(height: int, box_height: int, vertical_position: int) -> int:
    safe_margin = round(height * 0.05)
    effective_height = min(max(2, int(box_height)), max(2, height - 2 * safe_margin))
    target = round(height * int(vertical_position) / 100 - effective_height / 2)
    return max(safe_margin, min(height - effective_height - safe_margin, target))


def _append_cover_filter(
    graph: list[str],
    current: str,
    style: str,
    width: int,
    height: int,
    vertical_position: int,
    box_height_percent: int,
    blur_box: dict[str, float] | None,
    box_height_pixels: int | None = None,
) -> str:
    if style == "none":
        return current
    if style == "solid":
        box_height = max(
            2,
            min(
                height,
                int(box_height_pixels)
                if box_height_pixels is not None
                else round(height * int(box_height_percent) / 100),
            ),
        )
        top = _centered_top(height, box_height, vertical_position)
        graph.append(
            f"{current}drawbox=x=0:y={top}:w=iw:h={box_height}:color=black:t=fill[covered]"
        )
        return "[covered]"
    if blur_box is None:
        raise ValueError(f"Draw a cover area before using the {style} cover style")
    x, y, w, h = _blur_rectangle(blur_box, width, height)
    if style == "blur":
        radius = max(1, min(18, min(w, h) // 4))
        graph.extend([
            f"{current}split=2[coverbase][covercrop]",
            f"[covercrop]crop={w}:{h}:{x}:{y},"
            f"boxblur=luma_radius={radius}:luma_power=2:"
            f"chroma_radius={max(1, radius // 2)}:chroma_power=1[coveredblur]",
            f"[coverbase][coveredblur]overlay={x}:{y}[covered]",
        ])
        return "[covered]"
    graph.append(f"{current}delogo=x={x}:y={y}:w={w}:h={h}:show=0[covered]")
    return "[covered]"


def validate_box_options(
    background_opacity: int,
    min_box_height_percent: int,
    box_padding_percent: int,
) -> tuple[int, int, int]:
    opacity = int(background_opacity)
    min_height = int(min_box_height_percent)
    padding = int(box_padding_percent)
    if not 90 <= opacity <= 100:
        raise ValueError("Background opacity must be between 90 and 100 percent")
    if not 5 <= min_height <= 35:
        raise ValueError("Minimum subtitle box height must be between 5 and 35 percent")
    if not 0 <= padding <= 10:
        raise ValueError("Subtitle box padding must be between 0 and 10 percent")
    return opacity, min_height, padding


def _blur_rectangle(box: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    x_frac = max(0.0, min(1.0, float(box.get("x", 0.0))))
    y_frac = max(0.0, min(1.0, float(box.get("y", 0.0))))
    w_frac = max(0.0, min(1.0 - x_frac, float(box.get("w", 0.0))))
    h_frac = max(0.0, min(1.0 - y_frac, float(box.get("h", 0.0))))
    x = min(width - 2, max(0, round(x_frac * width) // 2 * 2))
    y = min(height - 2, max(0, round(y_frac * height) // 2 * 2))
    w = max(2, min(width - x, round(w_frac * width)) // 2 * 2)
    h = max(2, min(height - y, round(h_frac * height)) // 2 * 2)
    return x, y, w, h


def render_subtitle_preview(
    ffmpeg: str,
    ffprobe: str,
    source: Path,
    cue: TranslatedCue | None,
    output: Path,
    *,
    font_percent: int = 5,
    vertical_position: int = 86,
    cover_original: bool = True,
    cover_style: str = "solid",
    background_opacity: int = 95,
    min_box_height_percent: int = 12,
    box_padding_percent: int = 2,
    blur_box: dict[str, float] | None = None,
    timestamp_ms: int | None = None,
) -> Path:
    source, output = Path(source).resolve(), Path(output).resolve()
    _opacity, min_height, padding = validate_box_options(
        background_opacity, min_box_height_percent, box_padding_percent,
    )
    if not 3 <= int(font_percent) <= 10 or not 0 <= int(vertical_position) <= 100:
        raise ValueError("Preview font size or vertical position is out of range")
    width, height, _duration = _probe_video(ffprobe, source)
    scale = min(640 / width, 640 / height, 1.0)
    preview_width = max(2, round(width * scale) // 2 * 2)
    preview_height = max(2, round(height * scale) // 2 * 2)
    style = _validate_cover_style(cover_style)
    timestamp = max(
        0,
        timestamp_ms / 1000 if timestamp_ms is not None
        else (cue.source.start_ms + cue.source.end_ms) / 2000 if cue is not None else 0,
    )
    frame = output.parent / "preview_frame.png"
    overlay_image = output.parent / "preview_subtitle.png"
    extraction = subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{timestamp:.3f}", "-i", str(source), "-frames:v", "1",
            "-vf", f"scale={preview_width}:{preview_height}", str(frame),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if extraction.returncode or not frame.is_file():
        raise RuntimeError(f"Could not extract preview frame:\n{extraction.stderr[-2000:]}")

    short_edge = min(preview_width, preview_height)
    font_size = max(12, round(short_edge * int(font_percent) / 100))
    panel_width = min(preview_width, max(2, round(preview_width * 0.90)))
    panel_height = min(
        max(2, round(preview_height * 0.90)),
        max(96, round(preview_height * min_height / 100), round(font_size * 5.2)),
    )
    render_options = {
        "panel_width": panel_width,
        "video_title_panel_height": panel_height,
        "font_size": font_size,
        "min_title_font_size": max(12, round(font_size * 0.72)),
        "max_title_lines": 3,
        "panel_bg_alpha": 0,
        "panel_radius": max(8, round(short_edge * 0.018)),
        "title_horizontal_padding": max(12, round(panel_width * 0.035)),
        "title_vertical_padding": max(0, round(preview_height * padding / 100)),
        "stroke_px": max(1, round(font_size * 0.035)),
        "font_weight": 700,
    }
    if cue is not None and cue.translation.strip():
        renderer = _load_renderer()
        renderer([cue.translation], output.parent, render_options)
        (output.parent / "subtitle_000001.png").replace(overlay_image)
    graph: list[str] = []
    current = "[0:v:0]"
    if cover_original:
        current = _append_cover_filter(
            graph, current, style, preview_width, preview_height, vertical_position,
            min_height, blur_box, panel_height,
        )
    input_args = ["-i", str(frame)]
    if cue is not None and cue.translation.strip():
        input_args.extend(["-i", str(overlay_image)])
        graph.append(
            f"{current}[1:v:0]overlay=x='(W-w)/2':"
            f"y={_centered_top(preview_height, panel_height, vertical_position)}[preview]"
        )
        current = "[preview]"
    else:
        graph.append(f"{current}null[preview]")
    rendered = subprocess.run(
        [
            ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            *input_args,
            "-filter_complex", ";".join(graph), "-map", "[preview]",
            "-frames:v", "1", "-update", "1", str(output),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if rendered.returncode or not output.is_file():
        raise RuntimeError(f"Could not render subtitle preview:\n{rendered.stderr[-2000:]}")
    return output


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
    cover_original: bool = True,
    cover_style: str = "solid",
    background_opacity: int = 95,
    min_box_height_percent: int = 12,
    box_padding_percent: int = 2,
    blur_box: dict[str, float] | None = None,
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
    _opacity, min_box_height, padding = validate_box_options(
        background_opacity, min_box_height_percent, box_padding_percent,
    )
    style = _validate_cover_style(cover_style)
    if cover_original and style in {"blur", "delogo"} and blur_box is None:
        raise ValueError(f"Draw a cover area before using the {style} cover style")
    width, height, duration = _probe_video(ffprobe, source)
    if stop_event.is_set():
        raise InterruptedError("Video subtitle export cancelled")
    renderer = render_pngs or _load_renderer()
    short_edge = min(width, height)
    font_size = max(12, round(short_edge * percent / 100))
    panel_width = min(width, max(2, round(width * 0.90)))
    panel_height = min(
        max(2, round(height * 0.90)),
        max(96, round(height * min_box_height / 100), round(font_size * 5.2)),
    )
    render_options = {
        "panel_width": panel_width,
        "video_title_panel_height": panel_height,
        "font_size": font_size,
        "min_title_font_size": max(12, round(font_size * 0.72)),
        "max_title_lines": 3,
        "panel_bg_alpha": 0,
        "panel_radius": max(8, round(short_edge * 0.018)),
        "title_horizontal_padding": max(12, round(panel_width * 0.035)),
        "title_vertical_padding": max(0, round(height * padding / 100)),
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
            cover_original=cover_original,
            cover_style=style,
            background_opacity=_opacity,
            min_box_height_percent=min_box_height,
            box_padding_percent=padding,
            blur_box=blur_box if blur_box else None,
            cover_height_pixels=panel_height,
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
