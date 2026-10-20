"""503 "high demand" (2026-10-17, users of the shared tool): a 503 on the last model of the chain stopped the job, and
one busy moment moved it down the chain for good. Every model busy now means wait and start again from the first
model; 5 minutes after a busy move the first model is tried again."""
import sys
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import recap_planner as rp  # noqa: E402


class FakeAI:
    def __init__(self, busy_answers: int):
        self.busy_left = busy_answers
        self.models_used: list[str] = []
        outer = self

        class Models:
            def generate_content(self, model, contents):
                outer.models_used.append(model)
                if outer.busy_left > 0:
                    outer.busy_left -= 1
                    raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
                return type("R", (), {"text": '{"ok": true}'})()

        self.client = type("C", (), {"models": Models()})()
        self.text_model = "x"

    def _enable_proxy(self):
        pass

    def _disable_proxy(self):
        pass


def setup(ai, chain=("m1", "m2", "m3")):
    def factory(api_key, http_options):
        return ai.client
    rp._configure_gemini_key_pool(ai, [("K1", "a"), ("K2", "b")], client_factory=factory, log=lambda _m: None,
                                  model_chain=list(chain))


class BusyModelTests(unittest.TestCase):
    def test_every_model_busy_waits_and_starts_again(self):
        ai = FakeAI(busy_answers=4)              # m1, m2, m3 busy, then m1 busy again, then m2 answers
        setup(ai)
        with mock.patch.object(rp.time, "sleep") as sleep:
            self.assertEqual(rp._gemini_json(ai, "p"), {"ok": True})
        self.assertEqual(ai.models_used, ["m1", "m2", "m3", "m1", "m2"])
        sleep.assert_called_once_with(30)

    def test_gives_up_after_the_rounds(self):
        ai = FakeAI(busy_answers=10_000)
        setup(ai)
        with mock.patch.object(rp.time, "sleep"), self.assertRaisesRegex(RuntimeError, "exhausted"):
            rp._gemini_json(ai, "p")
        self.assertEqual(len(ai.models_used), 3 * (rp.GEMINI_BUSY_ROUNDS + 1))

    def test_the_first_model_is_tried_again_later(self):
        ai = FakeAI(busy_answers=1)
        setup(ai)
        clock = [1000.0]
        with mock.patch.object(rp.time, "time", lambda: clock[0]):
            rp._gemini_json(ai, "p")                         # m1 busy -> m2 answers
            rp._gemini_json(ai, "p")                         # soon after: still m2
            clock[0] += rp.GEMINI_BUSY_RETRY_FIRST_SECONDS
            rp._gemini_json(ai, "p")                         # 5 min later: m1 again
        self.assertEqual(ai.models_used, ["m1", "m2", "m2", "m1"])


if __name__ == "__main__":
    unittest.main()
