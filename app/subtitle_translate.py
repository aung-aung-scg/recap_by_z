from __future__ import annotations

import json
import re
import socket
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable, Sequence

from subtitle_io import SubtitleCue, TranslatedCue


ProgressFn = Callable[[int, int, str], None]
DEFAULT_MODEL = "gemini-3.5-flash"
BATCH_SIZE = 30
BATCH_CHAR_LIMIT = 12_000
BATCH_ATTEMPTS = 3


class SubtitleBatchError(RuntimeError):
    def __init__(self, message: str, translated: Sequence[TranslatedCue]):
        super().__init__(message)
        self.translated = tuple(translated)


def load_gemini_api_key(env_path: Path) -> str:
    if not env_path.is_file():
        raise FileNotFoundError(f"Gemini .env file not found: {env_path}")
    from dotenv import dotenv_values

    values = dotenv_values(env_path)
    key = str(values.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    project_keys = sorted(
        (
            (int(match.group(1)), str(value or "").strip())
            for name, value in values.items()
            if (match := re.fullmatch(r"GEMINI_IMAGE_PROJECT_(\d+)_KEY", str(name or "")))
            and str(value or "").strip()
        ),
        key=lambda item: item[0],
    )
    if project_keys:
        return project_keys[0][1]
    raise ValueError(f"No GEMINI_API_KEY or GEMINI_IMAGE_PROJECT_N_KEY found in {env_path}")


def _gemini_proxy(env_path: Path) -> str:
    from dotenv import dotenv_values

    configured = str(dotenv_values(env_path).get("GEMINI_PROXY") or "").strip()
    if configured:
        return "" if configured.lower() in {"none", "off", "direct", "0"} else configured
    try:
        with socket.create_connection(("127.0.0.1", 10808), timeout=0.2):
            return "http://127.0.0.1:10808"
    except OSError:
        return ""


def create_gemini_client(api_key: str, env_path: Path):
    from google import genai
    from google.genai import types

    proxy = _gemini_proxy(env_path)
    client_args = {"proxy": proxy} if proxy else None
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=45_000, client_args=client_args),
    )


def _batches(cues: Sequence[SubtitleCue]) -> list[list[SubtitleCue]]:
    batches: list[list[SubtitleCue]] = []
    current: list[SubtitleCue] = []
    chars = 0
    for cue in cues:
        cue_chars = len(cue.text)
        if current and (len(current) >= BATCH_SIZE or chars + cue_chars > BATCH_CHAR_LIMIT):
            batches.append(current)
            current = []
            chars = 0
        current.append(cue)
        chars += cue_chars
    if current:
        batches.append(current)
    return batches


def _prompt(cues: Sequence[SubtitleCue]) -> str:
    items = [{"id": cue.index, "text": cue.text} for cue in cues]
    ids = [cue.index for cue in cues]
    return (
        "Translate the subtitle cues into natural, concise Burmese (Myanmar language) suitable for on-screen "
        "subtitles. Preserve each cue's complete meaning and tone. Write Burmese in Unicode Myanmar script. "
        "Do not add narration, explanations, markdown, or timestamps. Keep each cue separate: do not merge, "
        "split, drop, reorder, or add cues. Return JSON only in the form "
        '{"items":[{"id":1,"translation":"..."}]}. Return the exact cue IDs once each, in this order: '
        f"{json.dumps(ids)}.\n\nCues:\n{json.dumps(items, ensure_ascii=False)}"
    )


def _parse_response(response_text: str, batch: Sequence[SubtitleCue]) -> list[TranslatedCue]:
    value = str(response_text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        value = fenced.group(1)
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON: {exc}") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError('Gemini response must contain an "items" list')
    expected_ids = [cue.index for cue in batch]
    actual_ids = []
    translations: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise ValueError("Every translated cue must contain an integer id")
        actual_ids.append(item["id"])
        translation = item.get("translation")
        if not isinstance(translation, str) or not translation.strip():
            raise ValueError(f"Translation for cue {item['id']} is empty or invalid")
        cleaned = unicodedata.normalize("NFC", translation.strip())
        if not any("\u1000" <= char <= "\u109f" or "\ua9e0" <= char <= "\ua9ff" for char in cleaned):
            raise ValueError(f"Translation for cue {item['id']} contains no Myanmar Unicode text")
        translations.append(cleaned)
    if actual_ids != expected_ids:
        raise ValueError(
            f"Cue ID sequence mismatch: expected {expected_ids[0]}–{expected_ids[-1]}, got {actual_ids}"
        )
    return [
        TranslatedCue(source=cue, translation=translation)
        for cue, translation in zip(batch, translations)
    ]


def translate_subtitle_cues(
    cues: Sequence[SubtitleCue],
    *,
    client,
    model: str = DEFAULT_MODEL,
    stop_event: threading.Event | None = None,
    progress: ProgressFn | None = None,
    log: Callable[[str], None] | None = None,
) -> list[TranslatedCue]:
    if not cues:
        raise ValueError("There are no subtitle cues to translate")
    for expected_index, cue in enumerate(cues, 1):
        if cue.index != expected_index:
            raise ValueError("Source cue sequence is not consecutive")
        if cue.end_ms <= cue.start_ms or not cue.text.strip():
            raise ValueError(f"Source cue {expected_index} is invalid")

    batches = _batches(cues)
    translated: list[TranslatedCue] = []
    completed = 0
    for batch_index, batch in enumerate(batches, 1):
        result: list[TranslatedCue] | None = None
        last_error: Exception | None = None
        for attempt in range(1, BATCH_ATTEMPTS + 1):
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Subtitle translation cancelled")
            try:
                response = client.models.generate_content(model=model, contents=_prompt(batch))
                if stop_event is not None and stop_event.is_set():
                    raise InterruptedError("Subtitle translation cancelled")
                result = _parse_response(getattr(response, "text", ""), batch)
                break
            except InterruptedError:
                raise
            except Exception as exc:
                last_error = exc
                if log:
                    log(f"Batch {batch_index}/{len(batches)} attempt {attempt}/{BATCH_ATTEMPTS} failed: {exc}")
                if attempt < BATCH_ATTEMPTS:
                    time.sleep(float(attempt))
        if result is None:
            first, last = batch[0].index, batch[-1].index
            error = SubtitleBatchError(
                f"Could not translate subtitle cues {first}–{last} after {BATCH_ATTEMPTS} attempts: {last_error}",
                translated,
            )
            raise error from last_error
        translated.extend(result)
        completed += len(result)
        if progress:
            progress(completed, len(cues), f"Translated {completed}/{len(cues)} cues")

    if len(translated) != len(cues):
        raise RuntimeError(f"Cue count mismatch: source has {len(cues)}, translation has {len(translated)}")
    for source, output in zip(cues, translated):
        if (output.source.index, output.source.start_ms, output.source.end_ms) != (
            source.index, source.start_ms, source.end_ms
        ):
            raise RuntimeError(f"Source timestamps or sequence changed for cue {source.index}")
    return translated
