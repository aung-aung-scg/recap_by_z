"""Any source language → Myanmar (2026-10-17, user: "don't fix Whisper to English"). English keeps small.en and its
old jobs keep their transcript + translation; another language is heard by the multilingual model and named in the
translation prompt; Auto-detect asks Whisper first."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import recap_planner as rp  # noqa: E402


def _builder(language: str) -> rp.RecapPlanBuilder:
    return rp.RecapPlanBuilder(runtime_root=str(ROOT / "recap_runtime"), ffprobe_path="ffprobe", log=lambda _m: None,
                               progress=lambda *_a: None, should_stop=lambda: False, source_language=language)


class SourceLanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "video.mp4"
        self.src.write_bytes(b"x")

    def test_english_keeps_small_en_others_use_the_multilingual_model(self):
        self.assertEqual(rp.whisper_choice("en"), ("small.en", "en"))
        self.assertEqual(rp.whisper_choice("hi"), ("medium", "hi"))
        self.assertEqual(rp.whisper_choice("zh", "small"), ("small", "zh"))
        self.assertEqual(rp.source_language_name("ko"), "Korean")

    def test_a_chosen_language_is_used_without_detection(self):
        with mock.patch.object(rp.RecapPlanBuilder, "_detect_language") as detect:
            got = _builder("hi")._pick_whisper(self.src, self.tmp, self.tmp / "whisper_transcript.json", True)
        self.assertEqual(got, ("medium", "hi"))
        detect.assert_not_called()

    def test_auto_detect(self):
        with mock.patch.object(rp.RecapPlanBuilder, "_detect_language", return_value="zh") as detect:
            got = _builder("auto")._pick_whisper(self.src, self.tmp, self.tmp / "whisper_transcript.json", True)
        self.assertEqual(got, ("medium", "zh"))
        detect.assert_called_once()

    def test_an_old_english_job_keeps_its_transcript(self):
        transcript = self.tmp / "whisper_transcript.json"
        transcript.write_text(json.dumps({"model": "small.en", "language": "en", "segments": []}), encoding="utf-8")
        with mock.patch.object(rp.RecapPlanBuilder, "_detect_language") as detect:
            got = _builder("auto")._pick_whisper(self.src, self.tmp, transcript, True)
        self.assertEqual(got, ("small.en", "en"))       # same fingerprint as before: nothing is redone
        detect.assert_not_called()
        with mock.patch.object(rp.RecapPlanBuilder, "_detect_language"):
            self.assertEqual(_builder("hi")._pick_whisper(self.src, self.tmp, transcript, True), ("medium", "hi"))

    def test_the_translation_prompt_names_the_source_language(self):
        prompts = []

        def answer(_ai, prompt, **_kw):
            prompts.append(prompt)
            return {"items": [{"id": 1, "translation": "သူ အိမ်ပြန်လာခဲ့တယ်။"}]}

        unit = {"id": 1, "speech_start": 0.0, "speech_end": 2.0, "source_text": "वो घर आया।", "source_transcript_id": 0,
                "timestamp": f"{rp._fmt_ts(0.0)} --> {rp._fmt_ts(2.0)}"}
        with mock.patch.object(rp, "_gemini_json", answer):
            rp.translate_batch(None, story_context={}, previous_context=[], current=[unit], next_context=[],
                               log=lambda _m: None, source_language="Hindi")
        self.assertIn("Translate ONLY the CURRENT Hindi items", prompts[0])

    def test_a_burmese_video_is_not_narrated_again(self):
        b = _builder("auto")

        class Detector:
            def __init__(self, **_kw):
                pass

            def detect_language(self, _path):
                return "my", 0.97

        fake = type("M", (), {"WhisperTimestampService": Detector})
        with mock.patch.object(rp, "_load_module", return_value=fake), mock.patch.object(rp.subprocess, "run"), \
                self.assertRaisesRegex(RuntimeError, "already speaks Burmese"):
            b._detect_language(self.src, self.tmp)

    def test_long_lines_without_marks_end_at_whisper_segments_for_other_languages(self):
        words, t = [], 0.0
        for seg in range(13):     # ten 2 s sentences ending in "।", then three 6 s Whisper segments without marks
            n = 4 if seg < 10 else 12
            ws = [{"text": f"शब्द{seg}{i}" + ("।" if seg < 10 and i == n - 1 else ""), "start": t + i * 0.5,
                   "end": t + i * 0.5 + 0.45} for i in range(n)]
            words.append({"id": seg, "start": t, "end": t + n * 0.5, "text": " ".join(w["text"] for w in ws),
                          "words": ws})
            t += n * 0.5
        transcript = {"segments": words}
        hindi = rp.atomicize_timestamp_segments(transcript, sentence_locked=True, segment_breaks=True)
        english_rule = rp.atomicize_timestamp_segments(transcript, sentence_locked=True)
        self.assertLessEqual(max(u["speech_end"] - u["speech_start"] for u in hindi), 12.5)
        self.assertGreater(max(u["speech_end"] - u["speech_start"] for u in english_rule), 17.0)   # unchanged
        build = (APP / "recap_planner.py").read_text(encoding="utf-8")
        self.assertIn('segment_breaks=whisper_language != "en"', build)

    def test_the_ui_offers_auto_detect_and_the_languages(self):
        ui = (APP / "controller.py").read_text(encoding="utf-8")
        self.assertIn('LANGUAGE_LABELS = {"auto": "Auto-detect", **SOURCE_LANGUAGES}', ui)
        self.assertIn('"source_language": settings.get("source_language", "auto")', ui)
        self.assertIn('target = Path(folder) / f"{source.stem}_Myanmar.mp4"', ui)


if __name__ == "__main__":
    unittest.main()
