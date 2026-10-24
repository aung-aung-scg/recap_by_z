"""Edit Text: fix the Burmese narration of any line of a job's smart_sync_plan.json by hand.

The English source is shown next to the Burmese line. A saved line gets a new voice on START / RESUME (the
WAV key includes the text); every other line keeps its WAV. Opens by itself on the line Edge TTS stopped at
(a line mixing English and Burmese can get no audio at all, 2026-10-12).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable
import tkinter as tk
from tkinter import messagebox, ttk

from core import normalize_segments, segment_basename
from recap_planner import _foreign_letters, _latin_words, _note_text
from subtitle_text_widgets import NativeTextBox

_FAILED_SEGMENT_RE = re.compile(r"FAILED at segment\s+(\d+)", re.IGNORECASE)
_MIXED_DIGITS_RE = re.compile(r"[၀-၉][0-9]|[0-9][၀-၉]")


def failed_segment_from_error(text: str) -> int | None:
    """Segment number from a render error, e.g. 'Edge TTS FAILED at segment 1442 (...)'."""
    match = _FAILED_SEGMENT_RE.search(str(text or ""))
    return int(match.group(1)) if match else None


def narration_problems(text: str) -> list[str]:
    issues = []
    if _latin_words(text):
        issues.append("English words: " + ", ".join(_latin_words(text)[:6]) + " (write them in Burmese)")
    letters = _foreign_letters(text)
    if letters:
        issues.append("letters of another script: " + " ".join(letters))
    if _note_text(text):
        issues.append("a note about IDs instead of narration")
    if _MIXED_DIGITS_RE.search(str(text or "")):
        issues.append("mixed Myanmar/Latin digits (e.g. ၂၀0၁)")
    return issues


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class NarrationEditor(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        job_dir: Path,
        *,
        start_segment: int = 1,
        on_saved: Callable[[int, str], None] | None = None,
        colors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(master)
        self.job_dir = Path(job_dir)
        self.plan_path = self.job_dir / "smart_sync_plan.json"
        self.translations_path = self.job_dir / "timestamp_translations.json"
        self.tts_dir = self.job_dir / "edge_tts_smart_sync" / "tts_parts"
        self.on_saved = on_saved
        c = colors or {}
        self.bg, self.panel, self.fg, self.muted = (
            c.get("bg", "#0d0f14"), c.get("panel", "#151922"), c.get("fg", "#e7eaf0"), c.get("muted", "#9da7b6"))

        self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        self.segments = normalize_segments(self.plan)
        self.index = 1
        self.loaded_text = ""

        self.title(f"Edit Narration — {self.job_dir.name}")
        self.configure(bg=self.bg)
        self.geometry("900x600")
        self.minsize(720, 480)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._show(max(1, min(int(start_segment), len(self.segments))))

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        nav = ttk.Frame(self, padding=(10, 10, 10, 4))
        nav.pack(fill="x")
        ttk.Label(nav, text="Segment").pack(side="left")
        self.seg_var = tk.StringVar()
        entry = ttk.Entry(nav, textvariable=self.seg_var, width=7)
        entry.pack(side="left", padx=(6, 4))
        entry.bind("<Return>", lambda _e: self._go())
        ttk.Button(nav, text="Go", command=self._go).pack(side="left")
        ttk.Button(nav, text="◀ Prev", command=lambda: self._move(-1)).pack(side="left", padx=(12, 4))
        ttk.Button(nav, text="Next ▶", command=lambda: self._move(1)).pack(side="left")
        ttk.Button(nav, text="Next problem ▶", command=self._next_problem).pack(side="left", padx=(12, 0))
        self.count_var = tk.StringVar()
        ttk.Label(nav, textvariable=self.count_var).pack(side="right")

        self.info_var = tk.StringVar()
        tk.Label(self, textvariable=self.info_var, bg=self.bg, fg=self.muted, anchor="w",
                 font=("Segoe UI", 9)).pack(fill="x", padx=10)

        tk.Label(self, text="English source (read-only)", bg=self.bg, fg=self.fg, anchor="w",
                 font=("Segoe UI Semibold", 10)).pack(fill="x", padx=10, pady=(8, 2))
        self.source_box = tk.Text(self, height=4, wrap="word", bg=self.panel, fg=self.muted,
                                  relief="flat", padx=8, pady=6, font=("Segoe UI", 11))
        self.source_box.pack(fill="x", padx=10)

        tk.Label(self, text="Burmese narration (editable)", bg=self.bg, fg=self.fg, anchor="w",
                 font=("Segoe UI Semibold", 10)).pack(fill="x", padx=10, pady=(10, 2))
        # The buttons and the problem line are packed at the bottom FIRST: the text box takes only
        # the room that is left, so Save / Revert / Close are never cut off on a small window.
        actions = ttk.Frame(self, padding=10)
        actions.pack(side="bottom", fill="x")
        ttk.Button(actions, text="Save", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(actions, text="Revert", command=lambda: self._show(self.index)).pack(side="left", padx=8)
        ttk.Button(actions, text="Close", command=self._close).pack(side="right")
        ttk.Label(actions, text="Save ပြီးရင် START / RESUME နှိပ်ပါ — ပြင်ထားတဲ့ segment ကိုပဲ အသံပြန်ထုတ်မယ်။",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))

        self.problem_var = tk.StringVar()
        self.problem_label = tk.Label(self, textvariable=self.problem_var, bg=self.bg, fg="#ff8c8c",
                                      anchor="w", justify="left", font=("Segoe UI", 10))
        self.problem_label.pack(side="bottom", fill="x", padx=10, pady=(6, 0))

        self.native_box: NativeTextBox | None = None
        holder = tk.Frame(self, bg=self.panel, height=160)
        holder.pack(fill="both", expand=True, padx=10)
        try:
            self.native_box = NativeTextBox(holder, font="Myanmar Text", size_pt=14, bg=self.panel, fg=self.fg)
            self._last_seen = ""
            self.after(400, self._watch_native)
        except Exception:  # not Windows / RichEdit missing: Tk's own box (Myanmar caret may be off)
            self.native_box = None
            self.text_box = tk.Text(holder, height=7, wrap="word", bg=self.panel, fg=self.fg,
                                    insertbackground=self.fg, relief="flat", padx=8, pady=6,
                                    font=("Myanmar Text", 14), undo=True)
            self.text_box.pack(fill="both", expand=True)
            self.text_box.bind("<KeyRelease>", lambda _e: self._refresh_problems())

    # ------------------------------------------------------------- helpers
    def _plan_row(self, index: int) -> dict[str, Any]:
        return self.plan["segments"][int(self.segments[index - 1]["source_index"])]

    def _raw_text(self) -> str:
        return self.native_box.get() if self.native_box else self.text_box.get("1.0", "end")

    def _current_text(self) -> str:
        return re.sub(r"\s+", " ", self._raw_text()).strip()

    def _watch_native(self) -> None:
        """RichEdit is not a Tk widget (no <KeyRelease>), so the problem line follows it by polling."""
        if not self.winfo_exists():
            return
        text = self._raw_text()
        if text != self._last_seen:
            self._last_seen = text
            self._refresh_problems()
        self.after(400, self._watch_native)

    def _dirty(self) -> bool:
        return self._current_text() != self.loaded_text

    def _confirm_leave(self) -> bool:
        if not self._dirty():
            return True
        answer = messagebox.askyesnocancel("Unsaved", f"Segment {self.index} ပြင်ထားတာ save မလုပ်ရသေးပါ။ Save လုပ်မလား?", parent=self)
        if answer is None:
            return False
        if answer:
            return self._save()
        return True

    def _show(self, index: int) -> None:
        self.index = index
        seg = self.segments[index - 1]
        row = self._plan_row(index)
        self.loaded_text = str(seg["narration"])
        self.seg_var.set(str(index))
        self.count_var.set(f"{index} / {len(self.segments)}")
        wav = self.tts_dir / f"{segment_basename(seg)}.wav"
        self.info_var.set(
            f"{row.get('timestamp') or ''}   ·   video {seg['video_start']:.2f}–{seg['video_end']:.2f}s   ·   "
            f"WAV: {'done' if wav.is_file() else 'not generated yet'}   ·   ID {row.get('atomic_id', '')}"
        )
        self.source_box.configure(state="normal")
        self.source_box.delete("1.0", "end")
        self.source_box.insert("1.0", str(row.get("source_text", "")))
        self.source_box.configure(state="disabled")
        if self.native_box:
            self.native_box.set(self.loaded_text)
            self._last_seen = self._raw_text()
            self.native_box.focus()
        else:
            self.text_box.delete("1.0", "end")
            self.text_box.insert("1.0", self.loaded_text)
            self.text_box.edit_reset()
        self._refresh_problems()

    def _refresh_problems(self) -> None:
        problems = narration_problems(self._current_text())
        self.problem_var.set(("⚠️ " + " · ".join(problems)) if problems else "✅ No English words / script problems found")
        self.problem_label.configure(fg="#ff8c8c" if problems else "#7ddc9a")

    def _go(self) -> None:
        try:
            target = int(self.seg_var.get().strip())
        except ValueError:
            return
        if 1 <= target <= len(self.segments) and self._confirm_leave():
            self._show(target)

    def _move(self, step: int) -> None:
        target = self.index + step
        if 1 <= target <= len(self.segments) and self._confirm_leave():
            self._show(target)

    def _next_problem(self) -> None:
        if not self._confirm_leave():
            return
        total = len(self.segments)
        for offset in range(1, total + 1):
            target = (self.index - 1 + offset) % total + 1
            if narration_problems(self.segments[target - 1]["narration"]):
                self._show(target)
                return
        messagebox.showinfo("Next problem", "ပြဿနာရှိတဲ့ segment မတွေ့တော့ပါ။", parent=self)

    def _save(self) -> bool:
        text = self._current_text()
        if not text:
            messagebox.showerror("Save", "စာသား အလွတ် မဖြစ်ရပါ။", parent=self)
            return False
        if text == self.loaded_text:
            return True
        row = self._plan_row(self.index)
        row["narration"] = text
        row["translation"] = text
        _atomic_write_json(self.plan_path, self.plan)
        # Keep the translation checkpoint consistent in case the plan is ever rebuilt.
        if self.translations_path.is_file() and row.get("atomic_id") is not None:
            try:
                saved = json.loads(self.translations_path.read_text(encoding="utf-8"))
                for item in saved.get("items") or []:
                    if int(item.get("id", -1)) == int(row["atomic_id"]):
                        item["translation"] = text
                _atomic_write_json(self.translations_path, saved)
            except Exception as exc:
                messagebox.showwarning("Save", f"Plan saved, translation checkpoint not updated: {exc}", parent=self)
        self.segments[self.index - 1]["narration"] = text
        self.loaded_text = text
        if self.on_saved:
            self.on_saved(self.index, text)
        self._show(self.index)
        return True

    def _close(self) -> None:
        if self._confirm_leave():
            self.destroy()
