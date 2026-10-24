from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Sequence

from subtitle_editing import edit_translation, revert_all_translations, revert_translation, validate_cue_sequence
from subtitle_io import SubtitleCue, TranslatedCue
from subtitle_text_widgets import NativeTextBox


def subtitle_problems(text: str) -> list[str]:
    problems = []
    if re.search(r"[A-Za-z]{2,}", text):
        problems.append("English words remain")
    if text.strip() and not any("\u1000" <= char <= "\u109f" or "\ua9e0" <= char <= "\ua9ff" for char in text):
        problems.append("No Myanmar Unicode characters found")
    return problems


class SubtitleCueEditor(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        source_cues: Sequence[SubtitleCue],
        gemini_cues: Sequence[TranslatedCue],
        current_cues: Sequence[TranslatedCue],
        *,
        on_saved: Callable[[Sequence[TranslatedCue]], None],
        colors: dict[str, str],
    ) -> None:
        super().__init__(master)
        validate_cue_sequence(source_cues, gemini_cues)
        validate_cue_sequence(source_cues, current_cues)
        if not any(cue.translation.strip() for cue in gemini_cues):
            raise ValueError("There are no translated cues to edit")
        self.source_cues = tuple(source_cues)
        self.gemini_cues = tuple(gemini_cues)
        self.current_cues = list(current_cues)
        self.on_saved = on_saved
        self.bg, self.panel, self.fg, self.muted = (
            colors.get("bg", "#0d0f14"),
            colors.get("panel", "#151922"),
            colors.get("fg", "#e7eaf0"),
            colors.get("muted", "#9da7b6"),
        )
        self.index = 1
        self.loaded_text = ""
        self._closing = False

        self.title("Edit Subtitle")
        self.configure(bg=self.bg)
        self.geometry("900x600")
        self.minsize(720, 480)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self._show(1)

    def _build(self) -> None:
        nav = ttk.Frame(self, padding=(10, 10, 10, 4))
        nav.pack(fill="x")
        ttk.Label(nav, text="Segment").pack(side="left")
        self.cue_var = tk.StringVar()
        entry = ttk.Entry(nav, textvariable=self.cue_var, width=7)
        entry.pack(side="left", padx=(6, 4))
        entry.bind("<Return>", lambda _event: self._go())
        ttk.Button(nav, text="Go", command=self._go).pack(side="left")
        ttk.Button(nav, text="◀ Prev", command=lambda: self._move(-1)).pack(side="left", padx=(12, 4))
        ttk.Button(nav, text="Next ▶", command=lambda: self._move(1)).pack(side="left")
        ttk.Button(nav, text="Next problem ▶", command=self._next_problem).pack(side="left", padx=(12, 0))
        self.count_var = tk.StringVar()
        ttk.Label(nav, textvariable=self.count_var).pack(side="right")

        self.info_var = tk.StringVar()
        tk.Label(
            self, textvariable=self.info_var, bg=self.bg, fg=self.muted, anchor="w",
            font=("Segoe UI", 9),
        ).pack(fill="x", padx=10)

        tk.Label(
            self, text="Original (read-only)", bg=self.bg, fg=self.fg, anchor="w",
            font=("Segoe UI Semibold", 10),
        ).pack(fill="x", padx=10, pady=(8, 2))
        self.source_box = tk.Text(
            self, height=4, wrap="word", bg=self.panel, fg=self.muted,
            relief="flat", padx=8, pady=6, font=("Segoe UI", 11),
        )
        self.source_box.pack(fill="x", padx=10)

        tk.Label(
            self, text="Burmese subtitle (editable)", bg=self.bg, fg=self.fg, anchor="w",
            font=("Segoe UI Semibold", 10),
        ).pack(fill="x", padx=10, pady=(10, 2))

        actions = ttk.Frame(self, padding=10)
        actions.pack(side="bottom", fill="x")
        ttk.Button(actions, text="Save", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(actions, text="Revert", command=lambda: self._show(self.index)).pack(side="left", padx=8)
        ttk.Button(actions, text="Revert cue", command=self._revert_cue).pack(side="left", padx=8)
        ttk.Button(actions, text="Revert all", command=self._revert_all).pack(side="left")
        ttk.Button(actions, text="Close", command=self._close).pack(side="right")

        self.problem_var = tk.StringVar()
        self.problem_label = tk.Label(
            self, textvariable=self.problem_var, bg=self.bg, fg="#ff8c8c",
            anchor="w", justify="left", font=("Segoe UI", 10),
        )
        self.problem_label.pack(side="bottom", fill="x", padx=10, pady=(6, 0))

        self.native_box: NativeTextBox | None = None
        holder = tk.Frame(self, bg=self.panel, height=160)
        holder.pack(fill="both", expand=True, padx=10)
        try:
            self.native_box = NativeTextBox(
                holder, font="Myanmar Text", size_pt=14, bg=self.panel, fg=self.fg,
            )
            self._last_seen = ""
            self.after(400, self._watch_native)
        except Exception:
            self.native_box = None
            self.text_box = tk.Text(
                holder, height=7, wrap="word", bg=self.panel, fg=self.fg,
                insertbackground=self.fg, relief="flat", padx=8, pady=6,
                font=("Myanmar Text", 14), undo=True,
            )
            self.text_box.pack(fill="both", expand=True)
            self.text_box.bind("<KeyRelease>", lambda _event: self._refresh_problems())

    @staticmethod
    def _timestamp(milliseconds: int) -> str:
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, fraction = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{fraction:03d}"

    def _current_text(self) -> str:
        raw = self.native_box.get() if self.native_box else self.text_box.get("1.0", "end")
        return raw.replace("\r\n", "\n").replace("\r", "\n").strip()

    def _watch_native(self) -> None:
        if self._closing or not self.winfo_exists():
            return
        text = self._current_text()
        if text != self._last_seen:
            self._last_seen = text
            self._refresh_problems()
        self.after(400, self._watch_native)

    def _refresh_problems(self) -> None:
        problems = subtitle_problems(self._current_text())
        self.problem_var.set(("⚠ " + " · ".join(problems)) if problems else "✓ No obvious subtitle script problems")
        self.problem_label.configure(fg="#ff8c8c" if problems else "#7ddc9a")

    def _dirty(self) -> bool:
        return self._current_text() != self.loaded_text

    def _confirm_leave(self) -> bool:
        if not self._dirty():
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved",
            f"Segment {self.index} has unsaved text. Save it before moving?",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self._save()
        return True

    def _show(self, index: int) -> None:
        cue = self.source_cues[index - 1]
        translated = self.current_cues[index - 1]
        self.index = index
        self.loaded_text = translated.translation
        self.cue_var.set(str(index))
        self.count_var.set(f"{index} / {len(self.source_cues)}")
        self.info_var.set(
            f"Segment {index}   ·   {self._timestamp(cue.start_ms)} → {self._timestamp(cue.end_ms)}"
        )
        self.source_box.configure(state="normal")
        self.source_box.delete("1.0", "end")
        self.source_box.insert("1.0", cue.text)
        self.source_box.configure(state="disabled")
        if self.native_box:
            self.native_box.set(self.loaded_text)
            self._last_seen = self._current_text()
            self.native_box.focus()
        else:
            self.text_box.delete("1.0", "end")
            self.text_box.insert("1.0", self.loaded_text)
            self.text_box.edit_reset()
        self._refresh_problems()

    def _go(self) -> None:
        try:
            target = int(self.cue_var.get().strip())
        except ValueError:
            return
        if 1 <= target <= len(self.source_cues) and self._confirm_leave():
            self._show(target)

    def _move(self, step: int) -> None:
        target = self.index + step
        if 1 <= target <= len(self.source_cues) and self._confirm_leave():
            self._show(target)

    def _next_problem(self) -> None:
        if not self._confirm_leave():
            return
        total = len(self.source_cues)
        for offset in range(1, total + 1):
            target = (self.index - 1 + offset) % total + 1
            if subtitle_problems(self.current_cues[target - 1].translation):
                self._show(target)
                return
        messagebox.showinfo("Next problem", "No untranslated subtitle cues remain.", parent=self)

    def _save(self) -> bool:
        text = self._current_text()
        if not text:
            messagebox.showerror("Save", "Subtitle segment cannot be empty.", parent=self)
            return False
        updated = edit_translation(
            self.source_cues, self.current_cues, self.index, text,
        )
        validate_cue_sequence(self.source_cues, updated)
        self.current_cues = updated
        self.loaded_text = text
        self.on_saved(self.current_cues)
        self._show(self.index)
        return True

    def _revert_cue(self) -> None:
        if not self._confirm_leave():
            return
        self.current_cues = revert_translation(
            self.source_cues, self.current_cues, self.gemini_cues, self.index,
        )
        self.on_saved(self.current_cues)
        self._show(self.index)

    def _revert_all(self) -> None:
        if not self._confirm_leave():
            return
        if not messagebox.askyesno(
            "Revert all", "Restore every cue to its Gemini translation?", parent=self,
        ):
            return
        self.current_cues = revert_all_translations(
            self.source_cues, self.current_cues, self.gemini_cues,
        )
        self.on_saved(self.current_cues)
        self._show(self.index)

    def _close(self) -> None:
        if self._confirm_leave():
            self._closing = True
            self.destroy()
