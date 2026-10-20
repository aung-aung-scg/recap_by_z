"""Splitter tab: videos -> parts of N minutes (frame ratio + blurred background, text box, "Part 1" label).

The work itself is splitter.py; this file is only the window. It runs in the app's own process (a thread
plus ffmpeg), so it needs no worker script.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import splitter as sp
from core import OUTPUT_RATIOS, output_canvas, probe_video_size
from preview_tools import extract_preview_frame, probe_duration as preview_probe_duration

BG, PANEL, FIELD, BORDER = "#0d0f14", "#151922", "#0a0c10", "#303744"
FG, MUTED, SUCCESS = "#e7eaf0", "#9da7b6", "#55d187"
RATIOS = ("Original",) + tuple(r for r in OUTPUT_RATIOS if r != "Original")
FILL_LABELS = {"blur": "Blur background", "black": "Black bars", "crop": "Crop to fill"}
VIDEO_TYPES = [("Video", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All", "*.*")]
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
DEFAULTS: dict[str, Any] = {
    "minutes": 3.0, "smart_cut": True, "max_extra": 20.0, "ratio": "Original", "fill": "blur",
    "text": "", "text_size": 46, "text_pos": [0.5, 0.86], "text_opacity": 1.0, "text_box": True,
    "label_on": True, "label_template": "Part {n}", "label_size": 56, "label_pos": [0.5, 0.10],
    "label_opacity": 1.0, "label_box": True, "output_root": "",
}
CUT_WORDS = {"pause": "pause", "breath": "short pause", "quietest": "quietest", "exact": "exact", "end": "end"}


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class SplitterTab(ttk.Frame):
    def __init__(self, master: tk.Misc, *, cfg: dict, save: Callable[[], None], tool: Callable[[str], str],
                 logs_dir: Path) -> None:
        super().__init__(master, padding=(12, 8, 12, 8))
        self.cfg, self._save, self._tool, self.logs_dir = cfg, save, tool, logs_dir
        saved = {**DEFAULTS, **(cfg.get("splitter") or {})}
        self.files: list[Path] = []
        self.msgq: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.procs: list = []
        self.worker: threading.Thread | None = None
        self.source_size = (0, 0)
        self.duration = 0.0
        self.text_pos = list(saved["text_pos"])
        self.label_pos = list(saved["label_pos"])
        self._photo = None
        self._drag: str | None = None
        self._canvas_size = (640, 360)
        self._resize_job = None
        self._save_job = None

        self.minutes = tk.StringVar(value=f"{float(saved['minutes']):g}")
        self.smart_cut = tk.BooleanVar(value=bool(saved["smart_cut"]))
        self.max_extra = tk.StringVar(value=f"{float(saved['max_extra']):g}")
        self.ratio = tk.StringVar(value=saved["ratio"] if saved["ratio"] in RATIOS else "Original")
        self.fill = tk.StringVar(value=FILL_LABELS.get(saved["fill"], FILL_LABELS["blur"]))
        self.text = tk.StringVar(value=str(saved["text"]))
        self.text_size = tk.DoubleVar(value=float(saved["text_size"]))
        self.text_opacity = tk.DoubleVar(value=float(saved["text_opacity"]))
        self.text_box = tk.BooleanVar(value=bool(saved["text_box"]))
        self.label_on = tk.BooleanVar(value=bool(saved["label_on"]))
        self.label_template = tk.StringVar(value=str(saved["label_template"]))
        self.label_size = tk.DoubleVar(value=float(saved["label_size"]))
        self.label_opacity = tk.DoubleVar(value=float(saved["label_opacity"]))
        self.label_box = tk.BooleanVar(value=bool(saved["label_box"]))
        self.output_root = tk.StringVar(value=str(saved["output_root"]))
        self.preview_time = tk.DoubleVar(value=1.0)
        self.status = tk.StringVar(value="READY")
        self.stage = tk.StringVar(value="Add a video to start")

        self._build()
        for var in (self.minutes, self.smart_cut, self.max_extra, self.text, self.text_box, self.label_on,
                    self.label_template, self.label_box, self.output_root):
            var.trace_add("write", lambda *_a: self._changed())
        self.after(150, self._pump)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        style = ttk.Style(self)
        style.configure("TSpinbox", fieldbackground=FIELD, foreground=FG, background=PANEL, arrowcolor=FG,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, insertcolor=FG)
        style.configure("Split.Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, rowheight=22,
                        bordercolor=BORDER)
        style.configure("Split.Treeview.Heading", background=PANEL, foreground=FG)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tk.Label(header, text="Splitter", bg=BG, fg=FG, font=("Segoe UI Semibold", 15)).pack(side="left")
        tk.Label(header, text="Long video → parts of N minutes  |  Ratio + blur background  |  Text box  |  Part number",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(14, 0), pady=(5, 0))

        # ---------------- left: scrolling settings
        host = ttk.LabelFrame(self, text="Videos / Settings", padding=3)
        host.grid(row=1, column=0, sticky="nsw", padx=(0, 8))
        host.rowconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=BG, highlightthickness=0, width=430)
        canvas.grid(row=0, column=0, sticky="ns")
        bar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=bar.set)
        box = ttk.Frame(canvas, padding=(6, 4, 8, 4))
        window = canvas.create_window((0, 0), window=box, anchor="nw")
        box.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        box.columnconfigure(0, weight=1)

        def title(row: int, text: str) -> None:
            if row:
                ttk.Separator(box).grid(row=row - 1, column=0, sticky="ew", pady=(4, 8))
            ttk.Label(box, text=text, font=("Segoe UI Semibold", 10)).grid(row=row, column=0, sticky="w")

        def hint(row: int, text: str) -> None:
            ttk.Label(box, text=text, style="Muted.TLabel", wraplength=400, justify="left").grid(
                row=row, column=0, sticky="w", pady=(0, 4))

        def slider(row: int, label: str, var: tk.DoubleVar, lo: float, hi: float, fmt: Callable[[float], str]) -> None:
            frame = ttk.Frame(box)
            frame.grid(row=row, column=0, sticky="ew", pady=2)
            frame.columnconfigure(1, weight=1)
            ttk.Label(frame, text=label, width=9).grid(row=0, column=0, sticky="w")
            value = ttk.Label(frame, text=fmt(var.get()), width=6, anchor="e")

            def moved(v: str) -> None:
                value.configure(text=fmt(float(v)))
                self._redraw()

            scale = ttk.Scale(frame, from_=lo, to=hi, orient="horizontal", variable=var, command=moved)
            scale.grid(row=0, column=1, sticky="ew")
            scale.bind("<ButtonRelease-1>", lambda _e: self._changed())
            value.grid(row=0, column=2, padx=(8, 0))

        title(0, "Videos")
        files = ttk.Frame(box)
        files.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        files.columnconfigure(0, weight=1)
        self.file_list = tk.Listbox(files, height=6, bg=FIELD, fg=FG, selectbackground="#274d8b",
                                    highlightthickness=1, highlightbackground=BORDER, relief="flat",
                                    activestyle="none", exportselection=False)
        self.file_list.grid(row=0, column=0, sticky="ew")
        self.file_list.bind("<<ListboxSelect>>", lambda _e: self._load_selected())
        buttons = ttk.Frame(box)
        buttons.grid(row=2, column=0, sticky="w", pady=(4, 2))
        for text, command in (("+ Videos", self._add_files), ("+ Folder", self._add_folder),
                              ("Remove", self._remove_file), ("Clear", self._clear_files)):
            ttk.Button(buttons, text=text, style="Compact.TButton", command=command).pack(side="left", padx=(0, 6))
        out_row = ttk.Frame(box)
        out_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        out_row.columnconfigure(1, weight=1)
        ttk.Label(out_row, text="Save to", width=9).grid(row=0, column=0, sticky="w")
        ttk.Entry(out_row, textvariable=self.output_root).grid(row=0, column=1, sticky="ew")
        ttk.Button(out_row, text="Browse", style="Compact.TButton", command=self._browse_output).grid(
            row=0, column=2, padx=(6, 0))
        hint(4, "ဗလာထားရင် video ဘေးက <name>_parts folder ထဲ သိမ်းမယ်။")

        title(6, "Split")
        length = ttk.Frame(box)
        length.grid(row=7, column=0, sticky="w", pady=(4, 2))
        ttk.Label(length, text="Each part", width=9).pack(side="left")
        ttk.Spinbox(length, from_=0.5, to=60, increment=0.5, width=6, textvariable=self.minutes).pack(side="left")
        ttk.Label(length, text="min").pack(side="left", padx=(6, 0))
        smart = ttk.Frame(box)
        smart.grid(row=8, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(smart, text="Smart cut — wait up to", variable=self.smart_cut).pack(side="left")
        ttk.Spinbox(smart, from_=5, to=60, increment=5, width=4, textvariable=self.max_extra).pack(side="left", padx=4)
        ttk.Label(smart, text="s for a pause").pack(side="left")
        hint(9, "ဖွင့်ထားရင် — အချိန်ပြည့်ချိန် စကားမဆုံးသေးရင် စကားရပ်တဲ့ နေရာ (pause) ကို စောင့်ပြီး ဖြတ်မယ်။ "
                "ပိတ်ထားရင် — မိနစ်အတိ ဖြတ်မယ်။")
        check = ttk.Frame(box)
        check.grid(row=10, column=0, sticky="w", pady=(2, 0))
        ttk.Button(check, text="Check cuts", style="Compact.TButton", command=self._check_cuts).pack(side="left")
        ttk.Label(check, text="ရွေးထားတဲ့ video ဘယ်မှာ ဖြတ်မလဲ ကြည့်ရန်", style="Muted.TLabel").pack(side="left", padx=8)

        title(12, "Frame")
        frame_row = ttk.Frame(box)
        frame_row.grid(row=13, column=0, sticky="ew", pady=(4, 2))
        ttk.Label(frame_row, text="Ratio", width=9).pack(side="left")
        ratio = ttk.Combobox(frame_row, textvariable=self.ratio, values=RATIOS, state="readonly", width=9)
        ratio.pack(side="left")
        ttk.Label(frame_row, text="Fill").pack(side="left", padx=(10, 6))
        self.fill_combo = ttk.Combobox(frame_row, textvariable=self.fill, values=tuple(FILL_LABELS.values()),
                                       state="readonly", width=15)
        self.fill_combo.pack(side="left")
        for combo in (ratio, self.fill_combo):
            combo.bind("<<ComboboxSelected>>", lambda _e: self._frame_changed())
        hint(14, "Original = မူရင်းအတိုင်း။ 16:9 / 9:16 / 1:1 ဆိုရင် ကွက်လပ်ကို Fill အတိုင်း ဖြည့်မယ် (Blur = နောက်ခံ ဝါးမယ်)။")

        title(16, "Text Box")
        ttk.Entry(box, textvariable=self.text, font=("Myanmar Text", 10)).grid(row=17, column=0, sticky="ew", pady=(4, 2))
        slider(18, "Size", self.text_size, 20, 110, lambda v: str(int(v)))
        slider(19, "Opacity", self.text_opacity, 0.2, 1.0, lambda v: f"{v * 100:.0f}%")
        ttk.Checkbutton(box, text="Dark box behind the text", variable=self.text_box).grid(row=20, column=0, sticky="w")
        hint(21, "Preview ပေါ်မှာ ဆွဲရွှေ့လို့ရတယ်။")

        title(23, "Part Number")
        label_row = ttk.Frame(box)
        label_row.grid(row=24, column=0, sticky="ew", pady=(4, 2))
        label_row.columnconfigure(1, weight=1)
        ttk.Checkbutton(label_row, text="Show", variable=self.label_on).grid(row=0, column=0, sticky="w")
        ttk.Entry(label_row, textvariable=self.label_template, font=("Myanmar Text", 10)).grid(
            row=0, column=1, sticky="ew", padx=(8, 0))
        hint(25, "{n} = 1, 2, 3   ·   {mm} = ၁, ၂, ၃   ·   {total} = အပိုင်း စုစုပေါင်း ({mm} နဲ့ဆို မြန်မာဂဏန်း)\n"
                 "ဥပမာ  Part {n}/{total} → Part 2/5   ·   အပိုင်း {mm}/{total} → အပိုင်း ၂/၅")
        slider(26, "Size", self.label_size, 20, 120, lambda v: str(int(v)))
        slider(27, "Opacity", self.label_opacity, 0.2, 1.0, lambda v: f"{v * 100:.0f}%")
        ttk.Checkbutton(box, text="Dark box behind the number", variable=self.label_box).grid(row=28, column=0, sticky="w")

        self._wheel(box, canvas)

        # ---------------- right: preview + the planned parts
        right = ttk.Frame(self)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(2, weight=1)
        pv = ttk.LabelFrame(right, text="Preview — drag the text box / part number", padding=6)
        pv.grid(row=0, column=0, sticky="nsew")
        pv.columnconfigure(0, weight=1)
        pv.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(pv, bg="#05070a", highlightthickness=1, highlightbackground=BORDER, cursor="fleur")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: self._release())
        self.canvas.bind("<Configure>", self._resized)
        seek = ttk.Frame(pv)
        seek.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        seek.columnconfigure(0, weight=1)
        self.seek = ttk.Scale(seek, from_=0.0, to=1.0, orient="horizontal", variable=self.preview_time,
                              command=lambda _v: self._time_label())
        self.seek.grid(row=0, column=0, sticky="ew")
        self.seek.bind("<ButtonRelease-1>", lambda _e: self._refresh())
        self.time_label = ttk.Label(seek, text="00:00 / 00:00", style="Muted.TLabel", width=15)
        self.time_label.grid(row=0, column=1, padx=(8, 0))

        bottom = ttk.Frame(right)
        bottom.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)
        bottom.rowconfigure(0, weight=1)
        parts = ttk.LabelFrame(bottom, text="Parts (Check cuts / START)", padding=6)
        parts.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        parts.columnconfigure(0, weight=1)
        parts.rowconfigure(0, weight=1)
        log_frame = ttk.LabelFrame(bottom, text="Log", padding=6)
        log_frame.grid(row=0, column=1, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.logbox = tk.Text(log_frame, height=8, width=40, wrap="word", bg="#080a0e", fg="#d9dee8",
                              relief="flat", borderwidth=0, padx=6, pady=6, font=("Consolas", 9),
                              insertbackground=FG)
        self.logbox.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.logbox.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.logbox.configure(yscrollcommand=log_scroll.set)
        self.parts_view = ttk.Treeview(parts, columns=("start", "end", "length", "cut"), height=6,
                                       style="Split.Treeview")
        self.parts_view.heading("#0", text="Part")
        self.parts_view.column("#0", width=70, stretch=False)
        for col, text, width in (("start", "Start", 80), ("end", "End", 80), ("length", "Length", 80),
                                 ("cut", "Cut at", 100)):
            self.parts_view.heading(col, text=text)
            self.parts_view.column(col, width=width, anchor="center")
        self.parts_view.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(parts, orient="vertical", command=self.parts_view.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.parts_view.configure(yscrollcommand=scroll.set)

        controls = ttk.Frame(self)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        controls.columnconfigure(0, weight=1)
        btns = ttk.Frame(controls)
        btns.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.start_btn = ttk.Button(btns, text="START SPLIT", style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="STOP", style="Danger.TButton", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="Open Output Folder", command=self._open_output).pack(side="left")
        ttk.Label(btns, textvariable=self.stage, style="Muted.TLabel").pack(side="right", padx=(8, 0))
        ttk.Label(btns, textvariable=self.status, style="Status.TLabel").pack(side="right")
        self.progress = ttk.Progressbar(controls, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew")
        self._frame_changed(refresh=False)

    @staticmethod
    def _wheel(widget: tk.Misc, canvas: tk.Canvas) -> None:
        if not isinstance(widget, (ttk.Scale, ttk.Combobox, ttk.Spinbox, tk.Listbox, tk.Text)):
            widget.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"), add="+")
        for child in widget.winfo_children():
            SplitterTab._wheel(child, canvas)

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        def number(var: tk.StringVar, default: float, lo: float, hi: float) -> float:
            try:
                return max(lo, min(hi, float(str(var.get()).strip())))
            except ValueError:
                return default

        return {
            "minutes": number(self.minutes, 3.0, 0.25, 600.0),
            "smart_cut": bool(self.smart_cut.get()),
            "max_extra": number(self.max_extra, 20.0, 1.0, 120.0),
            "ratio": self.ratio.get(),
            "fill": next((k for k, v in FILL_LABELS.items() if v == self.fill.get()), "blur"),
            "text": self.text.get().strip(),
            "text_size": int(self.text_size.get()),
            "text_pos": [round(float(x), 4) for x in self.text_pos],
            "text_opacity": round(float(self.text_opacity.get()), 2),
            "text_box": bool(self.text_box.get()),
            "label_on": bool(self.label_on.get()),
            "label_template": self.label_template.get().strip() or "Part {n}",
            "label_size": int(self.label_size.get()),
            "label_pos": [round(float(x), 4) for x in self.label_pos],
            "label_opacity": round(float(self.label_opacity.get()), 2),
            "label_box": bool(self.label_box.get()),
            "output_root": self.output_root.get().strip(),
        }

    def _changed(self) -> None:
        self._redraw()
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(600, self._persist)

    def _persist(self) -> None:
        self._save_job = None
        self.cfg["splitter"] = self.settings()
        try:
            self._save()
        except Exception as exc:
            self._log(f"⚠️ Could not save the Splitter settings: {exc}")

    def _frame_changed(self, refresh: bool = True) -> None:
        self.fill_combo.configure(state="disabled" if self.ratio.get() == "Original" else "readonly")
        self._changed()
        if refresh:
            self._refresh()

    # ------------------------------------------------------------------ files
    def _add(self, paths: list[Path]) -> None:
        known = {str(p).casefold() for p in self.files}
        for p in paths:
            if p.is_file() and str(p).casefold() not in known:
                self.files.append(p)
                self.file_list.insert("end", p.name)
                known.add(str(p).casefold())
        if self.files and not self.file_list.curselection():
            self.file_list.selection_set(0)
            self._load_selected()
        self.stage.set(f"{len(self.files)} video(s)")

    def _add_files(self) -> None:
        self._add([Path(p) for p in filedialog.askopenfilenames(title="Select videos", filetypes=VIDEO_TYPES)])

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select a folder of videos")
        if folder:
            found = sorted((p for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_EXTS),
                           key=lambda p: p.name.casefold())
            if not found:
                messagebox.showinfo("Splitter", "ဒီ folder ထဲမှာ video ဖိုင် မတွေ့ပါ။")
            self._add(found)

    def _remove_file(self) -> None:
        sel = self.file_list.curselection()
        if sel:
            self.files.pop(sel[0])
            self.file_list.delete(sel[0])
            if self.files:
                self.file_list.selection_set(min(sel[0], len(self.files) - 1))
            self._load_selected()

    def _clear_files(self) -> None:
        self.files.clear()
        self.file_list.delete(0, "end")
        self._load_selected()

    def _browse_output(self) -> None:
        folder = filedialog.askdirectory(title="Save the parts in")
        if folder:
            self.output_root.set(folder)

    def _selected(self) -> Path | None:
        sel = self.file_list.curselection()
        return self.files[sel[0]] if sel and sel[0] < len(self.files) else None

    def _load_selected(self) -> None:
        self.parts_view.delete(*self.parts_view.get_children())
        src = self._selected()
        if src is None:
            self.duration, self.source_size, self._photo = 0.0, (0, 0), None
            self.canvas.delete("all")
            self._time_label()
            self._redraw()
            return
        try:
            ffprobe = self._tool("ffprobe")
            self.duration = preview_probe_duration(ffprobe, str(src))
            self.source_size = probe_video_size(ffprobe, src)
            self.seek.configure(to=max(0.1, self.duration))
            self.preview_time.set(min(5.0, self.duration / 3))
            self._log(f"🎬 {src.name}: {_clock(self.duration)}, {self.source_size[0]}x{self.source_size[1]}")
        except Exception as exc:
            self._log(f"⚠️ Cannot read {src.name}: {exc}")
        self._refresh()

    # ------------------------------------------------------------------ preview
    def _bounds(self) -> tuple[int, int, int, int]:
        cw, ch = self._canvas_size
        fw, fh = output_canvas(self.ratio.get(), *self.source_size)
        scale = min(cw / fw, ch / fh)
        w, h = max(16, int(fw * scale)) // 2 * 2, max(16, int(fh * scale)) // 2 * 2
        return (cw - w) // 2, (ch - h) // 2, w, h

    def _resized(self, event) -> None:
        size = (max(160, event.width - 2), max(90, event.height - 2))
        if size == self._canvas_size:
            return
        self._canvas_size = size
        self._redraw()
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(300, self._refresh)

    def _time_label(self) -> None:
        self.time_label.configure(text=f"{_clock(self.preview_time.get())} / {_clock(self.duration)}")

    def _refresh(self) -> None:
        self._resize_job = None
        src = self._selected()
        if src is None or not src.is_file():
            return
        try:
            ox, oy, w, h = self._bounds()
            out = self.logs_dir / "splitter_preview.png"
            extract_preview_frame(self._tool("ffmpeg"), str(src), float(self.preview_time.get()), 1.0, False,
                                  str(out), w, h, ratio=self.ratio.get(), fill=self.settings()["fill"],
                                  source_size=self.source_size)
            self._photo = tk.PhotoImage(file=str(out))
            self.canvas.delete("frame")
            self.canvas.create_image(ox, oy, image=self._photo, anchor="nw", tags=("frame",))
            self.canvas.tag_lower("frame")
            self._time_label()
            self._redraw()
        except Exception as exc:
            self._log(f"⚠️ Preview: {exc}")

    def _redraw(self) -> None:
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("overlay")
        ox, oy, w, h = self._bounds()
        if self._selected() is None:
            c.create_text(self._canvas_size[0] // 2, self._canvas_size[1] // 2, fill=MUTED,
                          font=("Segoe UI", 12), tags=("overlay",),
                          text="+ Videos  /  + Folder  —  video ထည့်ပါ")
            return
        frame_w = output_canvas(self.ratio.get(), *self.source_size)[0]
        items = []
        if self.text.get().strip():
            items.append(("text", self.text.get().strip(), self.text_pos, self.text_size.get(),
                          self.text_opacity.get(), self.text_box.get(), 0.86))
        if self.label_on.get():
            total = len(self.parts_view.get_children()) or 1
            items.append(("label", sp.part_label(self.label_template.get() or "Part {n}", 1, total), self.label_pos,
                          self.label_size.get(), self.label_opacity.get(), self.label_box.get(), 0.6))
        for kind, text, pos, size, opacity, boxed, width in items:
            x, y = ox + float(pos[0]) * w, oy + float(pos[1]) * h
            fs = max(7, int(float(size) * w / frame_w))
            shade = max(110, min(255, int(255 * float(opacity))))
            item = c.create_text(x, y, text=text, fill=f"#{shade:02x}{shade:02x}{shade:02x}", anchor="center",
                                 justify="center", font=("Myanmar Text", fs, "bold"), width=int(w * width),
                                 tags=("overlay", kind))
            x1, y1, x2, y2 = c.bbox(item)
            pad = max(4, fs // 3)
            if boxed:
                c.create_rectangle(x1 - pad, y1 - pad // 2, x2 + pad, y2 + pad // 2, fill="#000000",
                                   stipple="gray50", outline="", tags=("overlay", kind))
            c.create_rectangle(x1 - pad, y1 - pad // 2, x2 + pad, y2 + pad // 2, outline="#48d7ff", dash=(4, 3),
                               tags=("overlay", kind))
            c.tag_raise(item)

    def _press(self, event) -> None:
        self._drag = None
        for item in reversed(self.canvas.find_overlapping(event.x - 2, event.y - 2, event.x + 2, event.y + 2)):
            tags = self.canvas.gettags(item)
            if "text" in tags or "label" in tags:
                self._drag = "text" if "text" in tags else "label"
                break

    def _motion(self, event) -> None:
        if not self._drag:
            return
        ox, oy, w, h = self._bounds()
        pos = [min(0.98, max(0.02, (event.x - ox) / w)), min(0.98, max(0.02, (event.y - oy) / h))]
        if self._drag == "text":
            self.text_pos = pos
        else:
            self.label_pos = pos
        self._redraw()

    def _release(self) -> None:
        if self._drag:
            self._drag = None
            self._changed()

    # ------------------------------------------------------------------ run
    def _log(self, text: str) -> None:
        self.msgq.put(("log", text))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.msgq.get_nowait()
                if kind == "log":
                    self.logbox.insert("end", str(payload) + "\n")
                    self.logbox.see("end")
                elif kind == "progress":
                    value, label = payload
                    self.progress["value"] = max(0.0, min(100.0, value * 100.0))
                    self.status.set(label)
                elif kind == "parts":
                    self._show_parts(payload)
                elif kind == "stage":
                    self.stage.set(str(payload))
                elif kind == "done":
                    self._running(False)
                    self.status.set("DONE")
                    messagebox.showinfo("Splitter", str(payload))
                elif kind == "stopped":
                    self._running(False)
                    self.status.set("STOPPED")
                elif kind == "error":
                    self._running(False)
                    self.status.set("ERROR")
                    messagebox.showerror("Splitter", str(payload))
        except queue.Empty:
            pass
        self.after(150, self._pump)

    def _show_parts(self, parts: list[dict[str, Any]]) -> None:
        self.parts_view.delete(*self.parts_view.get_children())
        for p in parts:
            self.parts_view.insert("", "end", text=f"Part {p['n']}", values=(
                _clock(p["start"]), _clock(p["end"]), f"{(p['end'] - p['start']) / 60:.2f} min",
                CUT_WORDS.get(p["cut"], p["cut"])))
        self._redraw()

    def _running(self, yes: bool) -> None:
        self.start_btn.configure(state="disabled" if yes else "normal")
        self.stop_btn.configure(state="normal" if yes else "disabled")

    def _check_cuts(self) -> None:
        src = self._selected()
        if src is None:
            messagebox.showinfo("Splitter", "Video တစ်ခု အရင်ထည့်ပါ။")
            return
        settings = self.settings()
        self.status.set("CHECKING")

        def work() -> None:
            try:
                levels = sp.audio_levels(self._tool("ffmpeg"), src) if settings["smart_cut"] else None
                parts = sp.plan_parts(self.duration or sp.probe_duration(self._tool("ffprobe"), src),
                                      settings["minutes"] * 60.0, smart=settings["smart_cut"],
                                      max_extra=settings["max_extra"], levels=levels)
                self.msgq.put(("parts", parts))
                self.msgq.put(("progress", (0.0, f"{len(parts)} PARTS")))
            except Exception as exc:
                self.msgq.put(("progress", (0.0, "ERROR")))
                self._log(f"⚠️ Check cuts: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("Splitter", "Video တစ်ခု အရင်ထည့်ပါ (+ Videos / + Folder)။")
            return
        settings = self.settings()
        self.cfg["splitter"] = settings
        self._save()
        files = list(self.files)
        self.stop_event.clear()
        self._running(True)
        self.progress["value"] = 0
        ffmpeg, ffprobe = self._tool("ffmpeg"), self._tool("ffprobe")

        def work() -> None:
            made: list[Path] = []
            try:
                for i, src in enumerate(files):
                    self.msgq.put(("stage", f"Video {i + 1}/{len(files)}: {src.name}"))

                    def progress(value: float, label: str, i=i) -> None:
                        self.msgq.put(("progress", ((i + value) / len(files), label)))

                    made += sp.split_video(src, settings, ffmpeg=ffmpeg, ffprobe=ffprobe, log=self._log,
                                           progress=progress, stop=self.stop_event, procs=self.procs,
                                           on_plan=lambda parts: self.msgq.put(("parts", parts)))
                folder = sp.parts_folder(files[-1], settings["output_root"])
                self.msgq.put(("done", f"{len(made)} part(s) made.\n{folder}"))
            except InterruptedError:
                self._log("⏹️ Stopped — START again goes on from the part that was not finished.")
                self.msgq.put(("stopped", None))
            except Exception as exc:
                self._log(f"❌ {exc}")
                self.msgq.put(("error", str(exc)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        for proc in list(self.procs):
            try:
                proc.kill()
            except Exception:
                pass
        self.status.set("STOPPING")

    def shutdown(self) -> None:
        """The window is closing: stop a running split (ffmpeg would go on without us)."""
        if self.worker and self.worker.is_alive():
            self._stop()
        if self._save_job is not None:
            self._persist()

    def _open_output(self) -> None:
        src = self._selected() or (self.files[0] if self.files else None)
        if src is None:
            return
        folder = sp.parts_folder(src, self.output_root.get().strip())
        target = folder if folder.is_dir() else src.parent
        try:
            os.startfile(str(target))  # noqa: S606 - Windows tool
        except Exception as exc:
            messagebox.showinfo("Splitter", f"{target}\n\n{exc}")
