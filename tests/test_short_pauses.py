from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import core

RATE = 24000


def make_clip(path: Path, lead: float, voice: float, tail: float) -> None:
    """Edge TTS-like clip: silence, a tone standing in for the voice, silence (mono 16-bit 24 kHz)."""
    frames = []
    for i in range(int((lead + voice + tail) * RATE)):
        t = i / RATE
        loud = lead <= t < lead + voice
        frames.append(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * t)) if loud else 0))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(b"".join(frames))


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as reader:
        return reader.getnframes() / reader.getframerate()


class TrimEdgeSilenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.clip = self.dir / "S0001.wav"
        make_clip(self.clip, lead=0.21, voice=1.0, tail=0.76)  # measured Edge TTS padding

    def test_join_pause_becomes_about_a_quarter_second(self) -> None:
        before = self.clip.read_bytes()
        used, seconds = core.trim_edge_silence(self.clip, self.dir / "short" / "S0001.wav")
        self.assertAlmostEqual(seconds, 0.05 + 1.0 + 0.20, delta=0.02)
        self.assertAlmostEqual(wav_seconds(used), seconds, delta=0.001)
        self.assertEqual(self.clip.read_bytes(), before)  # the TTS cache is never changed

    def test_never_shorter_than_the_picture_allows(self) -> None:
        _used, seconds = core.trim_edge_silence(self.clip, self.dir / "short" / "S0001.wav", min_duration=1.6)
        self.assertAlmostEqual(seconds, 1.6, delta=0.001)
        used, seconds = core.trim_edge_silence(self.clip, self.dir / "short" / "S0001.wav", min_duration=5.0)
        self.assertEqual(used, self.clip)  # already shorter than the floor: left as it was
        self.assertAlmostEqual(seconds, 1.97, delta=0.001)

    def test_silent_clip_is_left_alone(self) -> None:
        silent = self.dir / "silent.wav"
        make_clip(silent, lead=0.5, voice=0.0, tail=0.5)
        used, seconds = core.trim_edge_silence(silent, self.dir / "short" / "silent.wav")
        self.assertEqual(used, silent)
        self.assertAlmostEqual(seconds, 1.0, delta=0.001)

    def test_second_run_reuses_the_trimmed_clip(self) -> None:
        target = self.dir / "short" / "S0001.wav"
        core.trim_edge_silence(self.clip, target)
        stamp = target.stat().st_mtime_ns
        core.trim_edge_silence(self.clip, target)
        self.assertEqual(target.stat().st_mtime_ns, stamp)


class ShortPausesPipelineTests(unittest.TestCase):
    def _run(self, short_pauses: bool) -> tuple[list[float], list[float], list[float], list[float], dict]:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            job = base / "job"
            job.mkdir()
            source = base / "source.mp4"
            source.write_bytes(b"source")
            plan_path = job / "smart_sync_plan.json"
            plan_path.write_text(json.dumps({"segments": [
                # Overlong narration is fitted to its source interval, never by dropping footage.
                {"video_start": 0.0, "video_end": 1.2, "narration": "ပထမ စာကြောင်း။"},
                # Shorter narration pads with silence to retain the full 3.6-second source interval.
                {"video_start": 1.2, "video_end": 4.8, "narration": "ဒုတိယ စာကြောင်း။"},
            ]}, ensure_ascii=False), encoding="utf-8")
            render_targets: list[float] = []
            fit_targets: list[float] = []
            padding_targets: list[float] = []
            mux_padding_targets: list[float] = []

            class FakeEdgeEngine:
                def __init__(self, *, ffmpeg, work_dir, rate, pitch, log):
                    self.work_dir = Path(work_dir)
                    self.work_dir.mkdir(parents=True, exist_ok=True)
                    self.counter = 0

                def generate_channel99_voice(self, text, voice):
                    self.counter += 1
                    out = self.work_dir / f"fake_{self.counter}.wav"
                    make_clip(out, lead=0.2, voice=1.0 if self.counter == 1 else 2.0, tail=0.8)
                    return str(out)

            def probe(_ffprobe, path):
                try:
                    return wav_seconds(Path(path))  # the TTS clips are real WAVs
                except (wave.Error, EOFError, OSError):
                    return 4.8  # the fake joined voice / video files

            def fake_render(_ffmpeg, _source, dst, _seg, target, _encoder, *_args, **_kwargs):
                render_targets.append(round(float(target), 3))
                Path(dst).write_bytes(b"v" * 6000)
                return {"hybrid_used": 0.0, "applied_factor": 1.0}

            def fake_pad(_ffmpeg, _ffprobe, part, target, duration):
                if Path(target).name == "voice_mux_ready.wav":
                    mux_padding_targets.append(round(float(duration), 3))
                else:
                    padding_targets.append(round(float(duration), 3))
                return part, float(duration)

            def fake_fit(_ffmpeg, _ffprobe, part, target, duration):
                fit_targets.append(round(float(duration), 3))
                return part, float(duration)

            runner = core.EdgeSmartSync(
                job_dir=str(job), source_path=str(source), plan_path=str(plan_path),
                voice="my-MM-ThihaNeural", ffmpeg_path="/bin/true", ffprobe_path="/bin/true",
                render_final_video=True, mirror_video=False, zoom_factor=1.0, max_video_speed=1.25)
            runner.short_pauses = short_pauses
            with mock.patch.object(core, "EdgeTTSEngine", FakeEdgeEngine), \
                 mock.patch.object(core, "probe_duration", side_effect=probe), \
                 mock.patch.object(core, "concat_audio", side_effect=lambda _f, _p, out, _w: Path(out).write_bytes(b"a" * 2000)), \
                 mock.patch.object(core, "ffmpeg_encoders", return_value={"libx264"}), \
                 mock.patch.object(core, "pad_audio_to_duration", side_effect=fake_pad), \
                 mock.patch.object(core, "fit_audio_to_duration", side_effect=fake_fit), \
                 mock.patch.object(core, "render_video_part", side_effect=fake_render), \
                 mock.patch.object(core, "concat_video_parts", side_effect=lambda _f, _p, out, _w: Path(out).write_bytes(b"v" * 6000)), \
                 mock.patch.object(core, "apply_production_overlays", side_effect=lambda _f, video, *_args, **_kwargs: video), \
                 mock.patch.object(core, "mux_audio", side_effect=lambda _f, _v, _a, out, *_x: Path(out).write_bytes(b"m" * 6000)):
                runner.run()
            plan = json.loads((job / "edge_tts_smart_sync" / "smart_sync_plan_edge_tts.json").read_text(encoding="utf-8"))
            return render_targets, fit_targets, padding_targets, mux_padding_targets, plan

    def test_short_pauses_preserve_short_source_intervals_with_silence(self) -> None:
        targets, fit_targets, padding_targets, mux_padding_targets, plan = self._run(short_pauses=True)
        self.assertEqual(len(targets), 2)
        self.assertAlmostEqual(targets[0], 1.2, delta=0.01)
        self.assertAlmostEqual(targets[1], 3.6, delta=0.01)
        self.assertEqual(fit_targets, [1.2])
        self.assertEqual(padding_targets, [3.6])
        self.assertEqual(len(mux_padding_targets), 1)
        self.assertAlmostEqual(mux_padding_targets[0], sum(targets) + 0.1, delta=0.01)
        timing = plan["tts_timing_segments"]
        self.assertAlmostEqual(timing[1]["audio_start"], timing[0]["audio_end"], delta=0.001)
        self.assertEqual([round(x["audio_end"] - x["audio_start"], 3) for x in timing], [round(t, 3) for t in targets])
        self.assertAlmostEqual(plan["actual_audio_duration"], 4.8, delta=0.01)

    def test_short_pauses_off_still_preserves_full_source_intervals(self) -> None:
        targets, fit_targets, padding_targets, mux_padding_targets, _plan = self._run(short_pauses=False)
        self.assertEqual(targets, [1.2, 3.6])
        self.assertEqual(fit_targets, [1.2])
        self.assertEqual(padding_targets, [3.6])
        self.assertEqual(len(mux_padding_targets), 1)

    def test_overlong_audio_uses_a_tempo_chain_and_is_limited_to_target_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "overlong.wav"
                target = Path(temp) / "fitted" / "overlong.wav"
                completed = mock.Mock(returncode=0, stderr="")
                with mock.patch.object(core, "probe_duration", side_effect=[4.5, 1.5]), \
                     mock.patch.object(core.subprocess, "run", return_value=completed) as run:
                    output, duration = core.fit_audio_to_duration(
                        "/bin/true", "/bin/true", source, target, 1.5
                    )

        self.assertEqual(output, target)
        self.assertAlmostEqual(duration, 1.5)
        command = run.call_args.args[0]
        self.assertIn("atempo=2.0,atempo=1.500000,apad", command[command.index("-af") + 1])
        self.assertEqual(command[command.index("-t") + 1], "1.500000")


class FullFootageSyncTests(unittest.TestCase):
    def test_short_narration_never_speeds_up_or_trims_source_video(self) -> None:
        vf, metrics = core._sync_filter(10.0, 4.0, max_video_speed=1.25)
        self.assertIn("setpts=1.000000000*(PTS-STARTPTS)", vf)
        self.assertNotIn("trim=duration=4.000000", vf)
        self.assertEqual(metrics["target_duration"], 10.0)
        self.assertEqual(metrics["applied_factor"], 1.0)


if __name__ == "__main__":
    unittest.main()
