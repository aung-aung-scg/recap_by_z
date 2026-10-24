from __future__ import annotations

import ast
import json
import os
import sys
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import subtitle_io  # noqa: E402
import subtitle_editing  # noqa: E402
import subtitle_translate  # noqa: E402
import subtitle_transcription  # noqa: E402
import subtitle_video_export  # noqa: E402


SRT_SAMPLE = (
    "1\r\n00:00:01,250 --> 00:00:03,500\r\nHello there.\r\n\r\n"
    "2\r\n00:00:04,000 --> 00:00:05,125\r\nHow are you?\r\n"
)
VTT_SAMPLE = (
    "WEBVTT\r\n\r\nintro\r\n00:01.250 --> 00:03.500 align:start\r\nHello there.\r\n\r\n"
    "00:04.000 --> 00:05.125\r\nHow are you?\r\n"
)


class FakeGemini:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

        class Models:
            def generate_content(inner_self, *, model, contents):
                self.prompts.append(contents)
                response = self.responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                if callable(response):
                    response = response(contents)
                return SimpleNamespace(text=response)

        self.models = Models()


def response_for(batch, start="မြန်မာစာ"):
    payload = {
        "items": [
            {"id": cue["id"], "translation": f"{start} {cue['text']}"}
            for cue in batch
        ]
    }
    return json.dumps(payload, ensure_ascii=False)


class SubtitleIoTests(unittest.TestCase):
    def test_parses_srt_and_keeps_timestamp_milliseconds_and_text(self):
        cues = subtitle_io.parse_subtitles(SRT_SAMPLE, ".srt")
        self.assertEqual([(cue.index, cue.start_ms, cue.end_ms, cue.text) for cue in cues], [
            (1, 1250, 3500, "Hello there."),
            (2, 4000, 5125, "How are you?"),
        ])

    def test_parses_vtt_with_optional_hours_identifiers_and_settings(self):
        cues = subtitle_io.parse_subtitles(VTT_SAMPLE, "vtt")
        self.assertEqual([(cue.start_ms, cue.end_ms, cue.text) for cue in cues], [
            (1250, 3500, "Hello there."),
            (4000, 5125, "How are you?"),
        ])

    def test_skips_webvtt_header_metadata_without_losing_first_cue(self):
        cues = subtitle_io.parse_subtitles(
            "WEBVTT\nKind: captions\nLanguage: en\n\n"
            "00:00:01.000 --> 00:00:02.000\nFirst cue\n\n"
            "00:00:03.000 --> 00:00:04.000\nSecond cue\n",
            "vtt",
        )
        self.assertEqual([cue.text for cue in cues], ["First cue", "Second cue"])

    def test_malformed_cue_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "invalid timestamp"):
            subtitle_io.parse_subtitles(
                "1\n00:00:01,000 --> 00:00:02,000\nFirst\n\n"
                "2\ninvalid --> 00:00:04,000\nSecond",
                "srt",
            )

    def test_writes_srt_and_round_trips_myanmar_unicode(self):
        cues = subtitle_io.parse_subtitles(SRT_SAMPLE, "srt")
        translated = [
            subtitle_io.TranslatedCue(cue, f"မြန်မာစာ {cue.index}။")
            for cue in cues
        ]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.srt"
            source.write_text(SRT_SAMPLE, encoding="utf-8")
            output = Path(folder) / "translated.srt"
            subtitle_io.write_srt(output, translated, source_path=source)
            serialized = output.read_bytes().decode("utf-8")
        parsed = subtitle_io.parse_subtitles(serialized, "srt")
        self.assertEqual([cue.text for cue in parsed], ["မြန်မာစာ 1။", "မြန်မာစာ 2။"])
        self.assertEqual(
            [(cue.start_ms, cue.end_ms) for cue in parsed],
            [(cue.start_ms, cue.end_ms) for cue in cues],
        )

    def test_export_refuses_to_overwrite_source_or_existing_file(self):
        cue = subtitle_io.parse_subtitles(SRT_SAMPLE, "srt")[0]
        translated = [subtitle_io.TranslatedCue(cue, "မြန်မာစာ")]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.srt"
            source.write_bytes(SRT_SAMPLE.encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "must not overwrite"):
                subtitle_io.write_srt(source, translated, source_path=source)
            self.assertEqual(source.read_bytes().decode("utf-8"), SRT_SAMPLE)
            output = Path(folder) / "translated.srt"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                subtitle_io.write_srt(output, translated, source_path=source)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing")


class SubtitleTranslationTests(unittest.TestCase):
    def setUp(self):
        self.cues = subtitle_io.parse_subtitles(SRT_SAMPLE, "srt")

    def test_batches_in_order_and_keeps_source_text_and_timestamps_separate(self):
        fake = FakeGemini([
            lambda prompt: response_for(
                [{"id": cue.index, "text": cue.text} for cue in self.cues[:1]],
            ),
            lambda prompt: response_for(
                [{"id": cue.index, "text": cue.text} for cue in self.cues[1:]],
            ),
        ])
        progress = []
        with mock.patch.object(subtitle_translate, "BATCH_SIZE", 1):
            output = subtitle_translate.translate_subtitle_cues(
                self.cues, client=fake, progress=lambda *values: progress.append(values),
            )
        self.assertEqual([item.source for item in output], self.cues)
        self.assertEqual([item.source.text for item in output], ["Hello there.", "How are you?"])
        self.assertEqual([item.translation for item in output], [
            "မြန်မာစာ Hello there.", "မြန်မာစာ How are you?",
        ])
        self.assertEqual([(item.source.start_ms, item.source.end_ms) for item in output], [
            (1250, 3500), (4000, 5125),
        ])
        self.assertEqual(progress[-1][:2], (2, 2))

    def test_invalid_batch_is_retried_then_fails_without_padding_or_dropping(self):
        invalid = '{"items":[{"id":1,"translation":"မြန်မာစာ"}]}'
        fake = FakeGemini([invalid, invalid, invalid])
        with mock.patch.object(subtitle_translate.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "cues 1–2 after 3 attempts"):
                subtitle_translate.translate_subtitle_cues(self.cues, client=fake)
        self.assertEqual(len(fake.prompts), 3)

    def test_provider_failure_is_retried_then_reported(self):
        fake = FakeGemini([RuntimeError("service unavailable")] * 3)
        with mock.patch.object(subtitle_translate.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "service unavailable"):
                subtitle_translate.translate_subtitle_cues(self.cues[:1], client=fake)
        self.assertEqual(len(fake.prompts), 3)

    def test_failed_later_batch_retains_completed_cues_for_partial_editing(self):
        first_answer = response_for([{"id": 1, "text": self.cues[0].text}])
        fake = FakeGemini([
            first_answer,
            ValueError("invalid response"),
            ValueError("invalid response"),
            ValueError("invalid response"),
        ])
        with mock.patch.object(subtitle_translate, "BATCH_SIZE", 1), \
                mock.patch.object(subtitle_translate.time, "sleep"):
            with self.assertRaises(subtitle_translate.SubtitleBatchError) as caught:
                subtitle_translate.translate_subtitle_cues(self.cues, client=fake)
        self.assertEqual(len(caught.exception.translated), 1)
        self.assertEqual(caught.exception.translated[0].source, self.cues[0])

    def test_source_sequence_is_validated_before_request(self):
        invalid = [subtitle_io.SubtitleCue(2, 100, 200, "text")]
        fake = FakeGemini([])
        with self.assertRaisesRegex(ValueError, "not consecutive"):
            subtitle_translate.translate_subtitle_cues(invalid, client=fake)
        self.assertEqual(fake.prompts, [])

    def test_cancel_is_checked_between_batches(self):
        event = threading.Event()
        event.set()
        fake = FakeGemini([])
        with self.assertRaises(InterruptedError):
            subtitle_translate.translate_subtitle_cues(self.cues, client=fake, stop_event=event)
        self.assertEqual(fake.prompts, [])

    def test_custom_proxy_from_env_is_used_by_the_gemini_client_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / ".env"
            env_file.write_text("GEMINI_PROXY=http://127.0.0.1:10808\n", encoding="utf-8")
            with mock.patch.object(subtitle_translate.socket, "create_connection") as connect:
                self.assertEqual(subtitle_translate._gemini_proxy(env_file), "http://127.0.0.1:10808")
            connect.assert_not_called()


class SubtitleEditingTests(unittest.TestCase):
    def setUp(self):
        self.source = subtitle_io.parse_subtitles(SRT_SAMPLE, "srt")
        self.gemini = [
            subtitle_io.TranslatedCue(self.source[0], "ပထမ ဘာသာပြန်"),
            subtitle_io.TranslatedCue(self.source[1], "ဒုတိယ ဘာသာပြန်"),
        ]

    def test_edit_changes_only_burmese_text_and_preserves_source_and_timestamps(self):
        edited = subtitle_editing.edit_translation(
            self.source, self.gemini, 1, "ပထမ ပြင်ဆင်ထားသောစာ",
        )
        self.assertEqual(edited[0].source, self.source[0])
        self.assertEqual(edited[0].source.text, "Hello there.")
        self.assertEqual((edited[0].source.start_ms, edited[0].source.end_ms), (1250, 3500))
        self.assertEqual(edited[0].translation, "ပထမ ပြင်ဆင်ထားသောစာ")

    def test_export_uses_edited_text(self):
        edited = subtitle_editing.edit_translation(
            self.source, self.gemini, 2, "ဒုတိယ ပြင်ထားသောစာ",
        )
        with tempfile.TemporaryDirectory() as folder:
            source_path = Path(folder) / "source.srt"
            source_path.write_text(SRT_SAMPLE, encoding="utf-8")
            destination = Path(folder) / "translated.srt"
            subtitle_io.write_srt(destination, edited, source_path=source_path)
            serialized = destination.read_text(encoding="utf-8")
        parsed = subtitle_io.parse_subtitles(serialized, "srt")
        self.assertEqual(parsed[1].text, "ဒုတိယ ပြင်ထားသောစာ")
        self.assertEqual((parsed[1].start_ms, parsed[1].end_ms), (4000, 5125))

    def test_revert_cue_and_revert_all_restore_gemini_translations(self):
        edited = subtitle_editing.edit_translation(
            self.source, self.gemini, 1, "ပြောင်းထားသောစာ",
        )
        one_reverted = subtitle_editing.revert_translation(
            self.source, edited, self.gemini, 1,
        )
        self.assertEqual(one_reverted, self.gemini)
        changed_again = subtitle_editing.edit_translation(
            self.source, self.gemini, 2, "ပြောင်းထားသောစာ",
        )
        all_reverted = subtitle_editing.revert_all_translations(
            self.source, changed_again, self.gemini,
        )
        self.assertEqual(all_reverted, self.gemini)

    def test_cue_count_and_source_identity_are_validated(self):
        with self.assertRaisesRegex(ValueError, "Cue count changed"):
            subtitle_editing.validate_cue_sequence(self.source, self.gemini[:1])
        modified_source = [
            subtitle_io.SubtitleCue(1, 1250, 3500, "changed original"),
            self.source[1],
        ]
        with self.assertRaisesRegex(ValueError, "Original cue text, number or timestamp changed"):
            subtitle_editing.validate_cue_sequence(modified_source, self.gemini)


class SubtitleVideoWorkflowTests(unittest.TestCase):
    def test_whisper_worker_logging_survives_cp932_default_encoding(self):
        worker = APP / "subtitle_transcription.py"
        env = os.environ.copy()
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "cp932"
        result = subprocess.run(
            [sys.executable, str(worker), "--logging-self-test"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\u2b07", result.stdout)
        self.assertIn("မြန်မာစာ", result.stdout)

    def test_whisper_segments_become_ordered_millisecond_cues(self):
        cues = subtitle_transcription.transcribed_cues([
            {"start": 1.2346, "end": 2.5, "text": "Original speech"},
            {"start": 3.0, "end": 4.125, "text": "More speech"},
        ])
        self.assertEqual(cues, [
            subtitle_io.SubtitleCue(1, 1235, 2500, "Original speech"),
            subtitle_io.SubtitleCue(2, 3000, 4125, "More speech"),
        ])

    def test_invalid_whisper_timestamps_are_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "invalid time range"):
            subtitle_transcription.transcribed_cues([
                {"start": 2.0, "end": 1.0, "text": "Speech"},
            ])

    def test_temporary_whisper_audio_is_removed_after_success_or_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "source.mp4"
            video.write_bytes(b"video")
            observed_dirs = []

            def fake_extract(_ffmpeg, _video, audio, _stop):
                audio.write_bytes(b"temporary audio")
                observed_dirs.append(audio.parent)

            with mock.patch.object(subtitle_transcription, "_extract_audio", side_effect=fake_extract), \
                    mock.patch.object(
                        subtitle_transcription, "_run_whisper_worker",
                        return_value={"segments": [{"start": 0, "end": 1, "text": "Hello"}], "language": "en"},
                    ):
                cues, language = subtitle_transcription.transcribe_video(
                    "ffmpeg", video, stop_event=threading.Event(),
                )
            self.assertEqual(cues[0].text, "Hello")
            self.assertEqual(language, "en")
            self.assertFalse(observed_dirs[-1].exists())

            stop = threading.Event()

            def cancel_extract(_ffmpeg, _video, audio, _stop):
                audio.write_bytes(b"temporary audio")
                observed_dirs.append(audio.parent)
                raise InterruptedError("cancel")

            with mock.patch.object(subtitle_transcription, "_extract_audio", side_effect=cancel_extract):
                with self.assertRaises(InterruptedError):
                    subtitle_transcription.transcribe_video("ffmpeg", video, stop_event=stop)
            self.assertFalse(observed_dirs[-1].exists())

    def test_video_command_burns_timed_frames_and_copies_original_audio(self):
        cue = subtitle_io.SubtitleCue(1, 1250, 3500, "Original")
        translated = [subtitle_io.TranslatedCue(cue, "မြန်မာစာ")]
        command = subtitle_video_export.make_ffmpeg_export_command(
            "ffmpeg", Path("source.mp4"), Path("out.mp4"), translated,
            [Path("subtitle.png")], (1920, 1080), 86,
        )
        self.assertEqual(command[command.index("-map") + 1], "[vout]")
        self.assertEqual(command[command.index("-map", command.index("-map") + 1) + 1], "0:a?")
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertNotIn("-an", command)
        self.assertIn("between(t\\,1.250\\,3.500)", command[command.index("-filter_complex") + 1])

    def test_video_export_validates_original_cue_count_before_rendering(self):
        with tempfile.TemporaryDirectory() as folder:
            source_path = Path(folder) / "source.mp4"
            source_path.write_bytes(b"source")
            original = subtitle_io.parse_subtitles(SRT_SAMPLE, "srt")
            translated = [subtitle_io.TranslatedCue(original[0], "မြန်မာစာ")]
            with self.assertRaisesRegex(ValueError, "Cue count changed"):
                subtitle_video_export.export_burned_subtitles(
                    "ffmpeg", "ffprobe", source_path, original, translated,
                    Path(folder) / "out.mp4", stop_event=threading.Event(),
                )

    def test_video_output_path_never_overwrites_an_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "clip.mp4"
            source.write_bytes(b"original")
            output = subtitle_video_export.video_output_path(source)
            self.assertEqual(output.name, "clip_burmese_subs.mp4")
            output.write_bytes(b"existing")
            next_output = subtitle_video_export.video_output_path(source)
            self.assertEqual(next_output.name, "clip_burmese_subs_2.mp4")
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(output.read_bytes(), b"existing")


class SubtitleCueEditorStructureTests(unittest.TestCase):
    def test_editor_uses_recap_navigation_and_subtitle_only_fields(self):
        path = APP / "subtitle_cue_editor.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        editor = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SubtitleCueEditor"
        )
        methods = {
            node.name for node in editor.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        buttons = {
            keyword.value.value
            for node in ast.walk(editor)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Button"
            for keyword in node.keywords
            if keyword.arg == "text"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        }
        source = path.read_text(encoding="utf-8")
        self.assertTrue({"_go", "_move", "_next_problem"} <= methods)
        self.assertTrue(
            {"Go", "◀ Prev", "Next ▶", "Next problem ▶", "Save", "Revert", "Revert cue", "Revert all", "Close"}
            <= buttons
        )
        self.assertIn("Original (read-only)", source)
        self.assertIn("Burmese subtitle (editable)", source)
        self.assertIn('self.source_box.configure(state="disabled")', source)
        self.assertIn('font="Myanmar Text"', source)
        self.assertNotIn("NarrationEditor", source)
        self.assertIn("_refresh_problems", methods)


class SubtitleIsolationTests(unittest.TestCase):
    def test_subtitle_modules_do_not_import_or_call_audio_or_sync_code(self):
        forbidden = {
            "core", "recap_planner", "planner_worker", "render_worker", "whisper_service",
            "edge_tts", "audio", "audio_service", "tts", "sync", "smart_sync",
        }
        files = (
            APP / "subtitle_io.py",
            APP / "subtitle_translate.py",
            APP / "subtitle_translator_tab.py",
            APP / "subtitle_editing.py",
            APP / "subtitle_cue_editor.py",
            APP / "subtitle_text_widgets.py",
            APP / "subtitle_transcription.py",
            APP / "subtitle_video_export.py",
        )
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = set()
            called = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
                elif isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else (
                        node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    )
                    called.add(name.lower())
            self.assertFalse(imported & forbidden, f"forbidden module import in {path.name}")
            self.assertFalse(called & {name.lower() for name in forbidden}, f"forbidden call in {path.name}")
            self.assertFalse(
                {
                    "edgettsengine", "edgesmartsync", "mux_audio", "concat_audio",
                    "generate_channel99_voice", "replace_audio", "sync_video",
                } & called,
                f"audio generation or sync call in {path.name}",
            )

    def test_video_translation_has_no_srt_export_step(self):
        path = APP / "subtitle_translator_tab.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("write_srt", imported_names)
        self.assertNotIn("Export SRT", source)
        self.assertIn("Export video with subtitles", source)
        self.assertIn("self.video_path", source)

    def test_whisper_is_the_only_recap_runtime_service_reused_by_subtitles(self):
        source = (APP / "subtitle_transcription.py").read_text(encoding="utf-8")
        self.assertIn('"whisper_service.py"', source)
        self.assertIn("WhisperTimestampService", source)
        self.assertNotIn("recap_planner", source)


if __name__ == "__main__":
    unittest.main()
