from __future__ import annotations

import os
import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Sequence

from PIL import Image, ImageTk

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
from subtitle_video_export import (
    export_burned_subtitles,
    render_subtitle_preview,
    validate_box_options,
    resolve_output_folder,
    video_output_path,
)


def fit_preview_size(
    frame_size: tuple[int, int],
    area_size: tuple[int, int],
) -> tuple[int, int]:
    frame_width, frame_height = frame_size
    area_width, area_height = area_size
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("Preview frame dimensions must be positive")
    if area_width <= 0 or area_height <= 0:
        return 1, 1
    scale = min(area_width / frame_width, area_height / frame_height)
    return max(1, round(frame_width * scale)), max(1, round(frame_height * scale))


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
        self._preview_busy = False
        self._preview_id = 0
        self._preview_temp: tempfile.TemporaryDirectory | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_image: Image.Image | None = None
        self._preview_dimensions = (0, 0)
        self._preview_display_rect = (0, 0, 0, 0)
        self._large_preview_window: tk.Toplevel | None = None
        self._large_preview_canvas: tk.Canvas | None = None
        self._large_preview_photo: ImageTk.PhotoImage | None = None
        self._drawing_blur = False
        self._blur_start: tuple[float, float] | None = None
        self._blur_rect_id: int | None = None
        self._blur_box: dict[str, float] | None = None
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
        self._output_folder_hint = tk.StringVar(value="")
        self._font_percent = tk.StringVar(value=str(self.settings.get("font_percent", 5)))
        self._vertical_position = tk.StringVar(value=str(self.settings.get("vertical_position", 86)))
        cover_styles = {
            "solid": "Solid",
            "blur": "Blur",
            "delogo": "Fill (delogo)",
            "none": "None",
        }
        self._hide_original_subtitles = tk.BooleanVar(
            value=self.settings.get("hide_original_subtitles", True),
        )
        self._cover_style = tk.StringVar(
            value=cover_styles.get(str(self.settings.get("cover_style", "solid")).casefold(), "Solid"),
        )
        self._min_box_height = tk.StringVar(value=str(self.settings.get("min_box_height_percent", 12)))
        self._box_padding = tk.StringVar(value=str(self.settings.get("box_padding_percent", 2)))
        self._preview_time_ms: int | None = None
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
        self.output_folder_entry = ttk.Entry(options, textvariable=self._output_folder)
        self.output_folder_entry.grid(row=1, column=1, sticky="ew", pady=3)
        self.output_folder_entry.bind("<FocusOut>", self._save_output_folder_setting, add="+")
        self.output_button = ttk.Button(
            options, text="Browse", style="Compact.TButton", command=self._choose_output_folder,
        )
        self.output_button.grid(row=1, column=2, padx=(6, 0), pady=3)
        self.open_output_folder_button = ttk.Button(
            options, text="Open", style="Compact.TButton", command=self._open_output_folder,
        )
        self.open_output_folder_button.grid(row=1, column=3, padx=(6, 0), pady=3)
        ttk.Label(options, textvariable=self._output_folder_hint).grid(
            row=2, column=1, columnspan=3, sticky="w", pady=(0, 3),
        )
        ttk.Label(options, text="Font size (% of short edge)").grid(
            row=3, column=0, sticky="w", padx=(0, 6), pady=3,
        )
        ttk.Spinbox(options, textvariable=self._font_percent, from_=3, to=10, width=5).grid(
            row=3, column=1, sticky="w", pady=3,
        )
        ttk.Label(options, text="Cover / text position (% from top)").grid(
            row=3, column=2, sticky="w", padx=(12, 6), pady=3,
        )
        ttk.Spinbox(options, textvariable=self._vertical_position, from_=0, to=100, width=5).grid(
            row=3, column=3, sticky="w", pady=3,
        )
        ttk.Checkbutton(
            options, text="Hide original subtitles for the whole video",
            variable=self._hide_original_subtitles, command=self._refresh_selected_preview,
        ).grid(row=4, column=0, sticky="w", pady=3)
        ttk.Label(options, text="Cover style").grid(row=4, column=1, sticky="e", padx=(6, 4))
        self.cover_style_combo = ttk.Combobox(
            options, textvariable=self._cover_style, state="readonly",
            values=("Solid", "Blur", "Fill (delogo)", "None"), width=16,
        )
        self.cover_style_combo.grid(row=4, column=2, sticky="w", pady=3)
        self.cover_style_combo.bind("<<ComboboxSelected>>", self._refresh_selected_preview)
        ttk.Label(options, text="Cover height (% frame)").grid(row=4, column=3, sticky="e", padx=(8, 4))
        ttk.Spinbox(
            options, textvariable=self._min_box_height, from_=5, to=35, width=5,
            command=self._refresh_selected_preview,
        ).grid(row=4, column=4, sticky="w", pady=3)
        ttk.Label(options, text="Box padding (% height)").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Spinbox(
            options, textvariable=self._box_padding, from_=0, to=10, width=5,
            command=self._refresh_selected_preview,
        ).grid(row=5, column=1, sticky="w", pady=3)
        self.draw_blur_button = ttk.Button(
            options, text="Draw cover area", style="Compact.TButton", command=self._toggle_blur_drawing,
        )
        self.draw_blur_button.grid(row=5, column=2, sticky="w", padx=(8, 0), pady=3)
        self._vertical_position.trace_add("write", lambda *_args: self._refresh_selected_preview())
        self._min_box_height.trace_add("write", lambda *_args: self._refresh_selected_preview())
        self._output_folder.trace_add("write", lambda *_args: self._update_output_folder_hint())
        self._update_output_folder_hint()

        preview_box = ttk.LabelFrame(self, text="PREVIEW · ORIGINAL TEXT IS KEPT SEPARATE", style="Card.TLabelframe")
        preview_box.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
        preview_box.rowconfigure(0, weight=1)
        preview_box.columnconfigure(0, weight=2)
        preview_box.columnconfigure(3, weight=3)
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
        ttk.Separator(preview_box, orient="vertical").grid(row=0, column=2, rowspan=2, sticky="ns", padx=8)
        frame_preview = ttk.Frame(preview_box)
        frame_preview.grid(row=0, column=3, rowspan=2, sticky="nsew", padx=(0, 8))
        frame_preview.columnconfigure(0, weight=1)
        frame_preview.rowconfigure(1, weight=1)
        ttk.Label(frame_preview, text="Selected cue output preview").grid(
            row=0, column=0, sticky="w", pady=(0, 4),
        )
        self.frame_canvas = tk.Canvas(
            frame_preview, background="#101820",
            highlightthickness=1, highlightbackground="#64748B",
        )
        self.frame_canvas.grid(row=1, column=0, sticky="nsew")
        blur_controls = ttk.Frame(frame_preview)
        blur_controls.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.preview_gap_button = ttk.Button(
            blur_controls, text="Preview between cues", style="Compact.TButton",
            command=self._preview_between_cues,
        )
        self.preview_gap_button.pack(side="left")
        self.refresh_preview_button = ttk.Button(
            blur_controls, text="Refresh preview", style="Compact.TButton",
            command=self._refresh_selected_preview,
        )
        self.refresh_preview_button.pack(side="left", padx=(6, 0))
        self.frame_canvas.bind("<ButtonPress-1>", self._blur_draw_start)
        self.frame_canvas.bind("<B1-Motion>", self._blur_draw_drag)
        self.frame_canvas.bind("<ButtonRelease-1>", self._blur_draw_end)
        self.frame_canvas.bind("<Configure>", self._preview_canvas_resized)
        self.frame_canvas.bind("<Double-Button-1>", self._open_large_preview)
        self.preview.bind("<<TreeviewSelect>>", self._preview_selection_changed)

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
            footer, text="Open folder", command=self._open_output_video_folder, state="disabled",
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
        self._update_output_folder_hint()
        self._blur_box = None
        self.output_video = None
        self.open_folder_button.configure(state="disabled")
        self._update_translation_buttons()
        self._refresh_selected_preview()

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
            self._update_output_folder_hint()
            self._blur_box = None
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
            try:
                source = self.video_path or self.source_path or (Path.cwd() / "subtitle-video.mp4")
                folder = resolve_output_folder(source, selected)
                self._output_folder.set(str(folder))
                self._persist_output_folder()
            except OSError as exc:
                messagebox.showerror("Subtitle Translator", str(exc))

    def _update_output_folder_hint(self) -> None:
        selected = self._output_folder.get().strip()
        source = self.video_path or (
            self.source_path if self.source_kind == "video" else None
        )
        if selected:
            folder = Path(selected).expanduser().resolve()
        elif source is not None:
            folder = source.resolve().parent
        else:
            self._output_folder_hint.set("Folder to be used: select a video or enter an output folder")
            return
        self._output_folder_hint.set(f"Folder to be used: {folder}")

    def _persist_output_folder(self) -> None:
        self.settings["output_folder"] = self._output_folder.get().strip()
        try:
            self._save()
        except OSError as exc:
            messagebox.showerror("Subtitle Translator", f"Could not save output-folder setting: {exc}")

    def _save_output_folder_setting(self, _event=None) -> None:
        folder_text = self._output_folder.get().strip()
        if folder_text:
            source = self.video_path or self.source_path or (Path.cwd() / "subtitle-video.mp4")
            try:
                resolved = resolve_output_folder(source, folder_text)
            except OSError as exc:
                messagebox.showerror("Subtitle Translator", str(exc))
                return
            self._output_folder.set(str(resolved))
        self._persist_output_folder()

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
        source = self.video_path or (
            self.source_path if self.source_kind == "video" else None
        )
        folder_text = self._output_folder.get().strip()
        if source is None and not folder_text:
            messagebox.showinfo("Subtitle Translator", "Select a video or set an output folder first.")
            return
        try:
            folder = resolve_output_folder(
                source or (Path.cwd() / "subtitle-video.mp4"),
                folder_text,
            )
            os.startfile(str(folder))
        except OSError as exc:
            messagebox.showerror("Subtitle Translator", f"Could not open output folder: {exc}")

    def _open_output_video_folder(self) -> None:
        if self.output_video is None or not self.output_video.exists():
            return
        try:
            os.startfile("explorer.exe", "open", f'/select,"{self.output_video}"')
        except OSError:
            try:
                os.startfile(str(self.output_video.parent))
            except OSError as exc:
                messagebox.showerror(
                    "Subtitle Translator",
                    f"Could not open output folder:\n{self.output_video.parent}\n\n{exc}",
                )

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
            _opacity, min_box_height, box_padding = validate_box_options(
                100, int(self._min_box_height.get()), int(self._box_padding.get()),
            )
            cover_style = self._selected_cover_style()
            if cover_style is None:
                raise ValueError("Choose Solid, Blur, Fill (delogo), or None as the cover style.")
            hide_original_subtitles = self._hide_original_subtitles.get()
            if hide_original_subtitles and cover_style in {"blur", "delogo"} and self._blur_box is None:
                raise ValueError(f"Draw a cover area before using the {cover_style} cover style.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Subtitle Translator", str(exc))
            return
        source = self.video_path
        source_cues = self.source_cues
        cues = self.translated_cues
        blur_box = self._blur_box.copy() if self._blur_box else None
        output_folder = self._output_folder.get().strip()
        self.settings["font_percent"] = font_percent
        self.settings["vertical_position"] = vertical_position
        self.settings["hide_original_subtitles"] = hide_original_subtitles
        self.settings["cover_style"] = cover_style
        self.settings["min_box_height_percent"] = min_box_height
        self.settings["box_padding_percent"] = box_padding
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
                    cover_original=hide_original_subtitles,
                    cover_style=cover_style,
                    background_opacity=100,
                    min_box_height_percent=min_box_height,
                    box_padding_percent=box_padding,
                    blur_box=blur_box if cover_style in {"blur", "delogo"} else None,
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
            self.env_button, self.output_button, self.open_output_folder_button,
            self.output_folder_entry,
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
        self._preview_id += 1
        self.frame_canvas.delete("all")
        self._preview_photo = None
        self._preview_image = None
        self._preview_dimensions = (0, 0)
        self._preview_display_rect = (0, 0, 0, 0)
        self._close_large_preview()
        if self._preview_temp is not None and not self._preview_busy:
            self._preview_temp.cleanup()
            self._preview_temp = None

    def _preview_canvas_resized(self, _event=None) -> None:
        self._render_preview_to_canvas(self.frame_canvas)

    def _render_preview_to_canvas(self, canvas: tk.Canvas, *, large: bool = False) -> None:
        image = self._preview_image
        if image is None or not canvas.winfo_exists():
            return
        area_width = canvas.winfo_width()
        area_height = canvas.winfo_height()
        display_width, display_height = fit_preview_size(
            image.size, (area_width, area_height),
        )
        scaled = image.resize(
            (display_width, display_height),
            Image.Resampling.LANCZOS,
        )
        photo = ImageTk.PhotoImage(scaled, master=canvas)
        canvas.delete("all")
        x = (area_width - display_width) // 2
        y = (area_height - display_height) // 2
        canvas.create_image(x, y, image=photo, anchor="nw")
        if large:
            self._large_preview_photo = photo
            return
        self._preview_photo = photo
        self._preview_display_rect = (x, y, display_width, display_height)
        self._draw_blur_box_on_preview()

    def _draw_blur_box_on_preview(self) -> None:
        if not self._blur_box or self._preview_dimensions == (0, 0):
            self._blur_rect_id = None
            return
        x, y, width, height = self._preview_display_rect
        if width < 1 or height < 1:
            self._blur_rect_id = None
            return
        left = x + self._blur_box["x"] * width
        top = y + self._blur_box["y"] * height
        right = left + self._blur_box["w"] * width
        bottom = top + self._blur_box["h"] * height
        self._blur_rect_id = self.frame_canvas.create_rectangle(
            left, top, right, bottom,
            outline="#38BDF8", width=2, dash=(5, 3),
        )

    def _open_large_preview(self, _event=None) -> None:
        if self._preview_image is None:
            return
        if self._large_preview_window is not None and self._large_preview_window.winfo_exists():
            self._large_preview_window.lift()
            return
        window = tk.Toplevel(self)
        self._large_preview_window = window
        window.title("Subtitle preview")
        screen_width, screen_height = window.winfo_screenwidth(), window.winfo_screenheight()
        window.geometry(f"{max(320, int(screen_width * 0.85))}x{max(240, int(screen_height * 0.85))}")
        window.minsize(240, 180)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        canvas = tk.Canvas(window, background="#101820", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        self._large_preview_canvas = canvas
        canvas.bind("<Configure>", lambda _event: self._render_preview_to_canvas(canvas, large=True))
        window.bind("<Escape>", lambda _event: self._close_large_preview())
        window.protocol("WM_DELETE_WINDOW", self._close_large_preview)
        window.focus_set()
        self._render_preview_to_canvas(canvas, large=True)

    def _close_large_preview(self) -> None:
        window = self._large_preview_window
        self._large_preview_window = None
        self._large_preview_canvas = None
        self._large_preview_photo = None
        if window is not None and window.winfo_exists():
            window.destroy()

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
        self._refresh_selected_preview()

    def _selected_translation(self) -> TranslatedCue | None:
        if not self.translated_cues or self.video_path is None:
            return None
        selected = self.preview.selection()
        cue_index = None
        if selected:
            values = self.preview.item(selected[0], "values")
            if values:
                try:
                    cue_index = int(values[0])
                except (TypeError, ValueError):
                    cue_index = None
        if cue_index is not None:
            cue = next(
                (item for item in self.translated_cues
                 if item.source.index == cue_index and item.translation.strip()),
                None,
            )
            if cue is not None:
                return cue
        return next((item for item in self.translated_cues if item.translation.strip()), None)

    def _refresh_selected_preview(self, _event=None) -> None:
        cue = self._selected_translation()
        if self.video_path is None or self._preview_busy or self._busy:
            return
        try:
            font_percent = int(self._font_percent.get())
            vertical_position = int(self._vertical_position.get())
            _opacity, min_box_height, padding = validate_box_options(
                100,
                int(self._min_box_height.get()),
                int(self._box_padding.get()),
            )
        except ValueError:
            return
        cover_style = self._selected_cover_style()
        if cover_style is None:
            return
        blur_box = self._blur_box if cover_style in {"blur", "delogo"} else None
        if self._preview_temp is not None:
            self._preview_temp.cleanup()
        preview_temp = tempfile.TemporaryDirectory(prefix="subtitle-preview-")
        self._preview_temp = preview_temp
        destination = Path(preview_temp.name) / "subtitle-preview.png"
        self._preview_busy = True
        self._preview_id += 1
        request_id = self._preview_id
        source = self.video_path
        show_cue = cue if self._preview_time_ms is None else None
        options = (
            font_percent, vertical_position, self._hide_original_subtitles.get(),
            min_box_height, padding, blur_box, cover_style, self._preview_time_ms,
        )

        def work() -> None:
            try:
                preview = render_subtitle_preview(
                    self._tool("ffmpeg"), self._tool("ffprobe"), source, show_cue, destination,
                    font_percent=options[0],
                    vertical_position=options[1],
                    cover_original=options[2],
                    background_opacity=100,
                    min_box_height_percent=options[3],
                    box_padding_percent=options[4],
                    blur_box=options[5],
                    cover_style=options[6],
                    timestamp_ms=options[7],
                )
                if self._closing or request_id != self._preview_id:
                    preview_temp.cleanup()
                    return
                self.msgq.put(("subtitle_preview_ready", (request_id, preview_temp, preview)))
            except Exception as exc:
                self.msgq.put(("subtitle_preview_error", (request_id, preview_temp, str(exc))))

        threading.Thread(target=work, daemon=True).start()

    def _selected_cover_style(self) -> str | None:
        return {
            "solid": "solid",
            "blur": "blur",
            "fill (delogo)": "delogo",
            "none": "none",
        }.get(self._cover_style.get().strip().casefold())

    def _preview_selection_changed(self, _event=None) -> None:
        self._preview_time_ms = None
        self._refresh_selected_preview()

    def _preview_between_cues(self) -> None:
        ordered = sorted(self.source_cues, key=lambda item: item.start_ms)
        selected_index = None
        selected = self.preview.selection()
        if selected:
            values = self.preview.item(selected[0], "values")
            if values:
                try:
                    selected_index = int(values[0])
                except (TypeError, ValueError):
                    pass
        gaps = [
            (left.end_ms, right.start_ms)
            for left, right in zip(ordered, ordered[1:])
            if right.start_ms > left.end_ms
        ]
        if selected_index is not None:
            selected_cue = next((cue for cue in ordered if cue.index == selected_index), None)
            following = (
                next((cue for cue in ordered if cue.start_ms >= selected_cue.end_ms), None)
                if selected_cue else None
            )
            if selected_cue is not None and following and following.start_ms > selected_cue.end_ms:
                gap = (selected_cue.end_ms, following.start_ms)
            else:
                gap = gaps[0] if gaps else None
        else:
            gap = gaps[0] if gaps else None
        if gap is None:
            messagebox.showinfo("Subtitle preview", "There is no gap between subtitle cues to preview.")
            return
        self._preview_time_ms = (gap[0] + gap[1]) // 2
        self._refresh_selected_preview()

    def _toggle_blur_drawing(self) -> None:
        self._drawing_blur = not self._drawing_blur
        self.draw_blur_button.configure(
            text="Finish cover area" if self._drawing_blur else "Draw cover area",
        )
        self.frame_canvas.configure(
            cursor="crosshair" if self._drawing_blur else "",
        )

    def _blur_draw_start(self, event) -> None:
        if not self._drawing_blur:
            return
        x, y, width, height = self._preview_display_rect
        if not (x <= event.x <= x + width and y <= event.y <= y + height):
            return
        self._blur_start = (event.x, event.y)
        if self._blur_rect_id is not None:
            self.frame_canvas.delete(self._blur_rect_id)
        self._blur_rect_id = self.frame_canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#38BDF8", width=2, dash=(5, 3),
        )

    def _blur_draw_drag(self, event) -> None:
        if self._drawing_blur and self._blur_start and self._blur_rect_id is not None:
            x, y, width, height = self._preview_display_rect
            event_x = max(x, min(x + width, event.x))
            event_y = max(y, min(y + height, event.y))
            self.frame_canvas.coords(
                self._blur_rect_id, self._blur_start[0], self._blur_start[1], event_x, event_y,
            )

    def _blur_draw_end(self, event) -> None:
        if not self._drawing_blur or self._blur_start is None:
            return
        display_x, display_y, display_width, display_height = self._preview_display_rect
        frame_width, frame_height = self._preview_dimensions
        if display_width < 1 or display_height < 1 or frame_width < 1 or frame_height < 1:
            self._blur_start = None
            return
        x0, y0 = self._blur_start
        x1 = max(display_x, min(display_x + display_width, event.x))
        y1 = max(display_y, min(display_y + display_height, event.y))
        self._blur_start = None
        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            return
        x0 = max(display_x, min(display_x + display_width, x0))
        y0 = max(display_y, min(display_y + display_height, y0))
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left < 4 or bottom - top < 4:
            return
        self._blur_box = {
            "x": (left - display_x) / display_width,
            "y": (top - display_y) / display_height,
            "w": (right - left) / display_width,
            "h": (bottom - top) / display_height,
        }
        self._drawing_blur = False
        self.draw_blur_button.configure(text="Draw cover area")
        self.frame_canvas.configure(cursor="")
        self._render_preview_to_canvas(self.frame_canvas)
        self._refresh_selected_preview()

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
                    self._refresh_selected_preview()
                elif kind == "cues":
                    self.source_cues = tuple(payload)
                    self.translated_cues = ()
                    self.gemini_cues = ()
                    self._refresh_preview()
                    self._status.set(f"{len(self.source_cues)} CUES LOADED")
                    self._set_busy(False)
                    self._refresh_selected_preview()
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
                    self._refresh_selected_preview()
                elif kind == "translation_ready":
                    translated = payload
                    self.translated_cues = tuple(translated)
                    self.gemini_cues = tuple(translated)
                    self._refresh_preview()
                    self.progress["value"] = 100
                    self._status.set("TRANSLATED")
                    self._set_busy(False)
                    self._update_translation_buttons()
                    self._refresh_selected_preview()
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
                elif kind == "subtitle_preview_ready":
                    request_id, preview_temp, preview_path = payload
                    self._preview_busy = False
                    if request_id != self._preview_id or self._closing:
                        preview_temp.cleanup()
                        continue
                    self._preview_temp = preview_temp
                    with Image.open(preview_path) as rendered:
                        self._preview_image = rendered.convert("RGB").copy()
                    self._preview_dimensions = self._preview_image.size
                    self._render_preview_to_canvas(self.frame_canvas)
                    if (
                        self._large_preview_canvas is not None
                        and self._large_preview_canvas.winfo_exists()
                    ):
                        self._render_preview_to_canvas(self._large_preview_canvas, large=True)
                elif kind == "subtitle_preview_error":
                    request_id, preview_temp, error_message = payload
                    self._preview_busy = False
                    preview_temp.cleanup()
                    if request_id == self._preview_id and not self._closing:
                        self._log(f"Preview error: {error_message}")
                        self._status.set("PREVIEW ERROR")
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
                    self._refresh_selected_preview()
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
        self._preview_id += 1
        self.stop_event.set()
        self._close_editor()
        self._close_large_preview()
        if self._preview_temp is not None and not self._preview_busy:
            self._preview_temp.cleanup()
            self._preview_temp = None
