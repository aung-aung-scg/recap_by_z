from __future__ import annotations

import os
import shutil
import subprocess
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

# The Whisper model download goes through plain HTTP into the Hugging Face cache, so its size
# can be shown while it downloads (the newer "xet" transfer gave no visible progress; same speed).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


class NoUsableSpeechError(RuntimeError):
    """Source downloaded correctly, but Recap cannot obtain usable speech."""


class WhisperTimestampService:
    """
    Local Whisper timestamp engine.

    Preferred backend: faster-whisper (fast, low VRAM, accurate segment/word timestamps)
    Fallback backend: openai-whisper

    Gemini never invents timestamps in V4. This service is the local timing source of truth.
    """

    def __init__(
        self,
        model_size: Optional[str] = None,
        backend: str = "auto",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        self.model_size = model_size or os.getenv("WHISPER_MODEL", "medium")
        self.backend = (backend or os.getenv("WHISPER_BACKEND", "auto")).lower()
        self.device = device or os.getenv("WHISPER_DEVICE", "cuda")
        self.compute_type = compute_type or os.getenv("WHISPER_COMPUTE_TYPE", "float16")
        self.language = language or os.getenv("WHISPER_LANGUAGE") or None
        self._model: Any = None
        self._active_backend: Optional[str] = None

    def _download_model_once(self) -> None:
        """First run on a PC: the model (~460 MB for small.en, ~1.5 GB for medium) comes from huggingface.co.

        faster-whisper downloads it with its progress bar switched off, so the log looked frozen
        after "You are sending unauthenticated requests to the HF Hub" (only a warning: no
        account or HF_TOKEN is needed). The downloaded size is printed every 5 seconds instead.
        """
        try:
            from faster_whisper.utils import _MODELS, download_model
        except Exception:
            return
        repo = _MODELS.get(str(self.model_size))
        if not repo:
            return  # a local folder or another repo id: faster-whisper handles it
        try:
            download_model(str(self.model_size), local_files_only=True)
            return  # already on this PC
        except Exception:
            pass
        import threading

        from huggingface_hub import constants

        folder = Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
        size = {"tiny": 75, "base": 145, "small": 465, "small.en": 465, "medium": 1530}.get(str(self.model_size))
        print(
            f"⬇️ First run only: downloading the Whisper model '{self.model_size}'"
            + (f" (~{size} MB)" if size else "") + " from huggingface.co. "
            "No account is needed — the HF_TOKEN warning can be ignored.",
            flush=True,
        )
        done = threading.Event()

        def report() -> None:
            while not done.wait(5.0):
                files = (folder / "blobs") if (folder / "blobs").is_dir() else folder
                size = sum(f.stat().st_size for f in files.rglob("*") if f.is_file()) if files.is_dir() else 0
                print(f"⬇️ Whisper model: {size / 1_000_000:.0f} MB downloaded...", flush=True)

        threading.Thread(target=report, daemon=True).start()
        try:
            for attempt in range(1, 4):  # a dropped connection is tried again; the download resumes
                try:
                    download_model(str(self.model_size))
                    break
                except Exception as exc:
                    if attempt == 3:
                        raise RuntimeError(
                            f"Could not download the Whisper model from huggingface.co "
                            f"({' '.join(str(exc).split())[:200]}). Check the internet. If huggingface.co does not "
                            "open on this PC, use a VPN, or put HF_ENDPOINT=https://hf-mirror.com in the .env file "
                            "and start again."
                        ) from exc
                    print(f"⚠️ Whisper model download interrupted ({' '.join(str(exc).split())[:120]}); "
                          f"trying again {attempt + 1}/3...", flush=True)
                    time.sleep(5 * attempt)
        finally:
            done.set()
        print("✅ Whisper model downloaded (kept on this PC for next time)", flush=True)

    def _load_faster_whisper(self) -> bool:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            return False

        self._download_model_once()
        try:
            print(
                f"🧠 Loading faster-whisper: model={self.model_size}, "
                f"device={self.device}, compute={self.compute_type}"
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            self._active_backend = "faster-whisper"
            return True
        except Exception as exc:
            print(f"⚠️ faster-whisper GPU load failed: {exc}")
            if self.device != "cpu":
                try:
                    print("↩️ faster-whisper CPU fallback (int8)")
                    self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                    self._active_backend = "faster-whisper"
                    self.device = "cpu"
                    self.compute_type = "int8"
                    return True
                except Exception as cpu_exc:
                    print(f"⚠️ faster-whisper CPU fallback failed: {cpu_exc}")
            return False

    def _load_openai_whisper(self) -> bool:
        try:
            import whisper
        except Exception:
            return False

        try:
            print(f"🧠 Loading openai-whisper: model={self.model_size}, device={self.device}")
            self._model = whisper.load_model(self.model_size, device=self.device)
            self._active_backend = "openai-whisper"
            return True
        except Exception as exc:
            print(f"⚠️ openai-whisper GPU load failed: {exc}")
            if self.device != "cpu":
                try:
                    self._model = whisper.load_model(self.model_size, device="cpu")
                    self._active_backend = "openai-whisper"
                    self.device = "cpu"
                    return True
                except Exception as cpu_exc:
                    print(f"⚠️ openai-whisper CPU fallback failed: {cpu_exc}")
            return False

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        backends = []
        if self.backend in {"auto", "faster", "faster-whisper"}:
            backends.append("faster")
        if self.backend in {"auto", "openai", "openai-whisper", "whisper"}:
            backends.append("openai")

        for backend in backends:
            if backend == "faster" and self._load_faster_whisper():
                return
            if backend == "openai" and self._load_openai_whisper():
                return

        raise RuntimeError(
            "Local Whisper backend မတွေ့ပါ။ faster-whisper သို့မဟုတ် openai-whisper "
            "install/config ကိုစစ်ပါ။"
        )

    def detect_language(self, media_path: str) -> tuple[str, float]:
        """Which language the speech in media_path is in: (Whisper code such as "en", "zh", "hi", probability).
        Needs a multilingual model (not a ".en" one); music and silence are skipped (VAD), up to 8 pieces of 30 s."""
        self._ensure_model()
        if self._active_backend != "faster-whisper":
            raise RuntimeError("Language detection needs faster-whisper")
        from faster_whisper import decode_audio

        audio = decode_audio(str(media_path), sampling_rate=16000)
        try:
            language, probability, _all = self._model.detect_language(
                audio=audio, vad_filter=True, language_detection_segments=8)
        except RuntimeError as exc:
            text = str(exc).lower()
            if self.device == "cpu" or not any(word in text for word in ("cublas", "cudnn", "cuda", ".dll")):
                raise
            print(f"⚠️ GPU Whisper failed ({exc}); using the CPU instead")
            self._model = None
            self.device, self.compute_type = "cpu", "int8"
            self._ensure_model()
            language, probability, _all = self._model.detect_language(
                audio=audio, vad_filter=True, language_detection_segments=8)
        return str(language), float(probability)

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join((text or "").strip().split())

    @staticmethod
    def _fmt_clock(seconds: float) -> str:
        seconds = max(0, int(seconds or 0))
        h, rem = divmod(seconds, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def _transcribe_faster(self, media_path: str, vad_filter: bool = True, media_duration: Optional[float] = None) -> dict[str, Any]:
        # FAST-SYNC profile: keep word timestamps, but avoid expensive beam search.
        # Language is supplied by the planner: English uses small.en/en, other languages the multilingual model.
        kwargs: dict[str, Any] = {
            "beam_size": 1,
            "best_of": 1,
            "vad_filter": bool(vad_filter),
            "word_timestamps": True,
            "condition_on_previous_text": False,
            "temperature": 0.0,
        }
        if self.language:
            kwargs["language"] = self.language
        if not str(self.model_size).endswith(".en"):
            # Other languages (2026-10-17): the multilingual medium model on a Hindi recap wrote "ॉॉॉॉ…" and
            # "पर पाइजावाद पर पाइजावाद …" over real speech (3 loops in 2 min). With beam search and Whisper's
            # temperature fallback (a piece that loops is decoded again) the loops were gone, 36% more speech came
            # back and the sentence marks (।) were written; English keeps the fast settings above.
            kwargs["beam_size"] = 5
            kwargs["temperature"] = (0.0, 0.2, 0.4, 0.6, 0.8)

        segments_iter, info = self._model.transcribe(media_path, **kwargs)
        segments: list[dict[str, Any]] = []
        words_total = 0
        avg_logprob_values: list[float] = []
        no_speech_values: list[float] = []
        compression_ratio_values: list[float] = []
        next_progress = 5
        total_duration = float(media_duration or 0.0)
        for idx, seg in enumerate(segments_iter):
            text = self._clean_text(getattr(seg, "text", ""))
            start = float(getattr(seg, "start", 0.0) or 0.0)
            end = float(getattr(seg, "end", 0.0) or 0.0)
            if total_duration > 0 and end > 0:
                pct = min(99, int((end / total_duration) * 100))
                if pct >= next_progress:
                    print(
                        f"⏳ Whisper {pct:02d}% | "
                        f"{self._fmt_clock(end)} / {self._fmt_clock(total_duration)}",
                        flush=True,
                    )
                    next_progress = ((pct // 5) + 1) * 5
            if not text or end <= start:
                continue
            words = []
            for word in getattr(seg, "words", None) or []:
                w_text = self._clean_text(getattr(word, "word", ""))
                w_start = float(getattr(word, "start", start) or start)
                w_end = float(getattr(word, "end", w_start) or w_start)
                if not w_text or w_end <= w_start:
                    continue
                words.append({
                    "start": round(w_start, 3),
                    "end": round(w_end, 3),
                    "text": w_text,
                })
            words_total += len(words)

            avg_logprob = getattr(seg, "avg_logprob", None)
            no_speech_prob = getattr(seg, "no_speech_prob", None)
            compression_ratio = getattr(seg, "compression_ratio", None)
            try:
                if avg_logprob is not None:
                    avg_logprob_values.append(float(avg_logprob))
            except Exception:
                pass
            try:
                if no_speech_prob is not None:
                    no_speech_values.append(float(no_speech_prob))
            except Exception:
                pass
            try:
                if compression_ratio is not None:
                    compression_ratio_values.append(float(compression_ratio))
            except Exception:
                pass

            segments.append({
                "id": len(segments),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "words": words,
            })

        return {
            "backend": "faster-whisper",
            "model": self.model_size,
            "language": getattr(info, "language", self.language or "") or "",
            "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
            "segments": segments,
            "word_count": words_total,
            "avg_logprob": (sum(avg_logprob_values) / len(avg_logprob_values)) if avg_logprob_values else None,
            "avg_no_speech_prob": (sum(no_speech_values) / len(no_speech_values)) if no_speech_values else None,
            "avg_compression_ratio": (sum(compression_ratio_values) / len(compression_ratio_values)) if compression_ratio_values else None,
        }

    def _transcribe_openai(self, media_path: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "verbose": False,
            "word_timestamps": True,
            "fp16": self.device != "cpu",
        }
        if self.language:
            kwargs["language"] = self.language
        result = self._model.transcribe(media_path, **kwargs)

        segments: list[dict[str, Any]] = []
        words_total = 0
        for raw in result.get("segments") or []:
            text = self._clean_text(raw.get("text", ""))
            start = float(raw.get("start", 0.0) or 0.0)
            end = float(raw.get("end", 0.0) or 0.0)
            if not text or end <= start:
                continue
            words = []
            for word in raw.get("words") or []:
                w_text = self._clean_text(word.get("word", ""))
                w_start = float(word.get("start", start) or start)
                w_end = float(word.get("end", w_start) or w_start)
                if not w_text or w_end <= w_start:
                    continue
                words.append({
                    "start": round(w_start, 3),
                    "end": round(w_end, 3),
                    "text": w_text,
                })
            words_total += len(words)
            segments.append({
                "id": len(segments),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "words": words,
            })

        return {
            "backend": "openai-whisper",
            "model": self.model_size,
            "language": result.get("language") or self.language or "",
            "language_probability": None,
            "segments": segments,
            "word_count": words_total,
        }

    @staticmethod
    def _probe_audio_stream(media_path: str) -> Optional[bool]:
        """Return True/False when ffprobe is available, otherwise None."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    media_path,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return bool((result.stdout or "").strip())


    @staticmethod
    def _assess_vad_fallback_quality(
        result: dict[str, Any], *, min_unique_ratio: Optional[float] = None
    ) -> dict[str, Any]:
        """Conservatively decide whether a VAD-OFF rescue looks like real speech."""
        segments = result.get("segments") or []
        transcript = " ".join(str(seg.get("text") or "") for seg in segments).strip()
        tokens = [
            token.strip(".,!?;:'\"()[]{}<>-_—–…").lower()
            for token in transcript.split()
        ]
        tokens = [token for token in tokens if token]
        meaningful = [token for token in tokens if any(ch.isalnum() for ch in token)]
        unique_ratio = (len(set(meaningful)) / len(meaningful)) if meaningful else 0.0

        spoken_seconds = 0.0
        for seg in segments:
            try:
                start = float(seg.get("start", 0.0) or 0.0)
                end = float(seg.get("end", 0.0) or 0.0)
                if end > start:
                    spoken_seconds += end - start
            except Exception:
                pass

        media_duration = float(result.get("media_duration") or 0.0)
        coverage = (spoken_seconds / media_duration) if media_duration > 0 else None
        language_probability = result.get("language_probability")
        try:
            language_probability = float(language_probability) if language_probability is not None else None
        except Exception:
            language_probability = None

        avg_logprob = result.get("avg_logprob")
        avg_no_speech_prob = result.get("avg_no_speech_prob")
        try:
            avg_logprob = float(avg_logprob) if avg_logprob is not None else None
        except Exception:
            avg_logprob = None
        try:
            avg_no_speech_prob = float(avg_no_speech_prob) if avg_no_speech_prob is not None else None
        except Exception:
            avg_no_speech_prob = None

        reasons: list[str] = []
        min_words = max(4, int(os.getenv("WHISPER_FALLBACK_MIN_WORDS", "10")))
        min_spoken_seconds = max(1.0, float(os.getenv("WHISPER_FALLBACK_MIN_SPEECH_SECONDS", "5.0")))
        if min_unique_ratio is None:
            min_unique_ratio = float(os.getenv("WHISPER_FALLBACK_MIN_UNIQUE_RATIO", "0.42"))
        min_unique_ratio = min(1.0, max(0.0, float(min_unique_ratio)))
        min_language_probability = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MIN_LANGUAGE_PROB", "0.35"))))
        min_coverage = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MIN_COVERAGE", "0.08"))))
        max_no_speech_prob = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MAX_NO_SPEECH_PROB", "0.65"))))
        min_avg_logprob = float(os.getenv("WHISPER_FALLBACK_MIN_AVG_LOGPROB", "-1.20"))

        if len(meaningful) < min_words:
            reasons.append(f"too_few_words={len(meaningful)}<{min_words}")
        if spoken_seconds < min_spoken_seconds:
            reasons.append(f"speech_seconds={spoken_seconds:.2f}<{min_spoken_seconds:.2f}")
        if len(meaningful) >= 6 and unique_ratio < min_unique_ratio:
            reasons.append(f"repetitive_unique_ratio={unique_ratio:.2f}<{min_unique_ratio:.2f}")
        if language_probability is not None and language_probability > 0 and language_probability < min_language_probability:
            reasons.append(f"language_probability={language_probability:.2f}<{min_language_probability:.2f}")
        if coverage is not None and media_duration >= 20.0 and coverage < min_coverage:
            reasons.append(f"speech_coverage={coverage:.2f}<{min_coverage:.2f}")
        if avg_no_speech_prob is not None and avg_no_speech_prob > max_no_speech_prob:
            reasons.append(f"avg_no_speech={avg_no_speech_prob:.2f}>{max_no_speech_prob:.2f}")
        if avg_logprob is not None and avg_logprob < min_avg_logprob:
            reasons.append(f"avg_logprob={avg_logprob:.2f}<{min_avg_logprob:.2f}")

        return {
            "usable": not reasons,
            "reasons": reasons,
            "word_count": len(meaningful),
            "spoken_seconds": round(spoken_seconds, 3),
            "speech_coverage": round(coverage, 4) if coverage is not None else None,
            "unique_ratio": round(unique_ratio, 4),
            "language_probability": language_probability,
            "avg_logprob": avg_logprob,
            "avg_no_speech_prob": avg_no_speech_prob,
        }

    @staticmethod
    def assess_transcript_completeness(
        result: dict[str, Any], media_duration: Optional[float] = None
    ) -> dict[str, Any]:
        """Flag long-source transcripts whose text and timestamp evidence are unusually sparse."""
        segments = [seg for seg in result.get("segments") or [] if isinstance(seg, dict)]
        duration = float(media_duration or result.get("media_duration") or 0.0)
        text = " ".join(str(seg.get("text") or "") for seg in segments)
        words = [word for word in text.split() if any(char.isalnum() for char in word)]
        text_characters = sum(char.isalnum() for char in text)
        spoken_seconds = 0.0
        missing_timestamps = 0
        for segment in segments:
            try:
                start = float(segment["start"])
                end = float(segment["end"])
                if end <= start:
                    missing_timestamps += 1
                    continue
                spoken_seconds += end - start
            except (KeyError, TypeError, ValueError):
                missing_timestamps += 1

        coverage = spoken_seconds / duration if duration > 0 else None
        min_duration = max(20.0, float(os.getenv("WHISPER_SPARSE_MIN_DURATION", "60")))
        max_words = max(1, int(os.getenv("WHISPER_SPARSE_MAX_WORDS", "8")))
        max_coverage = min(1.0, max(0.0, float(os.getenv("WHISPER_SPARSE_MAX_COVERAGE", "0.025"))))
        min_characters = max(16, max_words * 4)
        reasons: list[str] = []
        if (
            duration >= min_duration
            and len(words) < max_words
            and text_characters < min_characters
            and coverage is not None
            and coverage < max_coverage
        ):
            reasons.append(
                f"long_source_sparse_transcript={len(words)}_words/{spoken_seconds:.2f}s/"
                f"{text_characters}_characters/{coverage:.2%}_coverage"
            )
        if duration >= min_duration and segments and missing_timestamps:
            reasons.append(f"missing_or_invalid_timestamps={missing_timestamps}/{len(segments)}")

        return {
            "suspicious": bool(reasons),
            "reasons": reasons,
            "media_duration": round(duration, 3),
            "word_count": len(words),
            "text_characters": text_characters,
            "spoken_seconds": round(spoken_seconds, 3),
            "speech_coverage": round(coverage, 4) if coverage is not None else None,
            "missing_timestamps": missing_timestamps,
        }

    @staticmethod
    def _sparse_transcripts_agree(first: dict[str, Any], second: dict[str, Any]) -> bool:
        first_text = " ".join(str(seg.get("text") or "") for seg in first.get("segments") or [])
        second_text = " ".join(str(seg.get("text") or "") for seg in second.get("segments") or [])
        normalize = lambda value: " ".join(
            "".join(char.lower() if char.isalnum() else " " for char in value).split()
        )
        first_text, second_text = normalize(first_text), normalize(second_text)
        return bool(first_text and second_text and SequenceMatcher(None, first_text, second_text).ratio() >= 0.90)

    def transcribe(self, media_path: str, media_duration: Optional[float] = None) -> dict[str, Any]:
        path = Path(media_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Whisper input မတွေ့ပါ: {path}")

        audio_probe = self._probe_audio_stream(str(path))
        if audio_probe is False:
            raise NoUsableSpeechError("NO_USABLE_SPEECH: ffprobe found no audio stream in source media.")

        self._ensure_model()
        print(f"🎙️ Local Whisper timestamp transcription: {path.name}")

        if self._active_backend == "faster-whisper":
            try:
                result = self._transcribe_faster(str(path), vad_filter=True, media_duration=media_duration)
            except RuntimeError as exc:
                # An NVIDIA GPU without the CUDA 12 libraries (cublas64_12.dll / cuDNN) loads the
                # model but fails on the first audio: finish on the CPU instead of stopping.
                text = str(exc).lower()
                if self.device == "cpu" or not any(word in text for word in ("cublas", "cudnn", "cuda", ".dll")):
                    raise
                print(f"⚠️ GPU Whisper failed ({exc}); using the CPU instead (slower)")
                self._model = None
                self.device, self.compute_type = "cpu", "int8"
                self._ensure_model()
                result = self._transcribe_faster(str(path), vad_filter=True, media_duration=media_duration)
            if not result.get("segments"):
                print("⚠️ Whisper VAD=ON returned 0 segments — retrying SAME source once with VAD=OFF...")
                result = self._transcribe_faster(str(path), vad_filter=False, media_duration=media_duration)
                result["vad_fallback_used"] = True
        elif self._active_backend == "openai-whisper":
            result = self._transcribe_openai(str(path))
        else:
            raise RuntimeError("Whisper backend မရွေးရသေးပါ။")

        if not result.get("segments"):
            raise NoUsableSpeechError(
                "NO_USABLE_SPEECH: Whisper returned 0 usable transcript segments after fallback."
            )

        if media_duration is not None:
            result["media_duration"] = round(float(media_duration), 3)
        else:
            result["media_duration"] = round(float(result["segments"][-1]["end"]), 3)

        result["text"] = " ".join(seg["text"] for seg in result["segments"]).strip()

        sparse_assessment = self.assess_transcript_completeness(result, media_duration)
        result["transcript_validation"] = {
            "status": "complete",
            **sparse_assessment,
        }
        if sparse_assessment["suspicious"]:
            reasons = ", ".join(sparse_assessment["reasons"])
            print(
                "⚠️ Whisper transcript looks unusually sparse for the source; "
                f"retrying without VAD ({reasons})",
                flush=True,
            )
            if self._active_backend != "faster-whisper" or bool(result.get("vad_fallback_used")):
                raise NoUsableSpeechError(
                    "TRANSCRIPT_COMPLETENESS_UNCONFIRMED: Whisper returned a suspiciously sparse transcript "
                    f"({reasons}). Inspect whisper_transcript.txt and retry with the correct source language."
                )
            try:
                retry = self._transcribe_faster(
                    str(path), vad_filter=False, media_duration=media_duration
                )
            except Exception as exc:
                raise NoUsableSpeechError(
                    "TRANSCRIPT_COMPLETENESS_UNCONFIRMED: Whisper's VAD-off completeness retry failed. "
                    "Inspect whisper_transcript.txt, verify the source-language setting, and retry."
                ) from exc
            retry["media_duration"] = result["media_duration"]
            retry["text"] = " ".join(seg["text"] for seg in retry.get("segments") or []).strip()
            retry_assessment = self.assess_transcript_completeness(retry, media_duration)
            original_words = int(sparse_assessment["word_count"])
            retry_words = int(retry_assessment["word_count"])
            retry_speech = float(retry_assessment["spoken_seconds"])
            original_speech = float(sparse_assessment["spoken_seconds"])

            if retry.get("segments") and retry_words > original_words and retry_speech > original_speech + 0.5:
                retry_quality = self._assess_vad_fallback_quality(
                    retry,
                    min_unique_ratio=float(os.getenv("WHISPER_SPARSE_RETRY_MIN_UNIQUE_RATIO", "0.30")),
                )
                if not retry_quality["usable"]:
                    retry_reasons = ", ".join(retry_quality["reasons"])
                    raise NoUsableSpeechError(
                        "TRANSCRIPT_COMPLETENESS_UNCONFIRMED: VAD-off retry found additional speech but did "
                        f"not pass quality checks ({retry_reasons}). Inspect whisper_transcript.txt and retry."
                    )
                retry["transcript_validation"] = {
                    "status": "sparse_recovered",
                    **retry_assessment,
                    "retry_quality": retry_quality,
                }
                result = retry
                print(
                    "✅ Whisper sparse-transcript retry recovered additional speech — "
                    f"{retry_words} words, {retry_speech:.2f}s",
                    flush=True,
                )
            elif (
                retry.get("segments")
                and not retry_assessment["missing_timestamps"]
                and self._sparse_transcripts_agree(result, retry)
            ):
                retry["transcript_validation"] = {
                    "status": "sparse_corroborated",
                    **retry_assessment,
                }
                result = retry
                print(
                    "✅ VAD-on and VAD-off transcripts agree; preserving the sparse low-dialogue result",
                    flush=True,
                )
            else:
                raise NoUsableSpeechError(
                    "TRANSCRIPT_COMPLETENESS_UNCONFIRMED: VAD-off retry did not corroborate or reliably "
                    "recover the sparse transcript. Inspect whisper_transcript.txt and the source audio; "
                    "then retry with the correct source language."
                )

        if bool(result.get("vad_fallback_used")):
            quality = self._assess_vad_fallback_quality(result)
            result["vad_fallback_quality"] = quality
            if not bool(quality.get("usable")):
                reasons = ", ".join(quality.get("reasons") or ["low_confidence_fallback_transcript"])
                print(
                    "🎵 VAD-OFF rescue rejected as likely music/noise or too-thin speech → "
                    f"{reasons}"
                )
                raise NoUsableSpeechError(
                    "MUSIC_ONLY_OR_TRANSCRIPT_TOO_THIN: " + reasons
                )
            print(
                "✅ VAD-OFF rescue passed speech-quality guard → "
                f"words={quality.get('word_count')}, "
                f"speech={quality.get('spoken_seconds')}s, "
                f"unique={quality.get('unique_ratio')}"
            )

        print(
            f"✅ Whisper done: {len(result['segments'])} segments, "
            f"language={result.get('language') or 'auto'}"
        )
        return result
