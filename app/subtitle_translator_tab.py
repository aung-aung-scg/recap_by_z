from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Sequence

from subtitle_cue_editor import SubtitleCueEditor, subtitle_problems
from subtitle_editing import validate_cue_sequence
from subtitle_io import (
    SubtitleCue,
    SubtitleTrack,
    TranslatedCue,
    extract_embedded_subtitle_track,
    list_embedded_subtitle_tracks,
    parse_subtitles,
)
from subtitle_translate import (
    DEFAULT_MODEL,
    SubtitleBatchError,
    create_gemini_client,
    load_gemini_api_key,
    translate_subtitle_cues,
)
from subtitle_transcription import transcribe_video
from subtitle_video_export import export_burned_subtitles, video_output_path


class SubtitleTranslatorTab(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        cfg: dict,
        save: Callable[[], None],
        tool: Callable[[str], str],
    ) -> None:
        super().__init__(master, padding=(12, 8, 12, 8))
        self.cfg = cfg
        self._save = save
        self._tool = tool
        self.settings = cfg.setdefault("subtitle_translator", {})
        self.msgq: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._busy = False
        self._closing = False
        self.source_path: Path | None = None
        self.source_kind = ""
        self.video_path: Path | None = None
        self.output_video: Path | None = None
        self.source_cues: tuple[SubtitleCue, ...] = ()
        self.translated_cues: tuple[TranslatedCue, ...] = ()
        self.gemini_cues: tuple[TranslatedCue, ...] = ()
        self.tracks: list[SubtitleTrack] = []
        self._text_editor: SubtitleCueEditor | None = None
        self._source_label = tk.StringVar(value="No subtitle source selected")
        self._video_label = tk.StringVar(value="No video selected for export")
        self._track_choice = tk.StringVar(value="")
        self._env_path = tk.StringVar(
            value=str(self.settings.get("gemini_env_path") or cfg.get("gemini_env_path") or Path(__file__).resolve().parents[1] / ".env")
        )
        self._output_folder = tk.StringVar(value=str(self.settings.get("output_folder") or ""))
        self._font_percent = tk.StringVar(value=str(self.settings.get("font_percent", 5)))
        self._vertical_position = tk.StringVar(value=str(self.settings.get("vertical_position", 86)))
        self._status = tk.StringVar(value="READY")
        self._build()
        self.after(150, self._pump)

    def _build(self) -> None:
        palette = getattr(self.winfo_toplevel(), "palette", {})
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Frame(self, style="Header.TFrame", padding=(12, 8))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(header, text="Subtitle Translator", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header, text="Transcribe or translate subtitles, then export a video · audio stays unchanged",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(5, 0))

        source_box = ttk.LabelFrame(self, text="VIDEO OR SUBTITLE SOURCE", style="Card.TLabelframe", padding=8)
        source_box.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        source_box.columnconfigure(1, weight=1)
        self.subtitle_file_button = ttk.Button(
            source_box, text="Open SRT / VTT...", style="Compact.TButton", command=self._choose_subtitle_file,
        )
        self.subtitle_file_button.grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self.video_button = ttk.Button(
            source_box, text="Open video...", style="Compact.TButton", command=self._choose_video,
        )
        self.video_button.grid(row=0, column=1, sticky="w", pady=3)
        self.transcribe_button = ttk.Button(
            source_box, text="Transcribe speech", style="Compact.TButton", command=self._transcribe,
            state="disabled",
        )
        self.transcribe_button.grid(row=0, column=2, sticky="w", padx=(6, 0), pady=3)
        self.export_video_source_button = ttk.Button(
            source_box, text="Video for export...", style="Compact.TButton",
            command=self._choose_export_video,
        )
        self.export_video_source_button.grid(row=0, column=3, sticky="w", padx=(6, 0), pady=3)
        ttk.Label(source_box, textvariable=self._source_label, wraplength=900, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(4, 2),
        )
        ttk.Label(source_box, textvariable=self._video_label, wraplength=900, justify="left").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=(0, 6),
        )
        ttk.Label(source_box, text="Embedded track").grid(row=3, column=0, sticky="w", padx=(0, 6))
        self.track_combo = ttk.Combobox(source_box, textvariable=self._track_choice, state="readonly")
        self.track_combo.grid(row=3, column=1, sticky="ew", padx=(0, 6))
        self.load_track_button = ttk.Button(
            source_box, text="Load track", style="Compact.TButton", command=self._load_selected_track,
        )
        self.load_track_button.grid(row=3, column=2, sticky="e")
        self.track_combo.bind("<<ComboboxSelected>>", self._track_selection_changed)

        options = ttk.Frame(source_box)
        options.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        options.columnconfigure(1, weight=1)
        ttk.Label(options, text="Gemini .env").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(options, textvariable=self._env_path).grid(row=0, column=1, sticky="ew", pady=3)
        self.env_button = ttk.Button(
            options, text="Browse...", style="Compact.TButton", command=self._choose_env,
        )
        self.env_button.grid(row=0, column=2, padx=(6, 0), pady=3)
        ttk.Label(options, text="Output video folder (optional)").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=3,
        )
        ttk.Entry(options, textvariable=self._output_folder).grid(row=1, column=1, sticky="ew", pady=3)
        self.output_button = ttk.Button(
            options, text="Browse...", style="Compact.TButton", command=self._choose_output_folder,
        )
        self.output_button.grid(row=1, column=2, padx=(6, 0), pady=3)
        ttk.Label(options, text="Font size (% of short edge)").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=3,
        )
        ttk.Spinbox(options, textvariable=self._font_percent, from_=3, to=10, width=5).grid(
            row=2, column=1, sticky="w", pady=3,
        )
        ttk.Label(options, text="Vertical position (% from top)").grid(
            row=2, column=2, sticky="w", padx=(12, 6), pady=3,
        )
        ttk.Spinbox(options, textvariable=self._vertical_position, from_=0, to=100, width=5).grid(
            row=2, column=3, sticky="w", pady=3,
        )

        preview_box = ttk.LabelFrame(self, text="PREVIEW · ORIGINAL TEXT IS KEPT SEPARATE", style="Card.TLabelframe")
        preview_box.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
        preview_box.rowconfigure(0, weight=1)
        preview_box.columnconfigure(0, weight=1)
        columns = ("cue", "time", "original", "burmese")
        self.preview = ttk.Treeview(preview_box, columns=columns, show="headings", style="Split.Treeview")
        self.preview.heading("cue", text="#")
        self.preview.heading("time", text="Time")
        self.preview.heading("original", text="Original")
        self.preview.heading("burmese", text="Burmese")
        self.preview.tag_configure("edited", foreground=palette.get("accent", "#38BDF8"))
        self.preview.column("cue", width=48, minwidth=48, stretch=False, anchor="center")
        self.preview.column("time", width=180, minwidth=160, stretch=False)
        self.preview.column("original", width=440, minwidth=220, stretch=True)
        self.preview.column("burmese", width=440, minwidth=220, stretch=True)
        y_scroll = ttk.Scrollbar(preview_box, orient="vertical", command=self.preview.yview)
        x_scroll = ttk.Scrollbar(preview_box, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100, style="Production.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.status_label = ttk.Label(footer, textvariable=self._status, width=20, anchor="w")
        self.status_label.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.start_button = ttk.Button(footer, text="Translate to Burmese", style="Accent.TButton", command=self._start)
        self.start_button.grid(row=0, column=2, padx=(0, 6))
        self.edit_button = ttk.Button(footer, text="Edit Text", command=self._open_editor, state="disabled")
        self.edit_button.grid(row=0, column=3, padx=(0, 6))
        self.export_button = ttk.Button(
            footer, text="Export video with subtitles", command=self._export, state="disabled",
        )
        self.export_button.grid(row=0, column=4, padx=(0, 6))
        self.open_folder_button = ttk.Button(
            footer, text="Open folder", command=self._open_output_folder, state="disabled",
        )
        self.open_folder_button.grid(row=0, column=5, padx=(0, 6))
        self.cancel_button = ttk.Button(
            footer, text="Cancel", style="Danger.TButton", command=self._cancel, state="disabled",
        )
        self.cancel_button.grid(row=0, column=6)

        self.logbox = tk.Text(
            self, height=5, wrap="word", bg=palette.get("field", "#0B0F14"),
            fg=palette.get("log_fg", "#F3F4F6"), insertbackground=palette.get("fg", "#F3F4F6"),
            relief="flat", padx=8, pady=5,
        )
        self.logbox.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.logbox.configure(state="disabled")
        self.track_combo.configure(values=())
        self.track_combo.state(["disabled"])
        self.load_track_button.configure(state="disabled")
        self._set_busy(False)

    def _choose_subtitle_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select source subtitle file",
            filetypes=[("Subtitle files", "*.srt *.vtt"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() not in {".srt", ".vtt"}:
            messagebox.showerror("Subtitle Translator", "Choose an .srt or .vtt file.")
            return
        self._prepare_source(path, "file", f"Subtitle file · {path}")
        self._begin_background(
            "Loading subtitle file",
            lambda: parse_subtitles(path.read_text(encoding="utf-8-sig"), path.suffix),
        )

    def _choose_video(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select video to transcribe or use embedded subtitles",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        self._prepare_source(path, "video", f"Video source · {path}")
        self.tracks = []
        self.track_combo.configure(values=())
        self._track_choice.set("")
        self.track_combo.state(["disabled"])
        self._begin_background(
            "Finding embedded subtitle tracks",
            lambda: list_embedded_subtitle_tracks(self._tool("ffprobe"), path, stop_event=self.stop_event),
            result_kind="tracks",
        )

    def _choose_export_video(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select video for subtitle export",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All files", "*.*")],
        )
        if not selected:
            return
        self.video_path = Path(selected).resolve()
        self._video_label.set(f"Video for export · {self.video_path}")
        self.output_video = None
        self.open_folder_button.configure(state="disabled")
        self._update_translation_buttons()

    def _prepare_source(self, path: Path, kind: str, label: str) -> None:
        self._close_editor()
        self.stop_event.set()
        self.source_path = path.resolve()
        self.source_kind = kind
        self.source_cues = ()
        self.translated_cues = ()
        self.gemini_cues = ()
        self.tracks = []
        self._track_choice.set("")
        self._source_label.set(label)
        if kind == "video":
            self.video_path = path.resolve()
            self._video_label.set(f"Video for export · {self.video_path}")
        self.output_video = None
        self.open_folder_button.configure(state="disabled")
        self._clear_preview()
        self.progress["value"] = 0
        self._status.set("LOADING")
        self.track_combo.configure(values=())
        self.track_combo.state(["disabled"])
        self.load_track_button.configure(state="disabled")

    def _track_selection_changed(self, _event=None) -> None:
        self._close_editor()
        self.source_cues = ()
        self.translated_cues = ()
        self.gemini_cues = ()
        self._clear_preview()
        self._status.set("LOAD SELECTED TRACK")
        self._set_busy(False)

    def _load_selected_track(self) -> None:
        if self.source_path is None or self.source_kind != "video":
            return
        selected = self._track_choice.get()
        track = next((item for item in self.tracks if item.label == selected), None)
        if track is None:
            messagebox.showinfo("Subtitle Translator", "Select an embedded subtitle track first.")
            return
        path = self.source_path
        self._source_label.set(f"Embedded track · {path.name} · {track.label}")

        def extract_and_parse() -> list[SubtitleCue]:
            content = extract_embedded_subtitle_track(
                self._tool("ffmpeg"), path, track, stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                raise InterruptedError("Subtitle track loading cancelled")
            return parse_subtitles(content, "srt")

        self._begin_background("Extracting embedded subtitle track", extract_and_parse)

    def _transcribe(self) -> None:
        if self._busy or self.source_path is None or self.source_kind != "video":
            return
        video = self.source_path

        def action() -> tuple[list[SubtitleCue], str]:
            return transcribe_video(
                self._tool("ffmpeg"),
                video,
                stop_event=self.stop_event,
                progress=lambda done, total, label: self.msgq.put(("progress", (done, total, label))),
                log=self._log,
            )

        self._begin_background("Transcribing video speech", action, result_kind="transcribed")

    def _choose_env(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select .env containing Gemini API key",
            initialdir=str(Path(self._env_path.get() or ".").parent),
            filetypes=[("ENV files", ".env"), ("All files", "*.*")],
        )
        if selected:
            self._env_path.set(selected)

    def _choose_output_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choose video output folder")
        if selected:
            self._output_folder.set(selected)
            self.settings["output_folder"] = selected
            try:
                self._save()
            except OSError as exc:
                messagebox.showerror("Subtitle Translator", f"Could not save settings: {exc}")

    def _begin_background(self, label: str, action, *, result_kind: str = "cues") -> None:
        if self._busy:
            return
        self.stop_event.clear()
        self._set_busy(True)
        self._status.set(label.upper())

        def work() -> None:
            try:
                result = action()
                if self.stop_event.is_set():
                    raise InterruptedError(f"{label} cancelled")
                self.msgq.put((result_kind, result))
            except InterruptedError as exc:
                self.msgq.put(("cancelled", str(exc)))
            except Exception as exc:
                self.msgq.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _start(self) -> None:
        if self._busy:
            return
        if self.source_path is None or not self.source_cues:
            messagebox.showinfo(
                "Subtitle Translator",
                "Open a video and transcribe speech or load its embedded track, or open an SRT/VTT file.",
            )
            return
        source_cues = self.source_cues
        env_path = Path(self._env_path.get().strip()).expanduser()
        output_folder = self._output_folder.get().strip()
        self.settings["gemini_env_path"] = str(env_path)
        self.settings["output_folder"] = output_folder
        try:
            self._save()
        except OSError as exc:
            messagebox.showerror("Subtitle Translator", f"Could not save settings: {exc}")
            return
        self.translated_cues = tuple(TranslatedCue(cue, "") for cue in source_cues)
        self.gemini_cues = ()
        self._refresh_preview()
        self.progress["value"] = 0
        self.stop_event.clear()
        self._set_busy(True)
        self._status.set("TRANSLATING")

        def work() -> None:
            try:
                api_key = load_gemini_api_key(env_path)
                client = create_gemini_client(api_key, env_path)
                translated = translate_subtitle_cues(
                    source_cues,
                    client=client,
                    model=DEFAULT_MODEL,
                    stop_event=self.stop_event,
                    progress=lambda done, total, label: self.msgq.put(("progress", (done, total, label))),
                    log=lambda text: self.msgq.put(("log", text)),
                )
                if self.stop_event.is_set():
                    raise InterruptedError("Subtitle translation cancelled")
                validate_cue_sequence(source_cues, translated)
                self.msgq.put(("translation_ready", translated))
            except SubtitleBatchError as exc:
                self.msgq.put(("partial", (exc.translated, str(exc))))
            except InterruptedError as exc:
                self.msgq.put(("cancelled", str(exc)))
            except Exception as exc:
                self.msgq.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _cancel(self) -> None:
        if self._busy:
            self.stop_event.set()
            self.cancel_button.configure(state="disabled")
            self._status.set("CANCELLING")
            self._log("Cancellation requested; waiting for the current operation to stop.")

    def _open_editor(self) -> None:
        if not self._can_edit():
            return
        if self._text_editor is not None and self._text_editor.winfo_exists():
            self._text_editor.lift()
            return
        self._text_editor = SubtitleCueEditor(
            self,
            self.source_cues,
            self.gemini_cues,
            self.translated_cues,
            on_saved=self._editor_saved,
            colors=getattr(self.winfo_toplevel(), "palette", {}),
        )

    def _close_editor(self) -> None:
        if self._text_editor is not None and self._text_editor.winfo_exists():
            self._text_editor._closing = True
            self._text_editor.destroy()
        self._text_editor = None

    def _editor_saved(self, cues: Sequence[TranslatedCue]) -> None:
        validate_cue_sequence(self.source_cues, cues)
        self.translated_cues = tuple(cues)
        self._refresh_preview()
        self._update_translation_buttons()

    def _can_edit(self) -> bool:
        return (
            bool(self.source_cues)
            and len(self.translated_cues) == len(self.source_cues)
            and len(self.gemini_cues) == len(self.source_cues)
            and any(cue.translation.strip() for cue in self.gemini_cues)
        )

    def _is_fully_translated(self) -> bool:
        return self._can_edit() and all(cue.translation.strip() for cue in self.translated_cues)

    def _update_translation_buttons(self) -> None:
        self.edit_button.configure(
            state="normal" if not self._busy and self._can_edit() else "disabled",
        )
        can_export_video = self.video_path is not None and self._is_fully_translated()
        self.export_button.configure(state="normal" if not self._busy and can_export_video else "disabled")

    def _open_output_folder(self) -> None:
        if self.output_video is None or not self.output_video.exists():
            return
        try:
            os.startfile(str(self.output_video.parent))
        except OSError as exc:
            messagebox.showerror("Subtitle Translator", f"Could not open output folder: {exc}")

    def _export(self) -> None:
        if not self._is_fully_translated() or self.video_path is None:
            messagebox.showinfo("Subtitle Translator", "Select a video and translate every segment before exporting.")
            return
        try:
            validate_cue_sequence(self.source_cues, self.translated_cues)
            destination = video_output_path(self.video_path, self._output_folder.get().strip())
            font_percent = int(self._font_percent.get())
            vertical_position = int(self._vertical_position.get())
            if not 3 <= font_percent <= 10:
                raise ValueError("Font size must be between 3 and 10.")
            if not 0 <= vertical_position <= 100:
                raise ValueError("Vertical position must be between 0 and 100.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Subtitle Translator", str(exc))
            return
        source = self.video_path
        source_cues = self.source_cues
        cues = self.translated_cues
        output_folder = self._output_folder.get().strip()
        self.settings["font_percent"] = font_percent
        self.settings["vertical_position"] = vertical_position
        self.settings["output_folder"] = output_folder
        try:
            self._save()
        except OSError as exc:
            messagebox.showerror("Subtitle Translator", f"Could not save settings: {exc}")
            return
        self.output_video = None
        self.open_folder_button.configure(state="disabled")
        self.stop_event.clear()
        self.progress["value"] = 0
        self._set_busy(True)
        self._status.set("EXPORTING VIDEO")

        def work() -> None:
            try:
                result = export_burned_subtitles(
                    self._tool("ffmpeg"),
                    self._tool("ffprobe"),
                    source,
                    source_cues,
                    cues,
                    destination,
                    font_percent=font_percent,
                    vertical_position=vertical_position,
                    stop_event=self.stop_event,
                    progress=lambda done, total, label: self.msgq.put(("progress", (done, total, label))),
                    log=self._log,
                )
                self.msgq.put(("video_exported", result))
            except InterruptedError as exc:
                self.msgq.put(("cancelled", str(exc)))
            except Exception as exc:
                self.msgq.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in (
            self.subtitle_file_button, self.video_button, self.export_video_source_button,
            self.env_button, self.output_button,
        ):
            button.configure(state=state)
        self.transcribe_button.configure(
            state=(
                "normal" if not busy and self.source_path is not None and self.source_kind == "video"
                else "disabled"
            ),
        )
        if busy or not self.tracks:
            self.track_combo.state(["disabled"])
        else:
            self.track_combo.state(["!disabled"])
        self.start_button.configure(state="disabled" if busy or not self.source_cues else "normal")
        self._update_translation_buttons()
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.load_track_button.configure(
            state="normal" if not busy and self.tracks and self._track_choice.get() else "disabled",
        )

    def _clear_preview(self) -> None:
        self.preview.delete(*self.preview.get_children())

    def _refresh_preview(self) -> None:
        self._clear_preview()
        translations = {item.source.index: item.translation for item in self.translated_cues}
        for cue in self.source_cues:
            timestamp = (
                f"{self._display_time(cue.start_ms)} → {self._display_time(cue.end_ms)}"
            )
            translation = translations.get(cue.index, "")
            edited = (
                cue.index <= len(self.gemini_cues)
                and translation != self.gemini_cues[cue.index - 1].translation
            )
            self.preview.insert(
                "", "end",
                values=(cue.index, timestamp, cue.text, translation),
                tags=("edited",) if edited else (),
            )

    @staticmethod
    def _display_time(milliseconds: int) -> str:
        hours, remaining = divmod(milliseconds, 3_600_000)
        minutes, remaining = divmod(remaining, 60_000)
        seconds, fraction = divmod(remaining, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{fraction:03d}"

    def _log(self, text: str) -> None:
        self.msgq.put(("log", text))

    def _pump(self) -> None:
        if self._closing:
            return
        try:
            while True:
                kind, payload = self.msgq.get_nowait()
                if kind == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", f"{payload}\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "progress":
                    done, total, label = payload
                    self.progress["value"] = 100.0 * done / max(1, total)
                    self._status.set(label.upper())
                elif kind == "tracks":
                    self.tracks = list(payload)
                    labels = [track.label for track in self.tracks]
                    self.track_combo.configure(values=labels)
                    if labels:
                        self._track_choice.set(labels[0])
                        self.track_combo.state(["!disabled"])
                        self._status.set(f"{len(labels)} TRACK(S) FOUND")
                    else:
                        self._track_choice.set("")
                        self._status.set("NO SUBTITLE TRACKS")
                        self._log("No embedded subtitle tracks were found in this video.")
                    self._set_busy(False)
                elif kind == "cues":
                    self.source_cues = tuple(payload)
                    self.translated_cues = ()
                    self.gemini_cues = ()
                    self._refresh_preview()
                    self._status.set(f"{len(self.source_cues)} CUES LOADED")
                    self._set_busy(False)
                elif kind == "transcribed":
                    self.source_cues, language = payload
                    self.translated_cues = ()
                    self.gemini_cues = ()
                    self._refresh_preview()
                    self._status.set(f"{len(self.source_cues)} SEGMENTS · {language.upper()}")
                    self._log(
                        f"Whisper detected source language: {language}; {len(self.source_cues)} timed speech segments."
                    )
                    self._set_busy(False)
                elif kind == "translation_ready":
                    translated = payload
                    self.translated_cues = tuple(translated)
                    self.gemini_cues = tuple(translated)
                    self._refresh_preview()
                    self.progress["value"] = 100
                    self._status.set("TRANSLATED")
                    self._set_busy(False)
                    self._update_translation_buttons()
                elif kind == "video_exported":
                    self.output_video = Path(payload)
                    self._status.set("VIDEO EXPORTED")
                    self._set_busy(False)
                    self.open_folder_button.configure(state="normal")
                    self._log(f"Exported video: {self.output_video}")
                    messagebox.showinfo(
                        "Subtitle Translator",
                        f"Video exported successfully:\n{self.output_video}",
                    )
                elif kind == "partial":
                    translated, error_message = payload
                    returned = {item.source.index: item for item in translated}
                    self.translated_cues = tuple(
                        returned.get(cue.index, TranslatedCue(cue, ""))
                        for cue in self.source_cues
                    )
                    self.gemini_cues = self.translated_cues
                    self._refresh_preview()
                    self._status.set(f"PARTIAL · {len(translated)}/{len(self.source_cues)} CUES")
                    self._set_busy(False)
                    self._log(f"ERROR: {error_message}")
                    self._log(
                        "Partial translations are available to edit. Video export is enabled only after every segment is translated."
                    )
                    messagebox.showwarning("Partial subtitle translation", str(error_message))
                elif kind == "cancelled":
                    self._status.set("CANCELLED")
                    self._set_busy(False)
                    self._log(str(payload))
                elif kind == "error":
                    self._status.set("ERROR")
                    self._set_busy(False)
                    self._log(f"ERROR: {payload}")
                    messagebox.showerror("Subtitle Translator", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._pump)

    def set_palette(self, palette: dict[str, str]) -> None:
        self.preview.tag_configure("edited", foreground=palette.get("accent", "#38BDF8"))

    def shutdown(self) -> None:
        self._closing = True
        self.stop_event.set()
        self._close_editor()
