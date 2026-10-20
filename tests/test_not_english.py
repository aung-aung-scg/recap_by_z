"""Whisper heard no real speech (2026-10-13, a user's second video): the English-only Whisper wrote a few English
phrases again and again ("I'm not going to do it." ×40) on a Hindi video and the narration came out wrong. The job
stops before any Gemini request and says why. Since 2026-10-17 the source language is detected or chosen
(test_source_language.py), so this now catches a wrong language choice or a video of music/noise."""
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import recap_planner as rp  # noqa: E402

# small.en on 3 minutes of a Hindi recap (same settings as the tool)
HINDI = (["I am not busy, I am not busy, I am not busy,"] * 13
         + ["The strongest villain system is bound successfully."] * 9
         + ["I will not be able to be a hero.", "I will not be a hero.", "I will not be a hero.",
            "the body of the phenomenon."])
ENGLISH = [
    "In a world where cultivation decides everything, a young servant wakes up in a stranger's body.",
    "He finds out that the sect he serves is about to be destroyed.",
    "The elders gather in the main hall and argue about the coming war.",
    "Meanwhile, the young master orders him to clean the training grounds.",
    "While sweeping, he hears a voice in his head.",
    "Check-in system activated, the voice says.",
    "He checks in at the training grounds and receives a sword technique.",
    "The next morning he practises it in secret behind the kitchen.",
    "A senior sister sees him and laughs at his clumsy moves.",
    "But that night, the technique suddenly clicks.",
    "He cuts a falling leaf in half without touching the branch.",
    "Wait, wait, wait.",
    "Wait, wait, wait.",      # a real repetition in the narration is fine
]


def transcript(lines):
    return {"segments": [{"id": i, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": t} for i, t in enumerate(lines)]}


class NotEnglishTests(unittest.TestCase):
    def test_a_hindi_video_stops_with_the_reason(self):
        with self.assertRaises(RuntimeError) as caught:
            rp._check_heard_speech(transcript(HINDI), "whisper_transcript.txt")
        text = str(caught.exception)
        self.assertIn("English စကားကို ကောင်းကောင်း မကြားရပါဘူး", text)
        self.assertIn("Source language", text)
        self.assertIn('"i am not busy i am not busy i am not busy" ×13', text)
        self.assertIn("whisper_transcript.txt", text)

    def test_an_english_video_goes_on(self):
        rp._check_heard_speech(transcript(ENGLISH), "whisper_transcript.txt")
        share, count, _top = rp._repeated_line_share(transcript(ENGLISH))
        self.assertLess(share, rp.REPEAT_STOP_SHARE)
        self.assertEqual(count, len(ENGLISH))

    def test_a_very_short_transcript_is_not_judged(self):
        rp._check_heard_speech(transcript(["We are all here together."] * 6), "whisper_transcript.txt")

    def test_the_check_runs_before_the_translation(self):
        source = (APP / "recap_planner.py").read_text(encoding="utf-8")
        self.assertLess(source.index("_check_heard_speech(transcript, transcript_text_file.name, language_name)"),
                        source.index("units = atomicize_timestamp_segments("))


if __name__ == "__main__":
    unittest.main()
