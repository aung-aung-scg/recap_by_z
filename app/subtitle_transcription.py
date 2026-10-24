from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

from subtitle_io import SubtitleCue


ProgressFn = Callable[[int, int, str], None]
LogFn = Callable[[str], None]


class _SafeTextStream:
    def __init__(self, stream) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        try:
            return self._stream.write(text)
        except Exception:
            try:
                encoding = getattr(self._stream, "encoding", None) or "utf-8"
                safe_text = str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")
                return self._stream.write(safe_text)
            except Exception:
                return len(text)

    def flush(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _configure_worker_streams() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            setattr(sys, name, _SafeTextStream(stream))


def _worker_log(message: str) -> None:
    try:
        print(message, flush=True)
    except Exception:
        pass


def _worker_result_path(audio_path: Path) -> Path:
    return audio_path.with_suffix(".transcript.json")


def transcribed_cues(segments: list[dict]) -> list[SubtitleCue]:
    cues = []
    for index, segment in enumerate(segments, 1):
        if not isinstance(segment, dict):
            raise ValueError(f"Whisper segment {index} is invalid")
        text = str(segment.get("text") or "").strip()
        if not text:
            raise ValueError(f"Whisper segment {index} has no text")
        try:
            start_ms = round(float(segment["start"]) * 1000)
            end_ms = round(float(segment["end"]) * 1000)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Whisper segment {index} has invalid timestamps") from exc
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError(f"Whisper segment {index} has an invalid time range")
        cues.append(SubtitleCue(index, start_ms, end_ms, text))
    if not cues:
        raise ValueError("Whisper did not return any speech segments")
    return cues


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _extract_audio(ffmpeg: str, video: Path, audio: Path, stop_event: threading.Event) -> None:
    command = [
        ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(audio),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace")
    try:
        while True:
            if stop_event.is_set():
                _stop_process(process)
                raise InterruptedError("Speech transcription cancelled during audio extraction")
            try:
                _stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError(f"Could not extract video audio:\n{stderr[-3000:]}")
    finally:
        if process.poll() is None:
            _stop_process(process)


def _run_whisper_worker(
    audio: Path,
    stop_event: threading.Event,
    progress: ProgressFn | None,
    log: LogFn | None,
) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), "--whisper-worker", str(audio)]
    worker_env = os.environ.copy()
    worker_env["PYTHONUTF8"] = "1"
    worker_env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", bufsize=1, env=worker_env,
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    result = None
    result_path = _worker_result_path(audio)
    output_ended = False
    if progress:
        try:
            progress(5, 100, "Whisper is transcribing speech")
        except Exception:
            pass
    try:
        while not output_ended or process.poll() is None:
            if stop_event.is_set():
                _stop_process(process)
                raise InterruptedError("Speech transcription cancelled")
            try:
                line = lines.get(timeout=0.15)
            except queue.Empty:
                continue
            if line is None:
                output_ended = True
            elif line and log:
                try:
                    log(line)
                except Exception:
                    pass
        reader.join(timeout=1)
        if process.returncode:
            raise RuntimeError("Whisper transcription failed; see log for details.")
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Could not read Whisper transcript result: {exc}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("Whisper did not return a transcript.")
        return result
    finally:
        if process.poll() is None:
            _stop_process(process)


def transcribe_video(
    ffmpeg: str,
    video_path: Path,
    *,
    stop_event: threading.Event,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> tuple[list[SubtitleCue], str]:
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")
    with tempfile.TemporaryDirectory(prefix="subtitle-whisper-") as directory:
        audio = Path(directory) / "whisper_audio_16k.wav"
        if progress:
            try:
                progress(0, 100, "Extracting temporary audio for Whisper")
            except Exception:
                pass
        _extract_audio(ffmpeg, video_path, audio, stop_event)
        if stop_event.is_set():
            raise InterruptedError("Speech transcription cancelled")
        result = _run_whisper_worker(audio, stop_event, progress, log)
    if stop_event.is_set():
        raise InterruptedError("Speech transcription cancelled")
    cues = transcribed_cues(result.get("segments") or [])
    if progress:
        try:
            progress(100, 100, "Speech transcription complete")
        except Exception:
            pass
    return cues, str(result.get("language") or "unknown")


def _whisper_worker(audio_path: Path) -> None:
    service_path = Path(__file__).resolve().parents[1] / "recap_runtime" / "services" / "whisper_service.py"
    if not service_path.is_file():
        raise FileNotFoundError(f"Recap Whisper service not found: {service_path}")
    spec = importlib.util.spec_from_file_location("subtitle_whisper_service", service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Recap Whisper service: {service_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    whisper = module.WhisperTimestampService(
        model_size="medium",
        backend="auto",
        device="cuda",
        compute_type="float16",
        language=None,
    )
    result = whisper.transcribe(str(audio_path))
    result_path = _worker_result_path(audio_path)
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    _worker_log("Whisper transcript ready")


if __name__ == "__main__" and len(sys.argv) == 2 and sys.argv[1] == "--logging-self-test":
    _configure_worker_streams()
    _worker_log("⬇ Myanmar logging check: မြန်မာစာ")
    raise SystemExit(0)

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--whisper-worker":
    _configure_worker_streams()
    try:
        _whisper_worker(Path(sys.argv[2]))
    except Exception as exc:
        _worker_log(f"Whisper worker failed: {exc}")
        raise SystemExit(1) from exc
