from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TranslatedCue:
    source: SubtitleCue
    translation: str


@dataclass(frozen=True)
class SubtitleTrack:
    stream_index: int
    codec: str
    language: str
    title: str

    @property
    def label(self) -> str:
        details = [f"Stream {self.stream_index}", self.codec]
        if self.language:
            details.append(self.language)
        if self.title:
            details.append(self.title)
        return " · ".join(details)


_TIMESTAMP_LINE = re.compile(
    r"^\s*(?P<start>(?:\d+:)?\d{2}:\d{2}[,.]\d{1,3})"
    r"\s*-->\s*(?P<end>(?:\d+:)?\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?$"
)


def _timestamp_ms(value: str) -> int:
    clock, fraction = re.split(r"[,.]", value, maxsplit=1)
    parts = [int(part) for part in clock.split(":")]
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        hours, minutes, seconds = parts
    if minutes > 59 or seconds > 59:
        raise ValueError(f"Invalid subtitle timestamp: {value}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(fraction.ljust(3, "0"))


def parse_subtitles(content: str, file_format: str) -> list[SubtitleCue]:
    """Parse SRT or WebVTT cues while keeping their millisecond timestamps intact."""
    normalized = str(content).lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    fmt = file_format.lower().lstrip(".")
    if fmt not in {"srt", "vtt", "webvtt"}:
        raise ValueError(f"Unsupported subtitle format: {file_format}")
    if fmt in {"vtt", "webvtt"}:
        lines = normalized.split("\n")
        if lines and lines[0].startswith("WEBVTT"):
            lines = lines[1:]
            while lines and (
                lines[0].startswith(("Kind:", "Language:", "X-TIMESTAMP-MAP="))
            ):
                lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
            normalized = "\n".join(lines)

    cues: list[SubtitleCue] = []
    for block in re.split(r"\n[ \t]*\n", normalized):
        if not block.strip():
            continue
        lines = block.splitlines()
        first = lines[0].strip()
        if fmt in {"vtt", "webvtt"} and first.startswith(("NOTE", "STYLE", "REGION")):
            continue
        timestamp_line = 0 if _TIMESTAMP_LINE.match(first) else 1
        if timestamp_line >= len(lines):
            raise ValueError(f"Malformed {fmt.upper()} cue block {len(cues) + 1}: missing timestamp")
        match = _TIMESTAMP_LINE.match(lines[timestamp_line])
        if not match:
            raise ValueError(f"Malformed {fmt.upper()} cue block {len(cues) + 1}: invalid timestamp")
        text = "\n".join(lines[timestamp_line + 1:]).strip()
        if not text:
            raise ValueError(f"Subtitle cue {len(cues) + 1} has no text")
        start_ms = _timestamp_ms(match.group("start"))
        end_ms = _timestamp_ms(match.group("end"))
        if end_ms <= start_ms:
            raise ValueError(f"Subtitle cue {len(cues) + 1} has invalid time range")
        cues.append(SubtitleCue(len(cues) + 1, start_ms, end_ms, text))
    if not cues:
        raise ValueError(f"No valid subtitle cues found in {fmt.upper()} input")
    return cues


def _format_timestamp(milliseconds: int) -> str:
    hours, remaining = divmod(milliseconds, 3_600_000)
    minutes, remaining = divmod(remaining, 60_000)
    seconds, fraction = divmod(remaining, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}"


def render_srt(cues: Sequence[TranslatedCue]) -> str:
    if not cues:
        raise ValueError("There are no translated cues to write")
    blocks: list[str] = []
    for expected_index, item in enumerate(cues, 1):
        source = item.source
        if source.index != expected_index:
            raise ValueError("Translated cue sequence does not match the source cue sequence")
        if not item.translation.strip():
            raise ValueError(f"Translated cue {expected_index} is empty")
        if source.end_ms <= source.start_ms:
            raise ValueError(f"Source cue {expected_index} has an invalid time range")
        blocks.append(
            f"{expected_index}\n"
            f"{_format_timestamp(source.start_ms)} --> {_format_timestamp(source.end_ms)}\n"
            f"{item.translation.strip()}"
        )
    return "\n\n".join(blocks) + "\n"


def _run_command(
    args: list[str],
    *,
    stop_event: threading.Event | None,
    timeout: float,
    operation: str,
) -> tuple[str, str]:
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + timeout
        while True:
            if stop_event is not None and stop_event.is_set():
                if proc.poll() is None:
                    proc.terminate()
                stdout, stderr = proc.communicate()
                raise InterruptedError(f"{operation} cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise RuntimeError(f"{operation} timed out after {timeout:g} seconds: {stderr[-2000:]}")
            try:
                stdout, stderr = proc.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"{operation} failed (exit {proc.returncode}): {stderr[-3000:]}")
    return stdout, stderr


def list_embedded_subtitle_tracks(
    ffprobe_path: str,
    video_path: Path,
    *,
    stop_event: threading.Event | None = None,
) -> list[SubtitleTrack]:
    stdout, _stderr = _run_command(
        [
            ffprobe_path, "-v", "error", "-select_streams", "s",
            "-show_entries", "stream=index,codec_name:stream_tags=language,title",
            "-of", "json", str(video_path),
        ],
        stop_event=stop_event,
        timeout=30,
        operation="Subtitle track scan",
    )
    try:
        streams = json.loads(stdout).get("streams") or []
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError(f"Could not read FFprobe subtitle-track output: {exc}") from exc
    tracks = []
    for stream in streams:
        if not isinstance(stream, dict) or "index" not in stream:
            continue
        tags = stream.get("tags") or {}
        tracks.append(SubtitleTrack(
            stream_index=int(stream["index"]),
            codec=str(stream.get("codec_name") or "unknown"),
            language=str(tags.get("language") or ""),
            title=str(tags.get("title") or ""),
        ))
    return tracks


def extract_embedded_subtitle_track(
    ffmpeg_path: str,
    video_path: Path,
    track: SubtitleTrack,
    *,
    stop_event: threading.Event | None = None,
) -> str:
    stdout, _stderr = _run_command(
        [
            ffmpeg_path, "-nostdin", "-v", "error", "-i", str(video_path),
            "-map", f"0:{track.stream_index}", "-c:s", "srt", "-f", "srt", "pipe:1",
        ],
        stop_event=stop_event,
        timeout=120,
        operation=f"Extract subtitle track {track.stream_index}",
    )
    if not stdout.strip():
        raise RuntimeError(f"Subtitle track {track.stream_index} contains no extractable cues")
    return stdout


def write_srt(path: Path, cues: Sequence[TranslatedCue], *, source_path: Path) -> None:
    destination = path.resolve()
    source = source_path.resolve()
    if destination == source:
        raise ValueError("Output path must not overwrite the source file")
    contents = render_srt(cues)
    created = False
    try:
        output = destination.open("x", encoding="utf-8", newline="\n")
        created = True
        with output:
            output.write(contents)
    except FileExistsError as exc:
        raise FileExistsError(f"Output already exists; choose another folder or filename: {destination}") from exc
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
