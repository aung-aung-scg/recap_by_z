"""Splitter tab (2026-10-17): parts of N minutes; smart cut waits for a pause (up to 20 s) instead of cutting a
sentence in two; frame ratio with a blurred background; text box and "Part 1" label. Needs ffmpeg, no network."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import numpy as np  # noqa: E402
import splitter as sp  # noqa: E402

F = sp.LEVEL_FRAME


def speech(seconds: float, pauses=(), music_db=None) -> np.ndarray:
    """-20 dB speech with a 0.1 s gap between words every second, quiet pauses (start, length) at -55 dB."""
    levels = np.full(int(seconds / F), -20.0)
    for s in np.arange(0, seconds, 1.0):
        levels[int(s / F):int(s / F) + 2] = -50.0
    for start, length in pauses:
        levels[int(start / F):int((start + length) / F)] = -55.0
    if music_db is not None:
        levels[levels < music_db] = music_db
    return levels


class PlanTests(unittest.TestCase):
    def test_exact_cuts_every_n_minutes(self):
        parts = sp.plan_parts(400, 180, smart=False)
        self.assertEqual([(p["start"], p["end"], p["cut"]) for p in parts],
                         [(0.0, 180.0, "exact"), (180.0, 360.0, "exact"), (360.0, 400.0, "end")])

    def test_smart_cut_waits_for_the_sentence_end(self):
        levels = speech(400, pauses=[(182.0, 0.25), (185.0, 0.6), (370.0, 0.45)])
        parts = sp.plan_parts(400, 180, smart=True, levels=levels)
        self.assertEqual([p["cut"] for p in parts], ["pause", "pause", "end"])
        self.assertTrue(185.0 < parts[0]["end"] < 185.6)          # in the 0.6 s pause, not the 0.25 s breath
        self.assertTrue(370.0 < parts[1]["end"] < 370.45)

    def test_speech_already_over_at_the_mark(self):
        levels = speech(400, pauses=[(179.5, 1.1), (185.0, 0.6)])
        self.assertTrue(180.0 <= sp.plan_parts(400, 180, smart=True, levels=levels)[0]["end"] < 180.6)

    def test_pauses_under_background_music_are_found(self):
        levels = speech(400, pauses=[(185.0, 0.6)], music_db=-34.0)
        self.assertTrue(185.0 < sp.plan_parts(400, 180, smart=True, levels=levels)[0]["end"] < 185.6)

    def test_never_later_than_allowed(self):
        levels = speech(400, pauses=[(205.0, 1.0)])                # the only pause is 25 s late
        part = sp.plan_parts(400, 180, smart=True, max_extra=20, levels=levels)[0]
        self.assertLessEqual(part["end"], 200.0)
        self.assertGreaterEqual(part["end"], 180.0)

    def test_a_short_tail_joins_the_last_part(self):
        parts = sp.plan_parts(370, 180, smart=False)                 # 10 s left (< 20 s): joins part 2
        self.assertEqual([(p["start"], p["end"]) for p in parts], [(0.0, 180.0), (180.0, 370.0)])
        self.assertEqual(len(sp.plan_parts(70, 30, smart=False)), 3)    # 10 s left of 30 s parts is kept

    def test_part_labels_keep_one_kind_of_digits(self):
        self.assertEqual(sp.part_label("Part {n}", 2, 5), "Part 2")
        self.assertEqual(sp.part_label("Part {n}/{total}", 2, 15), "Part 2/15")
        self.assertEqual(sp.part_label("အပိုင်း {mm}", 12, 15), "အပိုင်း ၁၂")
        self.assertEqual(sp.part_label("အပိုင်း {mm}/{total}", 2, 15), "အပိုင်း ၂/၁၅")   # not "၂/15"


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="splitter_"))
        self.src = self.tmp / "talk.mp4"
        # 30 s: tone 0-11.3 s, silence 11.3-12.1 s, tone to the end
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=30",
                        "-f", "lavfi", "-i",
                        "sine=f=300:d=30,volume='if(between(t,11.3,12.1),0,1)':eval=frame",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.src)],
                       check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def probe(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:format=duration", "-of", "default=nw=1", str(path)],
                             capture_output=True, text=True).stdout
        values = dict(line.split("=") for line in out.split())
        return int(values["width"]), int(values["height"]), float(values["duration"])

    def fake_png(self, text, output, font_size, max_width, box=True):
        from PIL import Image
        Image.new("RGBA", (120, 40), (255, 255, 255, 200)).save(output)
        self.labels.append(text)
        return output

    def test_parts_with_ratio_label_and_smart_cut(self):
        self.labels = []
        settings = {"minutes": 10 / 60, "smart_cut": True, "max_extra": 5, "ratio": "9:16", "fill": "blur",
                    "text": "Follow", "label_on": True, "label_template": "Part {n}/{total}",
                    "output_root": str(self.tmp / "out")}
        with mock.patch.object(sp, "render_text_png", self.fake_png):
            files = sp.split_video(self.src, settings, ffmpeg="ffmpeg", ffprobe="ffprobe", log=lambda _m: None)
        self.assertEqual([f.name for f in files], ["talk_part_01.mp4", "talk_part_02.mp4", "talk_part_03.mp4"])
        w, h, first = self.probe(files[0])
        self.assertEqual((w, h), (1080, 1920))
        self.assertAlmostEqual(first, 11.7, delta=0.25)            # waited for the silence at 11.3-12.1 s
        self.assertEqual(self.labels, ["Follow", "Part 1/3", "Part 2/3", "Part 3/3"])
        total = sum(self.probe(f)[2] for f in files)
        self.assertAlmostEqual(total, 30.0, delta=0.3)              # nothing lost, nothing twice

        # the same settings again: every part is kept, nothing is made twice
        self.labels = []
        with mock.patch.object(sp, "render_part") as render, mock.patch.object(sp, "render_text_png", self.fake_png):
            sp.split_video(self.src, settings, ffmpeg="ffmpeg", ffprobe="ffprobe", log=lambda _m: None)
        render.assert_not_called()

    def test_original_frame_exact_cuts_no_overlays(self):
        settings = {"minutes": 10 / 60, "smart_cut": False, "ratio": "Original", "label_on": False,
                    "output_root": str(self.tmp / "out")}
        files = sp.split_video(self.src, settings, ffmpeg="ffmpeg", ffprobe="ffprobe", log=lambda _m: None)
        self.assertEqual([self.probe(f)[:2] for f in files], [(640, 360)] * 3)
        self.assertAlmostEqual(self.probe(files[0])[2], 10.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
