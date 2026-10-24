from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SERVICE = ROOT / "recap_runtime" / "services"
for path in (str(APP), str(SERVICE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import core  # noqa: E402
import recap_planner  # noqa: E402
import whisper_service  # noqa: E402


def _segment(text: str, start: float, end: float) -> dict:
    return {"start": start, "end": end, "text": text, "words": []}


def _sparse_transcript() -> dict:
    return {
        "segments": [_segment("They're both coming back!", 47.5, 49.44)],
        "language": "en",
        "language_probability": 0.99,
        "avg_logprob": -0.45,
        "avg_no_speech_prob": 0.48,
        "avg_compression_ratio": 0.75,
    }


def _recovered_transcript() -> dict:
    return {
        "segments": [
            _segment("The little dragon flew across the valley", 10.0, 14.0),
            _segment("Then the family hurried toward the old bridge", 52.0, 56.0),
            _segment("They are both coming back home together", 100.0, 104.0),
        ],
        "language": "en",
        "language_probability": 0.99,
        "avg_logprob": -0.3,
        "avg_no_speech_prob": 0.1,
    }


class WhisperTranscriptCompletenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.media = Path(self.temp.name) / "audio.wav"
        self.media.write_bytes(b"test audio placeholder")
        self.service = whisper_service.WhisperTimestampService(
            backend="faster-whisper", device="cpu", language="en"
        )
        self.service._active_backend = "faster-whisper"

    def _run_transcription(self, result_for_vad):
        with mock.patch.object(self.service, "_probe_audio_stream", return_value=True), \
             mock.patch.object(self.service, "_ensure_model"), \
             mock.patch.object(self.service, "_transcribe_faster", side_effect=result_for_vad) as transcribe, \
             redirect_stdout(StringIO()):
            result = self.service.transcribe(str(self.media), media_duration=143.0)
        return result, transcribe

    def test_sparse_143_second_transcript_retries_and_recovers_more_speech(self):
        result, transcribe = self._run_transcription(
            lambda _path, *, vad_filter, media_duration: (
                _sparse_transcript() if vad_filter else _recovered_transcript()
            )
        )
        self.assertEqual(transcribe.call_count, 2)
        self.assertFalse(transcribe.call_args.kwargs["vad_filter"])
        self.assertEqual(result["transcript_validation"]["status"], "sparse_recovered")
        self.assertGreater(result["transcript_validation"]["word_count"], 8)

    def test_empty_whisper_output_after_fallback_is_rejected(self):
        with mock.patch.object(self.service, "_probe_audio_stream", return_value=True), \
             mock.patch.object(self.service, "_ensure_model"), \
             mock.patch.object(self.service, "_transcribe_faster", return_value={"segments": [], "language": "en"}) as transcribe, \
             redirect_stdout(StringIO()):
            with self.assertRaisesRegex(whisper_service.NoUsableSpeechError, "0 usable transcript segments"):
                self.service.transcribe(str(self.media), media_duration=143.0)
        self.assertEqual(transcribe.call_count, 2)

    def test_missing_segment_timestamps_trigger_retry_and_use_measured_fallback(self):
        missing = {
            "segments": [{"text": "They're both coming back!"}],
            "language": "en",
        }

        def respond(_path, *, vad_filter, media_duration):
            return missing if vad_filter else _sparse_transcript()

        result, transcribe = self._run_transcription(respond)
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(result["transcript_validation"]["status"], "sparse_corroborated")
        self.assertEqual(result["transcript_validation"]["missing_timestamps"], 0)

    def test_legitimate_sparse_low_dialogue_transcript_is_kept_when_retries_agree(self):
        result, transcribe = self._run_transcription(
            lambda _path, *, vad_filter, media_duration: _sparse_transcript()
        )
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(result["text"], "They're both coming back!")
        self.assertEqual(result["transcript_validation"]["status"], "sparse_corroborated")

    def test_normal_multisegment_transcript_does_not_retry(self):
        normal = _recovered_transcript()
        result, transcribe = self._run_transcription(
            lambda _path, *, vad_filter, media_duration: normal
        )
        self.assertEqual(transcribe.call_count, 1)
        self.assertEqual(result["transcript_validation"]["status"], "complete")

    def test_sparse_quality_assessment_uses_duration_text_and_timestamp_evidence(self):
        assessment = self.service.assess_transcript_completeness(_sparse_transcript(), 143.0)
        self.assertTrue(assessment["suspicious"])
        self.assertEqual(assessment["word_count"], 4)
        self.assertEqual(assessment["missing_timestamps"], 0)

        missing = {"segments": [{"text": "A longer transcript with missing timestamps"}]}
        missing_assessment = self.service.assess_transcript_completeness(missing, 143.0)
        self.assertTrue(missing_assessment["suspicious"])
        self.assertEqual(missing_assessment["missing_timestamps"], 1)

    def test_sparse_retry_can_tolerate_mild_repetition_without_relaxing_zero_segment_fallback(self):
        retry = {
            "segments": [
                _segment("dragon little family returns", 0.0, 4.0),
                _segment("dragon little family returns", 50.0, 54.0),
                _segment("dragon little family returns", 100.0, 104.0),
            ],
            "media_duration": 143.0,
            "language_probability": 0.99,
            "avg_logprob": -0.3,
            "avg_no_speech_prob": 0.1,
        }
        self.assertFalse(whisper_service.WhisperTimestampService._assess_vad_fallback_quality(retry)["usable"])
        self.assertTrue(
            whisper_service.WhisperTimestampService._assess_vad_fallback_quality(
                retry, min_unique_ratio=0.30
            )["usable"]
        )


class RecapDurationSafetyTests(unittest.TestCase):
    def test_plan_preserves_transcript_validation_for_the_render_guard(self):
        transcript = {
            "transcript_validation": {
                "status": "sparse_corroborated",
                "word_count": 4,
                "spoken_seconds": 1.94,
            }
        }
        plan = recap_planner.make_translation_plan(
            [{
                "id": 1,
                "source_transcript_id": 0,
                "source_transcript_ids": [0],
                "speech_start": 47.5,
                "speech_end": 49.44,
                "source_text": "They're both coming back!",
                "translation": "သူတို့နှစ်ယောက်စလုံး ပြန်လာနေကြပြီ!",
                "timestamp": "00:00:47.500 --> 00:00:49.440",
            }],
            143.0,
            source_title="incident",
            transcript=transcript,
            story_context={},
        )
        self.assertEqual(plan["transcript_validation"]["status"], "sparse_corroborated")
        self.assertEqual((plan["segments"][0]["video_start"], plan["segments"][0]["video_end"]), (0.0, 143.0))
        self.assertFalse(recap_planner._plan_has_unverified_sparse_transcript(plan))

    def test_normal_multisegment_plan_is_accepted_by_render_guard(self):
        units = []
        for index, start in enumerate((5.0, 45.0, 95.0), start=1):
            text = f"The family traveled home and met their friends in scene {index}."
            units.append({
                "id": index,
                "source_transcript_id": index - 1,
                "source_transcript_ids": [index - 1],
                "speech_start": start,
                "speech_end": start + 4.0,
                "source_text": text,
                "translation": "မိသားစုက အိမ်ပြန်ပြီး သူငယ်ချင်းများနှင့် တွေ့ဆုံခဲ့သည်။",
                "timestamp": f"{start:.3f} --> {start + 4.0:.3f}",
            })
        plan = recap_planner.make_translation_plan(
            units,
            143.0,
            source_title="normal",
            transcript={"transcript_validation": {"status": "complete"}},
            story_context={},
        )
        self.assertEqual(len(plan["segments"]), 3)
        core.validate_recap_audio_coverage(plan, 8.0)

    def test_143_second_source_and_269_second_narration_is_blocked_when_unverified(self):
        incident_plan = {
            "source_duration": 143.0,
            "segments": [{
                "source_text": "They're both coming back!",
                "gemini_start": 47.5,
                "gemini_end": 49.44,
            }],
        }
        self.assertTrue(recap_planner._plan_has_unverified_sparse_transcript(incident_plan))
        with self.assertRaisesRegex(RuntimeError, "RECAP_DURATION_VALIDATION_FAILED"):
            core.validate_recap_audio_coverage(incident_plan, 2.69)

    def test_render_pipeline_stops_before_video_render_for_incident_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job = root / "job"
            job.mkdir()
            source = root / "source.mp4"
            source.write_bytes(b"source")
            plan_path = job / "smart_sync_plan.json"
            plan_path.write_text(json.dumps({
                "source_duration": 143.0,
                "segments": [{
                    "video_start": 0.0,
                    "video_end": 143.0,
                    "gemini_start": 47.5,
                    "gemini_end": 49.44,
                    "source_text": "They're both coming back!",
                    "narration": "သူတို့နှစ်ယောက်စလုံး ပြန်လာနေကြပြီ!",
                }],
            }, ensure_ascii=False), encoding="utf-8")

            class FakeEdgeEngine:
                def __init__(self, *, work_dir, **_kwargs):
                    self.work_dir = Path(work_dir)

                def generate_channel99_voice(self, _text, _voice):
                    self.work_dir.mkdir(parents=True, exist_ok=True)
                    output = self.work_dir / "generated.wav"
                    output.write_bytes(b"fake wav")
                    return str(output)

            def concat_audio(_ffmpeg, _parts, output, _work):
                Path(output).write_bytes(b"joined audio")

            runner = core.EdgeSmartSync(
                job_dir=str(job),
                source_path=str(source),
                plan_path=str(plan_path),
                voice="my-MM-ThihaNeural",
                ffmpeg_path="unused",
                ffprobe_path="unused",
            )
            with mock.patch.object(core, "resolve_binary", return_value="unused"), \
                 mock.patch.object(core, "probe_video_size", return_value=(480, 850)), \
                 mock.patch.object(core, "probe_duration", return_value=2.69), \
                 mock.patch.object(core, "concat_audio", side_effect=concat_audio), \
                 mock.patch.object(core, "EdgeTTSEngine", FakeEdgeEngine), \
                 mock.patch.object(core, "render_video_part") as render:
                with self.assertRaisesRegex(RuntimeError, "RECAP_DURATION_VALIDATION_FAILED"):
                    runner.run()
            render.assert_not_called()

    def test_validated_low_dialogue_short_recap_is_allowed(self):
        confirmed_plan = {
            "source_duration": 143.0,
            "transcript_validation": {"status": "sparse_corroborated"},
            "segments": [{
                "source_text": "They're both coming back!",
                "gemini_start": 47.5,
                "gemini_end": 49.44,
            }],
        }
        core.validate_recap_audio_coverage(confirmed_plan, 2.69)

    def test_short_source_and_normal_multisegment_recap_are_allowed(self):
        core.validate_recap_audio_coverage(
            {"source_duration": 40.0, "segments": [{"source_text": "Only a short line."}]},
            2.69,
        )
        core.validate_recap_audio_coverage(
            {
                "source_duration": 143.0,
                "segments": [{
                    "source_text": "The family traveled home and met their friends.",
                    "gemini_start": 10.0,
                    "gemini_end": 14.0,
                }],
            },
            8.0,
        )

    def test_catastrophically_short_final_mux_is_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "FINAL_DURATION_VALIDATION_FAILED"):
            core.validate_final_mux_duration(143.0, 2.69)
        core.validate_final_mux_duration(2.69, 2.70)
        core.validate_final_mux_duration(66.533, 66.433)


if __name__ == "__main__":
    unittest.main()
