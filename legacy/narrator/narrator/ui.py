"""The tkinter application: window, dialogs, and all user interaction.

Only this module imports tkinter, which is what lets the worker run
in an environment that has no Tk installed.
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

from .config import *
# Underscore-prefixed helpers are skipped by import *, so the
# few the UI genuinely needs are named explicitly.
from .config import _no_window
from .documents import _have
from .documents import *
from .pronunciation import *
from .pronunciation import words_in
from .audio import *
from .engines import *
from .pipeline import *
from .segments import (write_manifest, export_span, build_manifest,
                       load_manifest)
from . import publish
from . import chapters as chapters_mod
from . import library
from . import transcribe as transcribe_mod
from . import audiogram as audiogram_mod
from . import ffgram as ffgram_mod
from . import components as components_mod
from . import expressions as expressions_mod
from . import session as session_mod
from . import render_config
from . import tasks as tasks_mod


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def launch():
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.withdraw()  # hidden until the wizard (if any) has run, so the
                     # person doesn't see a mostly-empty main window flash
                     # up behind it

    settings = load_settings()
    available = [name for name, spec in ENGINES.items() if spec["detect"]()]

    from . import wizard
    if not settings.get("wizard_shown") and wizard.needs_wizard():
        wizard.run_wizard(root)
        settings["wizard_shown"] = True
        save_settings(settings)
        available = [name for name, spec in ENGINES.items()
                    if spec["detect"]()]

    if not available:
        # Nothing usable yet (the wizard was skipped, or a previous launch
        # never got as far as showing it). Offer it again rather than
        # quitting with instructions to type into a terminal.
        if messagebox.askyesno(
                "No engine installed",
                "None of the narration engines are installed yet.\n\n"
                "Open the setup wizard now? Ticking edge-tts there is enough "
                "to start narrating (about 10 MB, needs internet); Kokoro "
                "and Qwen3-TTS are the offline engines.",
                parent=root):
            wizard.run_wizard(root)
            settings["wizard_shown"] = True
            save_settings(settings)
            forget_engine_probes()
            available = [name for name, spec in ENGINES.items()
                         if spec["detect"]()]

    root.deiconify()
    root.title("Narrator")
    root.geometry("860x780")
    root.minsize(680, 560)

    if not available:
        messagebox.showerror(
            "No engine installed",
            "Still no narration engine available. Reopen the app to try the "
            "wizard again, or in a terminal run:\n\n"
            "    pip install edge-tts\n\n"
            "then start Narrator again.")
        root.destroy()
        return

    settings = load_settings()
    root_dir = settings.get("output_root") or default_output_root()
    if not os.path.isdir(root_dir):
        root_dir = default_output_root()

    state = {"path": None, "running": False, "cancel": False,
             "root": root_dir, "session": session_mod.Session()}
    msgs = queue.Queue()

    outer = ttk.Frame(root, padding=14)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="Narrator",
              font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
    ttk.Label(outer,
              text="All output is kept in one folder, one subfolder per "
                   "document. Every run is saved under its own name, so "
                   "comparing voices never overwrites anything.",
              foreground="#555", wraplength=700).pack(anchor="w", pady=(0, 10))

    # --- file ---
    menubar = tk.Menu(root, tearoff=False)
    root.config(menu=menubar)

    def _scrollable_tab(nb, title):
        """A notebook tab whose content scrolls vertically once it doesn't
        fit, rather than the window having to keep growing every time a
        tab gains more content (which is what happened twice already:
        once at the redesign, once when Chapters was added to Publish).
        Returns the inner, padded frame -- used by every caller exactly
        like a plain ttk.Frame(notebook, padding=10) was before; nothing
        about how each tab's own widgets get built has to change."""
        outer_f = ttk.Frame(nb)
        nb.add(outer_f, text=title)
        canvas = tk.Canvas(outer_f, highlightthickness=0)
        vsb = ttk.Scrollbar(outer_f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner = ttk.Frame(canvas, padding=10)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                  lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                   lambda e: canvas.itemconfigure(window_id, width=e.width))

        def wheel(event):
            # Windows/Mac deliver <MouseWheel> with event.delta; Linux
            # delivers <Button-4>/<Button-5> instead, with no delta.
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        # Bound only while the pointer is actually over this tab's canvas,
        # so scrolling doesn't get hijacked by whichever tab was built
        # first -- and harmless that all four do this, since only one
        # tab's canvas can ever be the one under the mouse at a time.
        canvas.bind("<Enter>", lambda _e: (
            canvas.bind_all("<MouseWheel>", wheel),
            canvas.bind_all("<Button-4>", wheel),
            canvas.bind_all("<Button-5>", wheel)))
        canvas.bind("<Leave>", lambda _e: (
            canvas.unbind_all("<MouseWheel>"),
            canvas.unbind_all("<Button-4>"),
            canvas.unbind_all("<Button-5>")))
        return inner

    notebook = ttk.Notebook(outer)
    notebook.pack(fill="both", expand=True, pady=(2, 8))
    doc_tab = _scrollable_tab(notebook, "Document")
    voice_tab = _scrollable_tab(notebook, "Voice")
    output_tab = _scrollable_tab(notebook, "Output")
    publish_tab = _scrollable_tab(notebook, "Publish")

    ttk.Label(publish_tab,
             text="Publish your most recent take to the podcast RSS feed, "
                  "or export a transcript of the current document. YouTube "
                  "chapters and embedded audio chapter markers are next.",
             foreground="#666", wraplength=560, justify="left").pack(
        anchor="w")

    take_row = ttk.Frame(publish_tab)
    take_row.pack(fill="x", pady=(10, 0))
    ttk.Label(take_row, text="Take to publish").pack(side="left")
    take_pick_var = tk.StringVar()
    take_pick_menu = ttk.Combobox(take_row, textvariable=take_pick_var,
                                  state="readonly", width=52)
    take_pick_menu.pack(side="left", padx=8)

    pub_status = ttk.Label(publish_tab, text="", wraplength=560,
                           justify="left")
    pub_status.pack(anchor="w", pady=(10, 0))

    pubform = ttk.Frame(publish_tab)
    pubform.pack(fill="x", pady=(8, 0))
    pubform.columnconfigure(1, weight=1)
    ttk.Label(pubform, text="Episode title").grid(
        row=0, column=0, sticky="w", pady=3)
    pub_title_var = tk.StringVar()
    ttk.Entry(pubform, textvariable=pub_title_var).grid(
        row=0, column=1, sticky="ew", padx=8, pady=3)
    ttk.Label(pubform, text="Episode notes").grid(
        row=1, column=0, sticky="nw", pady=3)
    pub_desc_box = scrolledtext.ScrolledText(pubform, height=4, wrap="word",
                                             font=("TkDefaultFont", 9))
    pub_desc_box.grid(row=1, column=1, sticky="ew", padx=8, pady=3)

    pub_btn_row = ttk.Frame(publish_tab)
    pub_btn_row.pack(fill="x", pady=(8, 0))
    publish_btn = ttk.Button(pub_btn_row,
                             text="Publish this take to the RSS feed",
                             state="disabled")
    publish_btn.pack(side="left")
    transcript_btn = ttk.Button(pub_btn_row, text="Export transcript (.md)")
    transcript_btn.pack(side="left", padx=(8, 0))

    ttk.Separator(publish_tab, orient="horizontal").pack(fill="x", pady=14)
    feed_status = ttk.Label(publish_tab, text="", foreground="#666",
                            wraplength=560, justify="left")
    feed_status.pack(anchor="w")

    ttk.Separator(publish_tab, orient="horizontal").pack(fill="x", pady=14)
    ttk.Label(publish_tab, text="Chapters", font=("TkDefaultFont", 10, "bold")
             ).pack(anchor="w")
    ttk.Label(publish_tab,
             text="Found from this document's own headings, matched "
                  "against the take's timing. Paste the text below into "
                  "a YouTube description, and/or embed it directly into "
                  "the audio file (mp3, m4a).",
             foreground="#666", wraplength=560, justify="left").pack(
        anchor="w", pady=(2, 8))
    chapters_box = scrolledtext.ScrolledText(publish_tab, height=5,
                                             wrap="word",
                                             font=("TkFixedFont", 9))
    chapters_box.pack(fill="x")
    chap_btn_row = ttk.Frame(publish_tab)
    chap_btn_row.pack(fill="x", pady=(6, 0))
    gen_chapters_btn = ttk.Button(chap_btn_row, text="Generate chapter list")
    gen_chapters_btn.pack(side="left")
    embed_chapters_btn = ttk.Button(chap_btn_row,
                                    text="Embed chapters into audio file")
    embed_chapters_btn.pack(side="left", padx=(8, 0))

    libbox = ttk.LabelFrame(doc_tab, text="Library", padding=10)
    libbox.pack(fill="x", pady=4)
    ttk.Label(libbox,
             text="Documents worked on before, with the settings last "
                  "used for each. Picking a new file below adds it here "
                  "automatically.",
             foreground="#666", wraplength=560, justify="left").pack(
        anchor="w", pady=(0, 6))
    lib_list = tk.Listbox(libbox, height=5, exportselection=False,
                          selectmode="extended")
    lib_list.pack(fill="x")
    lib_btn_row = ttk.Frame(libbox)
    lib_btn_row.pack(fill="x", pady=(6, 0))
    lib_load_btn = ttk.Button(lib_btn_row, text="Load selected")
    lib_load_btn.pack(side="left")
    lib_remove_btn = ttk.Button(lib_btn_row, text="Remove from library")
    lib_remove_btn.pack(side="left", padx=(8, 0))
    queue_btn = ttk.Button(lib_btn_row, text="Render selected (queue)",
                           command=lambda: start_queue())
    queue_btn.pack(side="left", padx=(8, 0))
    ttk.Label(libbox,
             text="Ctrl-click or Shift-click to pick several, then Render "
                  "selected to run them back to back, each with its own "
                  "saved settings.",
             foreground="#666", font=("TkDefaultFont", 8),
             wraplength=540, justify="left").pack(anchor="w", pady=(4, 0))

    filebox = ttk.LabelFrame(doc_tab, text="Text file", padding=10)
    filebox.pack(fill="x", pady=4)
    filelabel = ttk.Label(filebox, text="No file chosen", foreground="#777")
    filelabel.pack(side="left", fill="x", expand=True)

    def load_source_path(path):
        """Everything pick_file does once it has a path -- shared with
        loading a document back in from the library, which already has
        one and doesn't need the dialog."""
        try:
            words = len(read_text_file(path).split())
        except ValueError as exc:
            messagebox.showerror("Can't read this file", str(exc))
            return False
        except Exception as exc:
            messagebox.showerror(
                "Can't read this file",
                f"{os.path.basename(path)} could not be read: {exc}")
            return False
        state["path"] = path
        filelabel.config(
            text=f"{os.path.basename(path)}  -  {words:,} words, "
                 f"about {words / 155:.0f} minutes of audio",
            foreground="#000")
        describe_chunks()
        library.touch(path, status="not_started")
        return True

    def pick_file():
        path = filedialog.askopenfilename(
            title="Choose a document",
            filetypes=[("Documents", "*.txt *.md *.markdown *.docx *.odt "
                                     "*.html *.htm *.tex *.epub"),
                       ("Text files", "*.txt *.md *.markdown"),
                       ("Word documents", "*.docx *.odt"),
                       ("All files", "*.*")])
        if not path:
            return
        if load_source_path(path):
            refresh_library_list()

    ttk.Button(filebox, text="Browse...", command=pick_file).pack(side="right")

    # --- where everything is saved ---
    outbox = ttk.LabelFrame(output_tab, text="Save location (everything "
                            "goes here)", padding=10)
    outbox.pack(fill="x", pady=4)
    rootlabel = ttk.Label(outbox, text=state["root"], foreground="#333")
    rootlabel.pack(side="left", fill="x", expand=True)

    def change_root():
        chosen = filedialog.askdirectory(
            title="Choose where narration output should be kept",
            initialdir=state["root"])
        if not chosen:
            return
        target = chosen if os.path.basename(chosen) == "narrator_output" \
            else os.path.join(chosen, "narrator_output")
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Cannot use that folder", str(exc))
            return
        state["root"] = target
        rootlabel.config(text=target)
        settings["output_root"] = target
        save_settings(settings)

    ttk.Button(outbox, text="Change...", command=change_root).pack(side="right")

    # --- settings ---
    setbox = ttk.LabelFrame(voice_tab, text="Voice", padding=10)
    setbox.pack(fill="x", pady=8)
    setbox.columnconfigure(1, weight=1)

    ttk.Label(setbox, text="Engine").grid(row=0, column=0, sticky="w", pady=3)
    # Remember the last engine used, if it's still available -- otherwise
    # fall back to whichever engine was found first.
    _saved_engine = settings.get("last_engine")
    _default_engine = (_saved_engine if _saved_engine in available
                       else available[0])
    engine_var = tk.StringVar(value=_default_engine)
    # ALL engines are listed, not only the installed ones: an engine you
    # can't see is an engine you don't know you could have. Picking an
    # uninstalled one greys out the voice controls and offers to set it up.
    engine_menu = ttk.Combobox(setbox, textvariable=engine_var,
                               values=list(ENGINES), state="readonly")
    engine_menu.grid(row=0, column=1, sticky="ew", padx=8, pady=3)

    setup_row = ttk.Frame(setbox)
    setup_msg = ttk.Label(setup_row, text="", foreground="#a06000",
                         wraplength=420, justify="left")
    setup_msg.pack(side="left")
    setup_btn = ttk.Button(setup_row, text="Download and set up")
    setup_btn.pack(side="left", padx=8)
    setup_bar = ttk.Progressbar(setbox, mode="determinate", maximum=100)

    hint = ttk.Label(setbox, text="", foreground="#666",
                     font=("TkDefaultFont", 8), wraplength=600,
                     justify="left")
    hint.grid(row=1, column=1, sticky="w", padx=8)

    ttk.Label(setbox, text="Voice").grid(row=2, column=0, sticky="nw", pady=3)
    voiceframe = ttk.Frame(setbox)
    voiceframe.grid(row=2, column=1, sticky="ew", padx=8, pady=3)
    voiceframe.columnconfigure(0, weight=1)
    voice_var = tk.StringVar()
    voice_menu = ttk.Combobox(voiceframe, textvariable=voice_var,
                              state="readonly")
    voice_menu.grid(row=0, column=0, sticky="ew")

    build_voice_btn = ttk.Button(voiceframe, text="Build a voice...",
                                 command=lambda: open_voice_builder())
    # Only relevant for editable (description-based) engines like Qwen3;
    # gridded/removed by refresh_option_visibility alongside everything else
    # that depends on which engine is selected.

    # "Take": which roll of the dice this description gets. Qwen3 designs a
    # voice from the description ONCE and then clones it for every part, so
    # the same description always gives the same narrator back. If that
    # narrator isn't right, a new take designs a fresh one -- each take is a
    # separate saved voice under narrator_data/voices, and going back to an
    # earlier number brings that earlier voice back.
    take_frame = ttk.Frame(voiceframe)
    ttk.Label(take_frame, text="Take").pack(side="left", padx=(6, 2))
    take_var = tk.IntVar(value=int(settings.get("qwen_take", 1) or 1))
    take_spin = ttk.Spinbox(take_frame, from_=1, to=99, width=3,
                            textvariable=take_var)
    take_spin.pack(side="left")

    def _current_take():
        try:
            return max(1, int(take_var.get()))
        except (tk.TclError, ValueError):
            return max(1, int(settings.get("qwen_take", 1) or 1))

    def _remember_take(*_):
        try:
            settings["qwen_take"] = max(1, int(take_var.get()))
        except (tk.TclError, ValueError):
            return
        save_settings(settings)
    take_var.trace_add("write", _remember_take)

    ttk.Label(setbox, text="Speed").grid(row=3, column=0, sticky="w", pady=3)
    speedframe = ttk.Frame(setbox)
    speedframe.grid(row=3, column=1, sticky="ew", padx=8, pady=3)
    speed_var = tk.DoubleVar(value=settings.get("speed", -5))
    speed_label = ttk.Label(speedframe, text="5% slower", width=14)
    speed_label.pack(side="right")
    speed_scale = ttk.Scale(speedframe, from_=-25, to=15, variable=speed_var,
                            orient="horizontal")
    speed_scale.pack(side="left", fill="x", expand=True)

    def on_speed(_=None):
        v = int(speed_var.get())
        speed_label.config(text="normal speed" if v == 0 else
                           f"{abs(v)}% {'slower' if v < 0 else 'faster'}")
        settings["speed"] = v
        save_settings(settings)
    speed_scale.config(command=on_speed)
    on_speed()

    def extra_voices_for(engine_key):
        return [tuple(v) for v in
               settings.get("extra_voices", {}).get(engine_key, [])]

    def spec():
        base = ENGINES[engine_var.get()]
        extra = extra_voices_for(base["key"])
        if not extra:
            return base
        return {**base, "voices": base["voices"] + extra}

    def refresh_voices(_=None):
        s = spec()
        labels = [d for _, d in s["voices"]]
        voice_menu.config(values=labels,
                          state="normal" if s["editable"] else "readonly")

        # Remember the last voice used with THIS engine specifically, so
        # switching between Kokoro and edge-tts doesn't forget either one's
        # choice. For Qwen3 (editable) this doubles as remembering the last
        # custom voice description typed in.
        remembered = (settings.get("last_voice_by_engine") or {}).get(s["key"])
        if s["editable"]:
            voice_var.set(remembered if remembered else s["voices"][0][0])
        elif remembered and remembered in labels:
            voice_var.set(remembered)
        else:
            voice_var.set(labels[0])
        hint.config(text=s["hint"])
        settings["last_engine"] = engine_var.get()
        save_settings(settings)

    def _remember_voice(*_):
        s = spec()
        chosen = chosen_voice_id()
        by_engine = settings.setdefault("last_voice_by_engine", {})
        by_engine[s["key"]] = chosen
        save_settings(settings)

    def on_voice_pick(_=None):
        s = spec()
        if not s["editable"]:
            _remember_voice()
            return
        # User picked a preset label; swap in the full editable description.
        for vid, desc in s["voices"]:
            if voice_var.get() == desc:
                voice_var.set(vid)
                return

    def engine_installed(name=None):
        return bool(ENGINES[name or engine_var.get()]["detect"]())

    # Widgets that only make sense once the selected engine exists.
    def _engine_dependent():
        return [voice_menu, speed_scale, take_spin, build_voice_btn,
                pronounce_btn, find_voices_btn, gen_btn, sample_btn,
                compare_btn]

    def refresh_engine_setup(*_):
        """Grey out everything engine-specific when the selected engine
        isn't installed, and offer to install it instead of leaving the
        person to work out why nothing happens."""
        name = engine_var.get()
        if engine_installed(name):
            setup_row.grid_remove()
            setup_bar.grid_remove()
            if not state["running"]:
                for w in _engine_dependent():
                    try:
                        w.config(state="normal")
                    except tk.TclError:
                        pass
            return
        size = {"kokoro": "about 2 GB", "qwen3": "about 8 GB"}.get(
            ENGINES[name]["key"], "a small download")
        setup_msg.config(
            text=f"Not installed yet ({size}). Everything below is "
                 "unavailable until it is.")
        setup_row.grid(row=2, column=1, sticky="ew", padx=8, pady=(4, 0))
        for w in _engine_dependent():
            try:
                w.config(state="disabled")
            except tk.TclError:
                pass

    def do_install_engine():
        name = engine_var.get()
        key = ENGINES[name]["key"]
        if not messagebox.askyesno(
                "Set up this engine",
                f"Download and set up {name}?\n\nThis runs in the "
                "background and can take a while on a slow connection. "
                "The window stays usable and progress appears in the log.",
                parent=root):
            return
        setup_btn.config(state="disabled")
        setup_bar.grid(row=3, column=1, sticky="ew", padx=8, pady=(4, 0))
        setup_bar["value"] = 0
        clear_log()
        set_running(True)

        def on_progress(info):
            # create_environment reports coarse stages rather than a fake
            # smooth percentage; reflect exactly that.
            if info.get("kind") == "stage":
                pct = 100.0 * (info["step"] - 1) / max(1, info["total"])
                root.after(0, lambda: (
                    setup_bar.config(value=pct),
                    setup_msg.config(
                        text=f"{info['label']} "
                             f"(step {info['step']} of {info['total']})...")))
            elif info.get("kind") == "downloading":
                root.after(0, lambda: setup_msg.config(
                    text=f"Downloading {info.get('name', '')} "
                         f"{info.get('size', '')}..."))

        def work():
            try:
                from . import setup_engines as se
                ok = se.create_environment(key, log, on_progress)
                if not ok:
                    raise RuntimeError("Setup did not complete -- see the "
                                       "log above.")
                forget_engine_probes()
                def done():
                    setup_bar.config(value=100)
                    setup_msg.config(text="Installed.", foreground="#060")
                    setup_btn.config(state="normal")
                    refresh_engine_setup()
                    refresh_voices()
                    refresh_option_visibility()
                root.after(0, done)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                log("Setup failed: " + msg)
                def failed():
                    setup_bar.grid_remove()
                    setup_msg.config(text=msg, foreground="#a00")
                    setup_btn.config(state="normal")
                root.after(0, failed)
            finally:
                root.after(0, lambda: set_running(False))
        threading.Thread(target=work, daemon=True).start()

    setup_btn.config(command=do_install_engine)
    engine_menu.bind("<<ComboboxSelected>>", refresh_voices)
    engine_menu.bind("<<ComboboxSelected>>", refresh_engine_setup, add="+")
    voice_menu.bind("<<ComboboxSelected>>", on_voice_pick, add="+")
    refresh_voices()

    def chosen_voice_id():
        s = spec()
        if s["editable"]:
            return voice_var.get().strip() or s["voices"][0][0]
        for vid, desc in s["voices"]:
            if desc == voice_var.get():
                return vid
        return s["voices"][0][0]

    # For the editable Qwen3 box, remember on every edit (not just on a
    # dropdown pick), since typing a custom description IS the normal way
    # of choosing a voice there.
    voice_var.trace_add("write", lambda *a: _remember_voice()
                        if spec()["editable"] else None)

    # --- chunking (how the document gets split for narration) ---
    chunkbox = ttk.LabelFrame(doc_tab, text="Chunking", padding=10)
    chunkbox.pack(fill="x", pady=4)
    chunkbox.columnconfigure(1, weight=1)
    optbox = chunkbox  # widgets below are written against this name

    # Chunk count: shown for every engine, but what it controls differs.
    # Kokoro/edge-tts synthesize each sentence independently regardless of how
    # many sentences are bundled per chunk, so this only affects progress
    # granularity and where a resume point falls, never audio quality. Qwen3
    # is autoregressive and genuinely drifts on long generations, so smaller
    # chunks there are a real quality control, not just bookkeeping.
    CHUNK_MODE_LABELS = {
        "parts": "Number of parts",
        "tokens": "Kokoro tokens per part",
        "chars": "Characters per part",
    }
    CHUNK_MODE_BY_LABEL = {v: k for k, v in CHUNK_MODE_LABELS.items()}

    ttk.Label(optbox, text="Split by").grid(row=0, column=0, sticky="w",
                                            pady=3)
    modeframe = ttk.Frame(optbox)
    modeframe.grid(row=0, column=1, sticky="ew", padx=8, pady=3)
    chunk_mode_var = tk.StringVar(
        value=CHUNK_MODE_LABELS.get(settings.get("chunk_mode", "parts"),
                                    CHUNK_MODE_LABELS["parts"]))
    chunk_mode_menu = ttk.Combobox(
        modeframe, textvariable=chunk_mode_var, state="readonly", width=24,
        values=list(CHUNK_MODE_LABELS.values()))
    chunk_mode_menu.pack(side="left")
    measure_btn = ttk.Button(modeframe, text="Measure tokens")
    measure_btn.pack(side="left", padx=(8, 0))

    ttk.Label(optbox, text="Chunks").grid(row=1, column=0, sticky="w", pady=3)
    chunkframe = ttk.Frame(optbox)
    chunkframe.grid(row=1, column=1, sticky="ew", padx=8, pady=3)
    chunk_var = tk.IntVar(value=settings.get("chunk_count", 1))
    chunk_scale = ttk.Scale(chunkframe, from_=1, to=40, variable=chunk_var,
                            orient="horizontal")
    chunk_scale.pack(side="left", fill="x", expand=True)
    chunk_target_var = tk.IntVar(
        value=int(settings.get("chunk_target", KOKORO_TARGET_TOKENS)))
    chunk_target_spin = ttk.Spinbox(chunkframe, from_=50, to=20000,
                                    increment=50, width=8,
                                    textvariable=chunk_target_var)

    def current_chunk_mode():
        return CHUNK_MODE_BY_LABEL.get(chunk_mode_var.get(), "parts")

    def chunk_setting_value():
        try:
            return (int(chunk_target_var.get())
                    if current_chunk_mode() != "parts"
                    else max(1, int(chunk_var.get())))
        except (tk.TclError, ValueError):
            return KOKORO_TARGET_TOKENS if current_chunk_mode() != "parts" else 1
    chunk_note = ttk.Label(optbox, text="", foreground="#666",
                           font=("TkDefaultFont", 8), wraplength=520,
                           justify="left")
    chunk_note.grid(row=2, column=1, sticky="w", padx=8)

    def describe_chunks(*_):
        if not state["path"]:
            chunk_note.config(text="Choose a file to see chunk sizes.")
            return
        try:
            text = read_text_file(state["path"])
        except Exception:
            chunk_note.config(
                text="Couldn't re-read this file (has it moved or changed "
                     "since you selected it?).")
            return
        mode = current_chunk_mode()
        ratio = state.get("chars_per_token") or DEFAULT_CHARS_PER_TOKEN
        measured = state.get("chars_per_token") is not None
        limit = chunk_limit_for(text, mode, chunk_setting_value(),
                                spec()["chunk"], ratio)
        uncapped = chunk_limit_for(text, mode, chunk_setting_value(),
                                   10 ** 9, ratio)
        parts = chunk_text(text, limit)
        sizes = [len(p) for p in parts]
        avg_chars = (sum(sizes) / len(sizes)) if sizes else 0
        avg_words = avg_chars / 6
        avg_min = avg_words / 155
        avg_tokens = avg_chars / max(0.1, ratio)
        note = (f"{len(parts)} chunk(s), about {avg_words:.0f} words / "
               f"{avg_min:.1f} min each.")
        if spec()["key"] == "kokoro":
            note += (f" Roughly {avg_tokens:.0f} Kokoro tokens per chunk "
                    f"({'measured' if measured else 'estimated'}).")
        if limit < uncapped:
            note += (f" (capped below your requested size to stay safe for "
                     f"{spec()['key']}.)")
        if spec()["key"] == "kokoro":
            note += (f" Kokoro re-splits internally at "
                    f"{KOKORO_TOKEN_LIMIT} tokens whatever you choose "
                    "here, so this mainly controls resume points -- it "
                    "only affects the sound if you make chunks small "
                    "enough to force splits Kokoro wouldn't have made.")
        else:
            note += (" More chunks = more frequent progress updates and "
                     "finer resume points. For Qwen3-TTS, smaller chunks "
                     "also reduce drift.")
        chunk_note.config(text=note)

    def refresh_chunk_mode(*_):
        mode = current_chunk_mode()
        if mode == "parts":
            chunk_target_spin.pack_forget()
            chunk_scale.pack(side="left", fill="x", expand=True)
        else:
            chunk_scale.pack_forget()
            chunk_target_spin.pack(side="left")
        settings["chunk_mode"] = mode
        # Save the target alongside the mode: the spinbox's own trace only
        # fires when it is edited, so a target left at its default would
        # otherwise never be persisted at all.
        settings["chunk_target"] = chunk_setting_value()
        save_settings(settings)
        describe_chunks()

    def on_chunk_change(*_):
        describe_chunks()
        settings["chunk_count"] = int(chunk_var.get())
        save_settings(settings)
    chunk_scale.config(command=on_chunk_change)

    def on_chunk_target_change(*_):
        try:
            settings["chunk_target"] = int(chunk_target_var.get())
        except (tk.TclError, ValueError):
            return
        save_settings(settings)
        describe_chunks()
    chunk_target_var.trace_add("write", on_chunk_target_change)
    chunk_mode_menu.bind("<<ComboboxSelected>>", refresh_chunk_mode)
    refresh_chunk_mode()

    def do_measure_tokens():
        """Replace the estimated characters-per-token ratio with the real
        one for THIS document, measured with the same G2P Kokoro uses.
        Samples the middle of the document rather than the whole thing --
        a few thousand characters is plenty to fix the ratio, and running
        G2P over an entire dissertation would be needlessly slow."""
        if not state["path"]:
            messagebox.showwarning("No file", "Choose a text file first.")
            return
        measure_btn.config(state="disabled")
        chunk_note.config(text="Measuring tokens with Kokoro's own "
                              "phonemiser...")

        def bg():
            try:
                text = read_text_file(state["path"])
                mid = max(0, len(text) // 2 - 2000)
                sample = text[mid:mid + 4000]
                if not sample.strip():
                    sample = text[:4000]
                counts = measure_kokoro_phonemes([sample], log)
                tokens = counts[0] if counts else -1
                if tokens and tokens > 0:
                    ratio = len(sample) / tokens
                    root.after(0, lambda: done(ratio, tokens, len(sample)))
                else:
                    root.after(0, lambda: failed(
                        "Kokoro's phonemiser couldn't measure that sample."))
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                root.after(0, lambda: failed(msg))

        def done(ratio, tokens, sample_len):
            state["chars_per_token"] = ratio
            measure_btn.config(state="normal")
            log(f"Measured {tokens:,} Kokoro tokens in a {sample_len:,}"
               f"-character sample -> {ratio:.3f} characters per token.")
            describe_chunks()

        def failed(msg):
            measure_btn.config(state="normal")
            log(f"Couldn't measure tokens: {msg}")
            chunk_note.config(
                text=f"Couldn't measure tokens ({msg}). Still usable -- "
                     "token counts just stay estimates until Kokoro is "
                     "set up.")

        threading.Thread(target=bg, daemon=True).start()

    measure_btn.config(command=do_measure_tokens)

    # edge-tts / kokoro: engine-specific options, next to the engine picker.
    enginebox = ttk.Frame(voice_tab)
    enginebox.pack(fill="x", pady=(10, 0))
    optbox = enginebox

    # edge-tts only: subtitles and a custom filename.
    edge_frame = ttk.Frame(optbox)
    edge_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
    edge_frame.columnconfigure(1, weight=1)

    subtitles_var = tk.BooleanVar(value=settings.get("subtitles", False))
    subtitles_var.trace_add(
        "write", lambda *a: (settings.__setitem__("subtitles",
                                                   bool(subtitles_var.get())),
                            save_settings(settings)))
    ttk.Checkbutton(edge_frame, text="Also save subtitles (.srt)",
                    variable=subtitles_var).grid(
        row=0, column=0, columnspan=2, sticky="w")

    ttk.Label(edge_frame, text="File name").grid(
        row=1, column=0, sticky="w", pady=(4, 0))
    filename_var = tk.StringVar()
    filename_entry = ttk.Entry(edge_frame, textvariable=filename_var)
    filename_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(4, 0))
    ttk.Label(edge_frame,
             text="Leave blank to auto-name from the document, engine, "
                  "voice and time.",
             foreground="#666", font=("TkDefaultFont", 8)).grid(
        row=2, column=1, sticky="w", padx=8)

    # Kokoro only: pronunciation pre-flight check.
    kokoro_frame = ttk.Frame(optbox)
    kokoro_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
    pronounce_btn = ttk.Button(kokoro_frame, text="Check pronunciation...",
                               command=lambda: open_pronunciation_dialog())
    pronounce_btn.pack(side="left")
    ttk.Label(kokoro_frame,
             text="  Scans for words Kokoro's dictionary doesn't know, and "
                  "acronyms worth spelling out.",
             foreground="#666", font=("TkDefaultFont", 8)).pack(side="left")

    kokoro_voices_row = ttk.Frame(kokoro_frame)
    kokoro_voices_row.pack(side="top", fill="x", pady=(4, 0))
    find_voices_btn = ttk.Button(kokoro_voices_row, text="Find more voices...",
                                 command=lambda: open_kokoro_voice_finder())
    find_voices_btn.pack(side="left")
    ttk.Label(kokoro_voices_row,
             text="  Checks Hugging Face for every voice Kokoro currently "
                  "ships (needs internet), so new ones don't need an app "
                  "update to use.",
             foreground="#666", font=("TkDefaultFont", 8)).pack(side="left")

    def refresh_option_visibility(*_):
        s = spec()
        edge_frame.grid_remove()
        kokoro_frame.grid_remove()
        build_voice_btn.grid_remove()
        if s["key"] == "edge":
            edge_frame.grid()
        elif s["key"] == "kokoro":
            kokoro_frame.grid()
        take_frame.grid_remove()
        if s["editable"]:
            build_voice_btn.grid(row=0, column=1, padx=(6, 0))
            take_frame.grid(row=0, column=2)
        describe_chunks()

    engine_menu.bind("<<ComboboxSelected>>", refresh_option_visibility, add="+")
    refresh_option_visibility()

    # --- output: format, quality, folder structure, chunks, video ---
    outfmt = ttk.LabelFrame(output_tab, text="Format & extras", padding=10)
    outfmt.pack(fill="x", pady=4)
    outfmt.columnconfigure(1, weight=1)

    ttk.Label(outfmt, text="Format").grid(row=0, column=0, sticky="w", pady=3)
    format_var = tk.StringVar(value=settings.get("format", DEFAULT_FORMAT))
    format_menu = ttk.Combobox(outfmt, textvariable=format_var,
                               values=list(AUDIO_FORMATS.keys()),
                               state="readonly")
    format_menu.grid(row=0, column=1, sticky="ew", padx=8, pady=3)

    ttk.Label(outfmt, text="Sample rate").grid(
        row=1, column=0, sticky="w", pady=3)
    samplerate_var = tk.IntVar(value=settings.get("sample_rate", 44100))
    samplerate_menu = ttk.Combobox(outfmt, textvariable=samplerate_var,
                                   values=[str(r) for r in SAMPLE_RATES],
                                   state="readonly")
    samplerate_menu.grid(row=1, column=1, sticky="w", padx=8, pady=3)

    bitdepth_label = ttk.Label(outfmt, text="Bit depth")
    bitdepth_label.grid(row=2, column=0, sticky="w", pady=3)
    bitdepth_var = tk.IntVar(value=settings.get("bit_depth", 16))
    bitdepth_menu = ttk.Combobox(outfmt, textvariable=bitdepth_var,
                                 values=[str(b) for b in BIT_DEPTHS],
                                 state="readonly", width=6)
    bitdepth_menu.grid(row=2, column=1, sticky="w", padx=8, pady=3)

    ttk.Label(outfmt, text="Quality").grid(row=3, column=0, sticky="w", pady=3)
    qualframe = ttk.Frame(outfmt)
    qualframe.grid(row=3, column=1, sticky="ew", padx=8, pady=3)
    quality_var = tk.DoubleVar(value=settings.get("quality_pct", 100))
    quality_scale = ttk.Scale(qualframe, from_=0, to=100,
                              variable=quality_var, orient="horizontal")
    quality_scale.pack(side="left", fill="x", expand=True)
    quality_label = ttk.Label(qualframe, text="100%", width=12)
    quality_label.pack(side="right")
    quality_note = ttk.Label(outfmt, text="", foreground="#666",
                             font=("TkDefaultFont", 8), wraplength=520,
                             justify="left")
    quality_note.grid(row=4, column=1, sticky="w", padx=8)

    def refresh_format(*_):
        fmt = AUDIO_FORMATS[format_var.get()]
        lossy = fmt["lossy"]
        is_wav = fmt["ext"] == "wav"

        # WAV has no compression concept -- raw samples -- so the slider is
        # disabled rather than left implying it does something for it.
        quality_scale.state(["disabled"] if is_wav else ["!disabled"])
        snapped = slider_index(quality_var.get()) * 10
        quality_var.set(snapped)
        if is_wav:
            quality_label.config(text="n/a")
            quality_note.config(text="WAV is uncompressed; there's nothing "
                                     "for this to control.")
        elif lossy:
            kbps = fmt["bitrates"][slider_index(snapped)]
            quality_label.config(text=f"{snapped:.0f}%  (~{kbps}kbps)")
            quality_note.config(text="Higher = larger file, less audible "
                                     "compression. 100% is closer to source "
                                     "quality than most podcast hosts need.")
        else:  # flac
            lvl = fmt["compression_levels"][slider_index(snapped)]
            quality_label.config(text=f"{snapped:.0f}%  (level {lvl})")
            quality_note.config(text="FLAC is lossless either way -- this "
                                     "only trades encode time for a smaller "
                                     "file, never audio quality.")

        # Bit depth only means anything for formats that store raw samples.
        show_depth = fmt["ext"] in ("wav", "flac")
        (bitdepth_label.grid if show_depth else bitdepth_label.grid_remove)()
        (bitdepth_menu.grid if show_depth else bitdepth_menu.grid_remove)()

    format_menu.bind("<<ComboboxSelected>>", refresh_format)
    refresh_format()

    use_subfolders_var = tk.BooleanVar(
        value=settings.get("use_subfolders", False))
    ttk.Checkbutton(
        outfmt, text="Organize into one subfolder per document "
                    "(off = everything in one flat folder)",
        variable=use_subfolders_var).grid(
        row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

    keep_chunks_var = tk.BooleanVar(value=settings.get("keep_chunks", False))
    ttk.Checkbutton(
        outfmt, text="Keep individual sentence/chunk audio files too",
        variable=keep_chunks_var).grid(
        row=6, column=0, columnspan=2, sticky="w")
    ttk.Label(outfmt,
             text="Saved to <output>_chunks/, each lightly faded so it "
                  "plays cleanly on its own.",
             foreground="#666", font=("TkDefaultFont", 8)).grid(
        row=7, column=1, sticky="w", padx=8)

    # --- companion WAV for video editing ---
    editing_wav_var = tk.BooleanVar(value=settings.get("editing_wav", False))
    wav_row = ttk.Frame(outfmt)
    wav_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(
        wav_row,
        text="Also save an uncompressed .wav for video editing",
        variable=editing_wav_var,
        command=lambda: refresh_wav_row()).pack(anchor="w")

    wav_opts_row = ttk.Frame(outfmt)
    wav_opts_row.grid(row=9, column=0, columnspan=2, sticky="ew",
                      padx=(20, 0))
    ttk.Label(wav_opts_row, text="Sample rate").pack(side="left")
    editing_wav_rate_var = tk.IntVar(
        value=settings.get("editing_wav_rate", 48000))
    ttk.Combobox(wav_opts_row, textvariable=editing_wav_rate_var,
                values=[str(r) for r in EDITING_WAV_RATES],
                state="readonly", width=8).pack(side="left", padx=(6, 14))
    ttk.Label(wav_opts_row, text="Channels").pack(side="left")
    editing_wav_ch_var = tk.StringVar(
        value=settings.get("editing_wav_channels_label", "Mono"))
    ttk.Combobox(wav_opts_row, textvariable=editing_wav_ch_var,
                values=list(EDITING_WAV_CHANNELS), state="readonly",
                width=8).pack(side="left", padx=6)
    ttk.Label(outfmt,
             text="Saved next to the audio. 48000 matches most editing "
                  "timelines and avoids the resampling that causes waveform "
                  "desync; converted from the original, not from the "
                  "compressed file.",
             foreground="#666", font=("TkDefaultFont", 8),
             wraplength=560, justify="left").grid(
        row=10, column=1, sticky="w", padx=8)

    def refresh_wav_row():
        (wav_opts_row.grid if editing_wav_var.get()
         else wav_opts_row.grid_remove)()
        settings["editing_wav"] = bool(editing_wav_var.get())
        save_settings(settings)

    # --- video export ---
    make_video_var = tk.BooleanVar(value=False)
    video_row = ttk.Frame(outfmt)
    video_row.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Checkbutton(video_row, text="Also export a video (image + waveform"
                                    ", captions if subtitles is on)",
                    variable=make_video_var,
                    command=lambda: refresh_video_row()).pack(anchor="w")

    video_image_row = ttk.Frame(outfmt)
    video_image_row.grid(row=12, column=0, columnspan=2, sticky="ew",
                         padx=(20, 0))
    video_image_label = ttk.Label(video_image_row, text="No image chosen",
                                  foreground="#777")
    video_image_label.pack(side="left", fill="x", expand=True)
    state["video_image"] = settings.get("video_image") or None
    if state["video_image"] and os.path.isfile(state["video_image"]):
        video_image_label.config(text=os.path.basename(state["video_image"]),
                                 foreground="#000")

    def pick_video_image():
        path = filedialog.askopenfilename(
            title="Choose a background image",
            filetypes=[("Images", "*.jpg *.jpeg *.png"),
                      ("All files", "*.*")])
        if not path:
            return
        state["video_image"] = path
        video_image_label.config(text=os.path.basename(path),
                                 foreground="#000")
        settings["video_image"] = path
        save_settings(settings)

    ttk.Button(video_image_row, text="Choose image...",
              command=pick_video_image).pack(side="right")

    def refresh_video_row(*_):
        (video_image_row.grid if make_video_var.get()
         else video_image_row.grid_remove)()

    refresh_video_row()
    refresh_wav_row()

    def persist_output_settings(*_):
        settings["format"] = format_var.get()
        settings["sample_rate"] = int(samplerate_var.get())
        settings["bit_depth"] = int(bitdepth_var.get())
        settings["quality_pct"] = float(quality_var.get())
        settings["use_subfolders"] = bool(use_subfolders_var.get())
        settings["keep_chunks"] = bool(keep_chunks_var.get())
        save_settings(settings)

    for widget, event in [(format_menu, "<<ComboboxSelected>>"),
                          (bitdepth_menu, "<<ComboboxSelected>>"),
                          (samplerate_menu, "<<ComboboxSelected>>")]:
        widget.bind(event, persist_output_settings, add="+")
    quality_scale.config(
        command=lambda v: (refresh_format(), persist_output_settings()))
    use_subfolders_var.trace_add("write", persist_output_settings)
    keep_chunks_var.trace_add("write", persist_output_settings)

    # --- log ---
    logbox = ttk.LabelFrame(outer, text="Progress", padding=6)
    logbox.pack(fill="both", expand=True, pady=8)
    logview = scrolledtext.ScrolledText(logbox, height=12, wrap="word",
                                        font=("TkFixedFont", 9))
    logview.pack(fill="both", expand=True)
    logview.insert("end",
                   "Ready.\n\nTip: run your document through prep_for_tts.py "
                   "first to strip citations,\nreference lists and tables. "
                   "Raw academic text reads badly aloud.\n")
    logview.config(state="disabled")

    def log(msg):
        msgs.put(msg)

    def drain():
        while True:
            try:
                msg = msgs.get_nowait()
            except queue.Empty:
                break
            logview.config(state="normal")
            logview.insert("end", msg + "\n")
            logview.see("end")
            logview.config(state="disabled")
        root.after(120, drain)

    def clear_log():
        logview.config(state="normal")
        logview.delete("1.0", "end")
        logview.config(state="disabled")

    # --- actions ---
    btnbar = ttk.Frame(outer)
    btnbar.pack(fill="x")
    status = ttk.Label(btnbar, text="", foreground="#555")
    status.pack(side="left")

    def set_running(on):
        state["running"] = on
        for b in (gen_btn, sample_btn, compare_btn, open_btn, fix_btn,
                 lib_load_btn, queue_btn, timeline_btn):
            b.config(state="disabled" if on else "normal")
        if not on:
            # Re-enabling everything is wrong if the selected engine still
            # isn't installed; this puts that gating back.
            refresh_engine_setup()
        menu_state = "disabled" if on else "normal"
        for label in ("Settings", "Tools"):
            try:
                menubar.entryconfig(label, state=menu_state)
            except tk.TclError:
                pass
        status.config(
            text="Working... the window may look frozen; it isn't."
            if on else "")

    # The orchestration itself lives in session.py, with no widgets in
    # sight; these just supply this window's log and take store.
    def render(cfg, chunks, voice, is_sample):
        return session_mod.render(cfg, chunks, voice, is_sample, log,
                                  ENGINES[cfg["engine"]], state["session"])

    def render_document(cfg):
        return session_mod.render_document(cfg, log, ENGINES[cfg["engine"]],
                                           state["session"])

    def work(mode, cfg):
        s = ENGINES[cfg["engine"]]
        try:
            if mode == "compare":
                voices = [v for v, _ in s["voices"] + extra_voices_for(s["key"])]
                log(f"Rendering the same sample in {len(voices)} voices.\n")
                for i, v in enumerate(voices, 1):
                    if state["cancel"]:
                        break
                    log(f"[{i}/{len(voices)}] {v[:60]}")
                    render(cfg, [SAMPLE_TEXT], v, True)
                log(f"\nAll samples are in:\n  "
                    f"{os.path.join(cfg['root'], 'samples')}")
            elif mode == "sample":
                out = render(cfg, [SAMPLE_TEXT], cfg["voice"], True)
                if out:
                    log(f"\nFull path:\n  {out}")
            elif mode == "clean":
                log("Cleaning document (citations, tables, reference "
                   "lists, markdown syntax)...\n")
                text, clean_log, orig_words = clean_document(cfg["path"])
                for l in clean_log:
                    log(f"  {l}")
                folder = document_folder(cfg["root"], cfg["path"],
                                        cfg.get("use_subfolders", False))
                os.makedirs(folder, exist_ok=True)
                stem = slugify(
                    os.path.splitext(os.path.basename(cfg["path"]))[0], 60)
                out_path = unique_path(
                    os.path.join(folder, stem + "_clean.txt"))
                with open(out_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                words = len(text.split())
                log(f"\n{orig_words:,} words -> {words:,} words "
                   f"({orig_words - words:,} removed)")
                log(f"Saved: {out_path}")
                log("\nOpening it now -- read it over before narrating. "
                   "Nothing has been generated yet.")
                library.touch(cfg["path"], status="prepared")
                reveal_file(out_path)
            else:
                out = render_document(cfg)
                if out:
                    log(f"\nDone.\n{out}")
        except Exception as exc:
            log(f"\nSomething went wrong:\n  {type(exc).__name__}: {exc}")
            if "sm_120" in str(exc) or "CUDA" in str(exc):
                log("\nThis is the Blackwell GPU issue. Reinstall PyTorch "
                    "with:\n  pip install torch torchaudio --index-url "
                    "https://download.pytorch.org/whl/cu128")
        finally:
            state["cancel"] = False
            root.after(0, lambda: set_running(False))
            # Refreshes whether or not this render produced a real last_render
            # (a sample/compare run changes nothing there, which is fine --
            # refresh_publish_tab just re-confirms the same state).
            root.after(0, refresh_publish_tab)
            root.after(0, refresh_library_list)

    def work_queue(paths):
        """Render several library documents back to back, each with its
        OWN saved settings -- not whatever happens to be on screen. One
        document failing never abandons the rest of the batch; it is
        reported and the queue moves on."""
        try:
            outcome = session_mod.run_queue(
                paths, log, ENGINES, state["session"],
                should_cancel=lambda: state["cancel"])
            if outcome["done"]:
                log("\nEach finished take can be published from the "
                   "Publish tab -- pick which one there.")
        finally:
            state["cancel"] = False
            root.after(0, lambda: set_running(False))
            root.after(0, refresh_publish_tab)
            root.after(0, refresh_library_list)

    def start_queue():
        if state["running"]:
            return
        paths = selected_project_paths()
        if not paths:
            messagebox.showinfo(
                "Nothing selected",
                "Tick one or more documents in the Library list first "
                "(Ctrl-click or Shift-click for several).", parent=root)
            return
        if not messagebox.askyesno(
                "Render queue",
                f"Render {len(paths)} document(s) back to back, each with "
                "the settings saved for it?\n\nThis can take a long "
                "while; the window stays usable and the log shows "
                "progress.", parent=root):
            return
        clear_log()
        set_running(True)
        threading.Thread(target=work_queue, args=(paths,),
                        daemon=True).start()

    def start(mode):
        if state["running"]:
            return
        if not state["path"]:
            messagebox.showwarning("No file", "Choose a text file first.")
            return
        if mode in ("generate", "clean"):
            # The file was readable when it was picked, but that could
            # have been hours ago -- it may have been moved, deleted or
            # replaced since. Without this guard the exception lands
            # uncaught in the Tk callback, which shows the person nothing.
            try:
                empty = not read_text_file(state["path"]).strip()
            except Exception as exc:
                messagebox.showerror(
                    "Can't read that file now",
                    f"{os.path.basename(state['path'])} could not be read:"
                    f"\n\n{type(exc).__name__}: {exc}\n\n"
                    "Has it been moved, renamed or deleted since you "
                    "chose it?")
                return
            if empty:
                messagebox.showwarning("Empty file",
                                       "That file has no text in it.")
                return
        if mode == "generate" and make_video_var.get() and \
                not state.get("video_image"):
            messagebox.showwarning(
                "No background image",
                "Video export needs a background image -- pick one under "
                "\"Also export a video\" first.")
            return

        # Read every setting here, on the main thread, and hand the worker a
        # plain dict. Nothing below this line may read a widget.
        cfg = {
            "path": state["path"],
            "root": state["root"],
            "engine": engine_var.get(),
            "voice": chosen_voice_id(),
            "take": _current_take(),
            "speed": int(speed_var.get()),
            "chunk_count": int(chunk_var.get()),
            "chunk_mode": current_chunk_mode(),
            "chunk_target": chunk_setting_value(),
            "chars_per_token": state.get("chars_per_token"),
            "subtitles": subtitles_var.get(),
            "filename": filename_var.get().strip(),
            "format": format_var.get(),
            "sample_rate": int(samplerate_var.get()),
            "bit_depth": int(bitdepth_var.get()),
            "quality_pct": float(quality_var.get()),
            "use_subfolders": bool(use_subfolders_var.get()),
            "keep_chunks": bool(keep_chunks_var.get()),
            "make_video": bool(make_video_var.get()),
            "editing_wav": bool(editing_wav_var.get()),
            "editing_wav_rate": int(editing_wav_rate_var.get()),
            "editing_wav_channels": EDITING_WAV_CHANNELS.get(
                editing_wav_ch_var.get(), 1),
            "video_image": state.get("video_image"),
            "intro_audio": settings.get("intro_audio") or None,
            "outro_audio": settings.get("outro_audio") or None,
            "intro_crossfade": float(settings.get("intro_crossfade", 1.0)),
        }

        # The widgets are one way of filling the schema in; the schema is
        # what decides whether the result is usable. This catches a bad
        # value here rather than partway through a long render -- and it
        # is the same check a cfg from a saved project or another
        # interface goes through.
        cfg, problems = render_config.coerce(cfg)
        if problems:
            blocking = [p for p in problems if "is required" in p
                       or "isn't one of" in p or "no file at" in p
                       or "no folder at" in p]
            if blocking:
                messagebox.showerror(
                    "These settings can't be used",
                    "\n".join("- " + p for p in blocking))
                return

        clear_log()
        # After clear_log, or the notes would be wiped by it.
        for problem in problems:
            log(f"Note: {problem}")
        log(f"Engine: {ENGINES[cfg['engine']]['key']}")
        log(f"Voice:  {cfg['voice']}")
        if ENGINES[cfg["engine"]]["editable"]:
            log(f"Take:   {cfg['take']}  (same description + take = same "
                f"saved voice)")
        log(f"Speed:  {cfg['speed']:+d}%")
        log(f"Output: {document_folder(cfg['root'], cfg['path'], cfg['use_subfolders'])}\n")
        set_running(True)
        threading.Thread(target=work, args=(mode, cfg), daemon=True).start()

    def reveal(path):
        os.makedirs(path, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            # Popen, not run: xdg-open can take several real seconds trying
            # a chain of fallback openers before giving up, and run() would
            # block the worker thread on that the whole time -- keeping
            # state["running"] True well after the actual work is done, so
            # the next button press silently no-ops. os.startfile on Windows
            # is already fire-and-forget; this matches that on Linux/Mac.
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    def reveal_file(path):
        """Same as reveal(), but for a single file that already exists --
        reveal() would try to makedirs a folder with the file's own name."""
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    def open_folder():
        reveal(document_folder(state["root"], state["path"],
                               use_subfolders_var.get())
               if state["path"] else state["root"])

    def open_kokoro_voice_finder():
        """Query Hugging Face for the current full Kokoro voice roster and
        let the user add any of them -- not the fixed set this app ships
        with. Runs the query wherever kokoro actually is (in-process or
        the separate kokoro-env), same as a render would."""
        win = tk.Toplevel(root)
        win.title("Find more Kokoro voices")
        win.geometry("580x480")
        win.transient(root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        status = ttk.Label(frame,
                           text="Checking Hugging Face for the current "
                                "voice list (needs internet)...",
                           foreground="#666", wraplength=540, justify="left")
        status.pack(anchor="w")
        listbox = tk.Listbox(frame, selectmode="extended", height=16,
                             font=("TkFixedFont", 9))
        listbox.pack(fill="both", expand=True, pady=(8, 8))
        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x")
        add_btn = ttk.Button(btn_row, text="Add selected", state="disabled")
        add_btn.pack(side="left")
        ttk.Button(btn_row, text="Close",
                  command=win.destroy).pack(side="right")
        found = {"voices": []}

        def show_results(voices, error):
            if not win.winfo_exists():
                return  # dialog was closed before the fetch came back
            if error:
                status.config(
                    text="Couldn't reach Hugging Face to list voices:\n"
                         f"{error}\n\nCheck your internet connection and "
                         "try again.", foreground="#a00")
                return
            known = ({v for v, _ in KOKORO_VOICES} |
                    {v for v, _ in extra_voices_for("kokoro")})

            def sort_key(v):
                return (v[0] not in ("a", "b"), v)
            new = sorted((v for v in voices if v not in known), key=sort_key)
            found["voices"] = new
            if not new:
                status.config(
                    text=f"Found {len(voices)} voice(s) on Hugging Face -- "
                        "every one is already in your list.",
                    foreground="#666")
                return
            status.config(
                text=f"Found {len(new)} voice(s) not already in your list "
                    "(English first). Select any number below, then "
                    "Add selected. Japanese and Mandarin voices need an "
                    "extra package before they'll actually work -- noted "
                    "next to each; the rest work right away.",
                foreground="#000")
            for v in new:
                lang_name = KOKORO_LANGUAGES.get(v[0], v[0])
                extra_dep = KOKORO_LANGUAGE_EXTRA_DEPS.get(v[0])
                note = f"  [needs pip install {extra_dep}]" if extra_dep else ""
                listbox.insert("end", f"{lang_name:<20} {v}{note}")
            add_btn.config(state="normal")

        def do_fetch():
            def bg():
                try:
                    voices = fetch_kokoro_voices(log)
                    root.after(0, lambda: show_results(voices, None))
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    root.after(0, lambda: show_results(None, msg))
            threading.Thread(target=bg, daemon=True).start()

        def do_add():
            sel = list(listbox.curselection())
            if not sel:
                status.config(text="Pick at least one voice first.",
                             foreground="#a00")
                return
            chosen = [found["voices"][i] for i in sel]
            extra = settings.setdefault("extra_voices", {})
            kokoro_extra = extra.setdefault("kokoro", [])
            existing_ids = {v for v, _ in kokoro_extra}
            added = []
            for vid in chosen:
                if vid in existing_ids:
                    continue
                name = (vid.split("_", 1)[1].replace("_", " ").title()
                        if "_" in vid else vid)
                lang_name = KOKORO_LANGUAGES.get(vid[0], vid[0])
                kokoro_extra.append([vid, f"{name} ({lang_name})"])
                added.append(vid)
            save_settings(settings)
            log(f"Added {len(added)} Kokoro voice(s) to the picker: "
               + ", ".join(added))
            refresh_voices()
            # Remove the added rows so they can't be added twice, highest
            # index first so an earlier deletion doesn't shift the index
            # of one still queued -- the window stays open in case there's
            # a second batch (English now, say, Spanish in a moment).
            for i in sorted(sel, reverse=True):
                listbox.delete(i)
                del found["voices"][i]
            status.config(
                text=f"Added {len(added)} voice(s) -- they're in the "
                    "Voice list now. Pick more below, or Close when "
                    "you're done. The first time you use a new voice, "
                    "Kokoro downloads it (a few MB).",
                foreground="#060")
            if not found["voices"]:
                add_btn.config(state="disabled")

        add_btn.config(command=do_add)
        do_fetch()

    def open_pronunciation_dialog():
        if not state["path"]:
            messagebox.showwarning("No file", "Choose a text file first.")
            return

        win = tk.Toplevel(root)
        win.title("Check pronunciation")
        win.geometry("640x520")
        win.transient(root)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        status_lbl = ttk.Label(frame, text="Scanning...")
        status_lbl.pack(anchor="w")

        body = ttk.Frame(frame)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical",
                                  command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        entries = {}     # word -> StringVar holding the phoneme override
        acro_vars = {}   # word -> BooleanVar for "spell it out"

        def build_results(result):
            for w in body.winfo_children():
                pass
            body.pack(fill="both", expand=True, pady=(8, 0))
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            if "error" in result:
                status_lbl.config(text=result["error"])
                return

            existing = load_pronunciations()
            unknown = result["unknown"]
            acronyms = result["acronyms"]
            status_lbl.config(
                text=f"Checked {result['checked']} distinct words -- "
                     f"{len(unknown)} unknown, {len(acronyms)} acronym(s).")

            row = 0
            if unknown:
                ttk.Label(inner, text="Unknown words",
                         font=("TkDefaultFont", 10, "bold")).grid(
                    row=row, column=0, columnspan=3, sticky="w", pady=(4, 2))
                row += 1
                ttk.Label(inner,
                         text="These fall through to a weaker fallback "
                              "pronunciation. Type the word phonetically "
                              "using ordinary letters and spaces, the way "
                              "you'd sound it out for someone -- \"nare uh "
                              "tiv izing\", not IPA symbols. The first word "
                              "gets the main stress by default; mark a "
                              "different one with a leading * (\"nare uh "
                              "*tiv izing\") if that sounds better. Press "
                              "Tab or click elsewhere to check it; the "
                              "preview shows what will actually be stored.",
                         foreground="#666", wraplength=580,
                         justify="left").grid(
                    row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
                row += 1
                for word in unknown:
                    ttk.Label(inner, text=word).grid(
                        row=row, column=0, sticky="w", padx=(0, 8), pady=2)

                    stored_ipa = existing.get(word.lower(), "")
                    respell_var = tk.StringVar(
                        value=existing.get(word.lower() + "__respelling", ""))
                    entries[word] = {"respelling": respell_var,
                                     "resolved_ipa": stored_ipa or None}

                    entry = ttk.Entry(inner, textvariable=respell_var,
                                      width=28)
                    entry.grid(row=row, column=1, sticky="ew", pady=2,
                              padx=(0, 6))

                    preview = ttk.Label(inner, text=(
                        "(unchanged)" if not stored_ipa else "using saved fix"),
                        foreground="#888", font=("TkDefaultFont", 8),
                        wraplength=180)
                    preview.grid(row=row, column=2, sticky="w", pady=2)

                    def make_checker(w, var, prev_label, store):
                        def check(_=None):
                            text = var.get().strip()
                            if not text:
                                store["resolved_ipa"] = None
                                prev_label.config(
                                    text="(unchanged)", foreground="#888")
                                return
                            pieces, stress_on = parse_pieces_with_stress(text)
                            ipa, failed = respell_to_ipa(pieces, stress_on)
                            if ipa:
                                store["resolved_ipa"] = ipa
                                prev_label.config(
                                    text=f"-> {ipa}", foreground="#2a7a2a")
                            else:
                                store["resolved_ipa"] = None
                                prev_label.config(
                                    text=f'"{failed}" isn\'t a word Kokoro '
                                        f"recognises -- try different words",
                                    foreground="#b33")
                        return check

                    checker = make_checker(word, respell_var, preview,
                                           entries[word])
                    entry.bind("<FocusOut>", checker)
                    entry.bind("<Return>", checker)
                    if respell_var.get():
                        checker()
                    row += 1

            if acronyms:
                ttk.Label(inner, text="Acronyms",
                         font=("TkDefaultFont", 10, "bold")).grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(14, 2))
                row += 1
                ttk.Label(inner,
                         text="Check the box to have this spelled out "
                              "letter by letter (A.P.I. instead of a word). "
                              "Leave unchecked if it already sounds right.",
                         foreground="#666", wraplength=560,
                         justify="left").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
                row += 1
                for word in acronyms:
                    stored = existing.get(word.lower(), "")
                    already = bool(stored) and stored == acronym_ipa(word)
                    v = tk.BooleanVar(value=already)
                    acro_vars[word] = v
                    ttk.Checkbutton(
                        inner, text=f"{word}  ->  {spell_out(word)}",
                        variable=v).grid(
                        row=row, column=0, columnspan=2, sticky="w", pady=2)
                    row += 1

            if not unknown and not acronyms:
                ttk.Label(inner, text="No problem words found.").grid(
                    row=0, column=0, sticky="w")

            inner.columnconfigure(1, weight=1)

        def run_scan():
            try:
                text = read_text_file(state["path"])
            except Exception as exc:
                win.after(0, lambda: build_results(
                    {"error": f"Couldn't read this file: {exc}"}))
                return
            result = scan_pronunciation(text, overrides=load_pronunciations())
            win.after(0, lambda: build_results(result))

        threading.Thread(target=run_scan, daemon=True).start()

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(10, 0))

        def save_and_close():
            data = load_pronunciations()
            added, skipped = 0, []
            for word, store in entries.items():
                respelling = store["respelling"].get().strip()
                key = word.lower()
                if not respelling:
                    continue  # left blank; don't touch any existing fix
                if store["resolved_ipa"]:
                    data[key] = store["resolved_ipa"]
                    data[key + "__respelling"] = respelling
                    added += 1
                else:
                    skipped.append(word)
            for word, var in acro_vars.items():
                key = word.lower()
                ipa = acronym_ipa(word)
                if var.get():
                    if ipa:
                        data[key] = ipa
                        added += 1
                    else:
                        log(f"  ! could not resolve letter-by-letter "
                            f"pronunciation for {word}; skipped")
                elif key in data and ipa and data[key] == ipa:
                    del data[key]  # unticked again; remove the fix
            save_pronunciations(data)
            if skipped:
                log(f"  ! skipped (couldn't resolve): {', '.join(skipped)} "
                    f"-- try different words for these")
            log(f"Saved {added} pronunciation fix(es) to "
                f"{os.path.basename(PRONOUNCE_FILE)}")
            win.destroy()

        ttk.Button(btns, text="Save", command=save_and_close).pack(side="right")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(
            side="right", padx=6)
        ttk.Label(btns,
                 text="Saved fixes apply automatically to every future "
                      "Kokoro run, for every document.",
                 foreground="#666", font=("TkDefaultFont", 8)).pack(
            side="left")

    # --- Qwen3 voice builder ---------------------------------------------
    #
    # Qwen3's VoiceDesign mode takes a single free-text description (the
    # "instruct" field), not discrete numeric parameters -- there is no
    # underlying pitch/speed/timbre knob to expose, however tempting it is
    # to build one anyway. What this dialog actually does is compose that
    # free-text description FOR you from a handful of structured choices,
    # then write the result into the same editable voice field you could
    # type into directly -- so this is a convenience layer over the real
    # API, not a different API. Nothing here is guessed: the phrasing
    # matches the style of the built-in presets in QWEN_VOICES.

    VOICE_GENDERS = ["male", "female", "neutral"]
    VOICE_AGES = ["young adult", "in their thirties", "middle-aged",
                 "older", "elderly"]
    VOICE_ACCENTS = ["neutral American", "British", "Australian", "Irish",
                     "Scottish", "Indian English", "neutral, no strong "
                     "regional accent"]
    VOICE_PACES = ["slow and deliberate", "measured, unhurried", "brisk",
                   "energetic"]
    VOICE_TONES = ["warm and friendly", "dry and precise", "authoritative",
                   "calm and soothing", "formal", "conversational",
                   "enthusiastic"]

    def compose_voice_description(gender, age, accent, pace, tone, extra):
        desc = (f"A {age} {gender} voice, {accent} accent, {pace} pace, "
               f"{tone} tone.")
        extra = extra.strip()
        if extra:
            desc += " " + (extra if extra.endswith((".", "!", "?"))
                          else extra + ".")
        return desc

    def open_voice_builder():
        saved = settings.get("qwen_voice_builder", {})

        win = tk.Toplevel(root)
        win.title("Build a voice")
        win.geometry("520x420")
        win.transient(root)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame,
                 text="Qwen3 takes a written description, not numeric "
                      "settings -- these choices get combined into one for "
                      "you, and you can still edit the result by hand "
                      "afterward.",
                 foreground="#666", wraplength=480,
                 justify="left").pack(anchor="w", pady=(0, 10))

        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        fields = {}

        def add_row(r, label, options, key):
            ttk.Label(grid, text=label).grid(
                row=r, column=0, sticky="w", pady=4)
            var = tk.StringVar(value=saved.get(key, options[0]))
            box = ttk.Combobox(grid, textvariable=var, values=options,
                               state="readonly")
            box.grid(row=r, column=1, sticky="ew", padx=8, pady=4)
            box.bind("<<ComboboxSelected>>", lambda e: refresh_preview())
            fields[key] = var

        add_row(0, "Gender", VOICE_GENDERS, "gender")
        add_row(1, "Age", VOICE_AGES, "age")
        add_row(2, "Accent", VOICE_ACCENTS, "accent")
        add_row(3, "Pace", VOICE_PACES, "pace")
        add_row(4, "Tone", VOICE_TONES, "tone")

        ttk.Label(grid, text="Extra notes").grid(
            row=5, column=0, sticky="nw", pady=4)
        extra_var = tk.StringVar(value=saved.get("extra", ""))
        extra_entry = ttk.Entry(grid, textvariable=extra_var)
        extra_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=4)
        ttk.Label(grid, text="Optional -- anything not covered above, e.g. "
                            "\"slight vocal fry\" or \"reads like a "
                            "documentary narrator\".",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=380, justify="left").grid(
            row=6, column=1, sticky="w", padx=8)

        ttk.Label(frame, text="Preview", font=("TkDefaultFont", 9, "bold")
                 ).pack(anchor="w", pady=(12, 2))
        preview = tk.Text(frame, height=4, wrap="word",
                          font=("TkDefaultFont", 9))
        preview.pack(fill="x")

        def refresh_preview(*_):
            desc = compose_voice_description(
                fields["gender"].get(), fields["age"].get(),
                fields["accent"].get(), fields["pace"].get(),
                fields["tone"].get(), extra_var.get())
            preview.config(state="normal")
            preview.delete("1.0", "end")
            preview.insert("1.0", desc)

        extra_entry.bind("<KeyRelease>", refresh_preview)
        refresh_preview()

        def apply_and_close():
            desc = preview.get("1.0", "end").strip()
            voice_var.set(desc)
            settings["qwen_voice_builder"] = {
                k: v.get() for k, v in fields.items()
            }
            settings["qwen_voice_builder"]["extra"] = extra_var.get()
            save_settings(settings)
            _remember_voice()
            win.destroy()

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Use this voice",
                  command=apply_and_close).pack(side="right")
        ttk.Button(btns, text="Cancel",
                  command=win.destroy).pack(side="right", padx=6)

    def open_fix_chunk_dialog():
        # Same take the Publish tab is pointed at, so after a batch run
        # this fixes the one you actually mean rather than always the
        # last one to finish.
        lr = current_take()
        if not lr:
            messagebox.showinfo(
                "Nothing to fix yet",
                "Generate audio first -- this fixes one chunk of a "
                "finished take, in place. After a queue run, pick which "
                "take on the Publish tab.")
            return

        win = tk.Toplevel(root)
        win.title("Fix a chunk or a sentence")
        win.geometry("700x640")
        win.transient(root)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame,
                 text=f"Fixing: {os.path.basename(lr['out_path'])}",
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(frame,
                 text="Pick the chunk, then the sentence that sounds wrong. "
                      "Edit it (a respelling from the pronunciation dictionary "
                      "applies here too) and regenerate just that sentence -- "
                      "it is spliced back in; everything else is untouched. "
                      "Regenerating the whole chunk is still available.",
                 foreground="#666", wraplength=600,
                 justify="left").pack(anchor="w", pady=(2, 10))

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        listbox = tk.Listbox(body, height=10, exportselection=False)
        listbox.pack(side="left", fill="both", expand=True)
        listscroll = ttk.Scrollbar(body, orient="vertical",
                                   command=listbox.yview)
        listscroll.pack(side="left", fill="y")
        listbox.config(yscrollcommand=listscroll.set)

        def refresh_list():
            listbox.delete(0, "end")
            for i, text in enumerate(lr["result"]["chunk_texts"], 1):
                preview = text.strip().replace("\n", " ")
                if len(preview) > 70:
                    preview = preview[:67] + "..."
                listbox.insert("end", f"{i:>3}.  {preview}")

        refresh_list()

        ttk.Label(frame, text="Sentences in this chunk").pack(
            anchor="w", pady=(8, 2))
        sbody = ttk.Frame(frame)
        sbody.pack(fill="both", expand=True)
        sentbox = tk.Listbox(sbody, height=7, exportselection=False)
        sentbox.pack(side="left", fill="both", expand=True)
        sscroll = ttk.Scrollbar(sbody, orient="vertical",
                                command=sentbox.yview)
        sscroll.pack(side="left", fill="y")
        sentbox.config(yscrollcommand=sscroll.set)

        def chunk_segments(i):
            r = lr["result"]
            segs = (r.get("segments") or [None] * len(r["chunk_paths"]))[i]
            if not segs:
                from .segments import load_segments
                segs = load_segments(r["chunk_paths"][i], r["chunk_texts"][i],
                                     r["chunk_durations"][i])
            return segs

        def refresh_sentences(i):
            sentbox.delete(0, "end")
            for k, seg in enumerate(chunk_segments(i), 1):
                preview = seg["text"].strip().replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                sentbox.insert(
                    "end", f"{k:>3}. [{seg['start']:6.1f}s] {preview}")

        editbox_label = ttk.Label(frame, text="Text for this chunk")
        editbox_label.pack(anchor="w", pady=(10, 2))
        editbox = tk.Text(frame, height=5, wrap="word")
        editbox.pack(fill="x")

        status_label = ttk.Label(frame, text="", foreground="#666")
        status_label.pack(anchor="w", pady=(6, 0))

        def on_select(_=None):
            sel = listbox.curselection()
            if not sel:
                return
            i = sel[0]
            editbox.delete("1.0", "end")
            editbox.insert("1.0", lr["result"]["chunk_texts"][i])
            editbox_label.config(text="Text for this chunk")
            refresh_sentences(i)

        def on_select_sentence(_=None):
            sel, ssel = listbox.curselection(), sentbox.curselection()
            if not sel or not ssel:
                return
            seg = chunk_segments(sel[0])[ssel[0]]
            editbox.delete("1.0", "end")
            editbox.insert("1.0", seg["text"])
            editbox_label.config(
                text=f"Text for sentence {ssel[0] + 1} of chunk {sel[0] + 1}")

        listbox.bind("<<ListboxSelect>>", on_select)
        sentbox.bind("<<ListboxSelect>>", on_select_sentence)
        if lr["result"]["chunk_texts"]:
            listbox.selection_set(0)
            on_select()

        def play_selected():
            sel = listbox.curselection()
            if not sel:
                return
            path = lr["result"]["chunk_paths"][sel[0]]
            if os.path.exists(path):
                reveal_file(path)
            else:
                status_label.config(
                    text="That chunk's cached audio is gone (cache was "
                         "cleared); regenerate it to hear the fix.")

        def play_sentence():
            sel, ssel = listbox.curselection(), sentbox.curselection()
            if not sel or not ssel:
                return
            path = lr["result"]["chunk_paths"][sel[0]]
            if not path.lower().endswith(".wav") or not os.path.exists(path):
                play_selected()
                return
            seg = chunk_segments(sel[0])[ssel[0]]
            out = os.path.join(tempfile.gettempdir(),
                               f"narrator_sentence_{sel[0] + 1}_{ssel[0] + 1}.wav")
            try:
                reveal_file(export_span(path, seg["start"], seg["end"], out))
            except Exception as exc:
                status_label.config(text=f"Couldn't extract it: {exc}")

        def run_sentence_fix(retry):
            sel, ssel = listbox.curselection(), sentbox.curselection()
            if not sel or not ssel:
                status_label.config(text="Pick a sentence first.")
                return
            i, k = sel[0], ssel[0]
            new_text = editbox.get("1.0", "end").strip()
            if not new_text:
                messagebox.showwarning("Empty text",
                                       "Can't regenerate an empty sentence.")
                return
            for b in (regen_btn, close_btn, sent_btn, again_btn):
                b.config(state="disabled")
            status_label.config(text="Regenerating that sentence and "
                                     "splicing it in...")
            win.update_idletasks()

            def work():
                try:
                    out = resplice_segment(lr, i, k, new_text, log,
                                           retry=retry)
                    def done():
                        refresh_list()
                        listbox.selection_set(i)
                        refresh_sentences(i)
                        sentbox.selection_set(k)
                        status_label.config(
                            text=f"Done. Updated: {os.path.basename(out)}"
                            if out else "Something went wrong; see the main "
                                        "progress log.")
                        for b in (regen_btn, close_btn, sent_btn, again_btn):
                            b.config(state="normal")
                    win.after(0, done)
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    def failed():
                        status_label.config(text=f"Failed: {msg}")
                        for b in (regen_btn, close_btn, sent_btn, again_btn):
                            b.config(state="normal")
                    win.after(0, failed)

            threading.Thread(target=work, daemon=True).start()

        btnrow = ttk.Frame(frame)
        btnrow.pack(fill="x", pady=(8, 0))
        ttk.Button(btnrow, text="Play sentence",
                  command=play_sentence).pack(side="left")
        sent_btn = ttk.Button(btnrow, text="Regenerate this sentence",
                              command=lambda: run_sentence_fix(0))
        sent_btn.pack(side="left", padx=6)
        # Same text, different roll: for a sentence that was worded fine but
        # came out oddly. Counts up so each press is a genuinely new try.
        retry_count = {"n": 0}
        def try_again():
            retry_count["n"] += 1
            run_sentence_fix(retry_count["n"])
        again_btn = ttk.Button(btnrow, text="Try again (same text)",
                               command=try_again)
        again_btn.pack(side="left")
        ttk.Separator(btnrow, orient="vertical").pack(side="left", fill="y",
                                                       padx=10)
        ttk.Button(btnrow, text="Play chunk",
                  command=play_selected).pack(side="left")

        def do_regenerate():
            sel = listbox.curselection()
            if not sel:
                return
            i = sel[0]
            new_text = editbox.get("1.0", "end").strip()
            if not new_text:
                messagebox.showwarning("Empty text",
                                       "Can't regenerate an empty chunk.")
                return
            if sentbox.curselection() and not messagebox.askyesno(
                    "Whole chunk?",
                    "The text box currently holds ONE sentence. Regenerate "
                    "the whole chunk from just that text?\n\n(Use "
                    "'Regenerate this sentence' to fix only the sentence.)",
                    parent=win):
                return

            for b in (regen_btn, close_btn):
                b.config(state="disabled")
            status_label.config(text="Regenerating this chunk and "
                                     "rebuilding the take...")
            win.update_idletasks()

            def work():
                try:
                    out = resplice_chunk(lr, i, new_text, log)
                    def done():
                        refresh_list()
                        listbox.selection_set(i)
                        status_label.config(
                            text=f"Done. Updated: {os.path.basename(out)}"
                            if out else "Something went wrong; see the main "
                                        "progress log.")
                        for b in (regen_btn, close_btn):
                            b.config(state="normal")
                    win.after(0, done)
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    def failed():
                        status_label.config(text=f"Failed: {msg}")
                        for b in (regen_btn, close_btn):
                            b.config(state="normal")
                    win.after(0, failed)

            threading.Thread(target=work, daemon=True).start()

        regen_btn = ttk.Button(btnrow, text="Regenerate chunk",
                               command=do_regenerate)
        regen_btn.pack(side="left", padx=6)
        close_btn = ttk.Button(btnrow, text="Close", command=win.destroy)
        close_btn.pack(side="right")

    def require_components(*keys, feature="This"):
        """True if every named component is present. Otherwise explains
        what's missing and offers the Components dialog, rather than
        letting the feature fail partway through."""
        missing = components_mod.missing_for(*keys)
        if not missing:
            return True
        labels = ", ".join(components_mod.COMPONENTS[k]["label"]
                          for k in missing)
        if messagebox.askyesno(
                "Something's missing",
                f"{feature} needs: {labels}.\n\nOpen Components and "
                "add-ons to install it?", parent=root):
            open_components_dialog()
        return False

    def open_components_dialog():
        """What's installed, what each piece unlocks, and a one-click
        install for the ones that can be installed automatically.

        Narrator runs without any of these; this exists so a feature that
        needs something says so up front instead of failing when clicked.
        """
        win = tk.Toplevel(root)
        win.title("Components and add-ons")
        win.geometry("880x620")
        win.transient(root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame,
                 text="Narrator works without any of these. Each one "
                      "unlocks the features listed beside it. Licences are "
                      "shown because some carry conditions if you pass the "
                      "program on -- that's information, not legal advice.",
                 foreground="#666", wraplength=840, justify="left").pack(
            anchor="w")

        listframe = ttk.Frame(frame)
        listframe.pack(fill="both", expand=True, pady=(8, 0))
        clist = tk.Listbox(listframe, height=11, exportselection=False,
                           font=("TkFixedFont", 9))
        clist.pack(side="left", fill="both", expand=True)
        csb = ttk.Scrollbar(listframe, orient="vertical",
                            command=clist.yview)
        csb.pack(side="left", fill="y")
        clist.config(yscrollcommand=csb.set)

        detail = ttk.LabelFrame(frame, text="Details", padding=8)
        detail.pack(fill="x", pady=(8, 0))
        detail_lbl = ttk.Label(detail, text="Pick a component.",
                              wraplength=830, justify="left")
        detail_lbl.pack(anchor="w")
        bar = ttk.Progressbar(detail, mode="determinate", maximum=100)
        status = ttk.Label(detail, text="", wraplength=830, justify="left")
        status.pack(anchor="w", pady=(6, 0))

        btnrow = ttk.Frame(frame)
        btnrow.pack(fill="x", pady=(8, 0))
        install_btn = ttk.Button(btnrow, text="Install")
        install_btn.pack(side="left")
        page_btn = ttk.Button(btnrow, text="Open download page")
        page_btn.pack(side="left", padx=6)
        ttk.Button(btnrow, text="Re-check", command=lambda: refresh()).pack(
            side="left")
        ttk.Button(btnrow, text="Close", command=win.destroy).pack(
            side="right")

        def refresh(*_):
            keep = clist.curselection()
            clist.delete(0, "end")
            entries = components_mod.report()
            clist._entries = entries
            for e in entries:
                mark = "installed" if e["installed"] else (
                    "REQUIRED " if e.get("essential") else "optional ")
                clist.insert("end",
                            f"{mark:<10} {e['label']:<26} {e['size']:<14} "
                            f"{e['licence']}")
            if keep:
                clist.selection_set(keep[0])
                show()

        def current():
            sel = clist.curselection()
            if not sel or not getattr(clist, "_entries", None):
                return None
            return clist._entries[sel[0]]

        def show(*_):
            e = current()
            if not e:
                return
            enables = "\n".join(f"   - {x}" for x in e["enables"])
            state_line = ("Installed: " + e["detail"] if e["installed"]
                         else "Not installed: " + e["detail"])
            detail_lbl.config(
                text=f"{e['label']}   ({e['licence']}, {e['size']})\n"
                     f"{state_line}\n\nUnlocks:\n{enables}"
                     + (f"\n\n{e['hint']}" if e.get("hint") else ""))
            can_auto = e["kind"] == "python" and not e["installed"]
            install_btn.config(
                state="normal" if can_auto else "disabled",
                text="Install" if can_auto else
                     ("Already installed" if e["installed"]
                      else "Install manually"))
            page_btn.config(state="normal" if e.get("url") else "disabled")
            status.config(text="")

        def do_open_page():
            e = current()
            if e and e.get("url"):
                import webbrowser
                webbrowser.open(e["url"])

        def do_install():
            e = current()
            if not e or e["kind"] != "python":
                return
            install_btn.config(state="disabled")
            bar.pack(fill="x", pady=(6, 0))
            bar["value"] = 0
            status.config(text=f"Installing {e['label']}...",
                         foreground="#000")
            clear_log()
            set_running(True)

            def on_progress(fraction):
                root.after(0, lambda: bar.config(value=fraction * 100))

            def work():
                try:
                    components_mod.install_python_component(
                        e["key"], log, on_progress)
                    def done():
                        bar.pack_forget()
                        status.config(
                            text=f"{e['label']} is ready. The features it "
                                 "unlocks are available now.",
                            foreground="#060")
                        refresh()
                    root.after(0, done)
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    log("Install failed: " + msg)
                    def failed():
                        bar.pack_forget()
                        status.config(text=msg, foreground="#a00")
                        install_btn.config(state="normal")
                    root.after(0, failed)
                finally:
                    root.after(0, lambda: set_running(False))
            threading.Thread(target=work, daemon=True).start()

        clist.bind("<<ListboxSelect>>", show)
        install_btn.config(command=do_install)
        page_btn.config(command=do_open_page)
        refresh()

    def open_voice_studio():
        """Manage the Qwen3 voices on disk: audition a description without
        rendering a document, clone one from your own recording, play,
        label, delete, or load one into the Voice tab."""
        win = tk.Toplevel(root)
        win.title("Voice studio")
        win.geometry("820x600")
        win.transient(root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame,
                 text="Voices are saved the first time they're used and "
                      "reused after that, so the same description and take "
                      "always give the same narrator.",
                 foreground="#666", wraplength=780, justify="left").pack(
            anchor="w")

        listframe = ttk.Frame(frame)
        listframe.pack(fill="both", expand=True, pady=(8, 0))
        vlist = tk.Listbox(listframe, height=10, exportselection=False,
                           font=("TkFixedFont", 9))
        vlist.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(listframe, orient="vertical",
                            command=vlist.yview)
        vsb.pack(side="left", fill="y")
        vlist.config(yscrollcommand=vsb.set)
        status = ttk.Label(frame, text="", wraplength=780, justify="left")
        status.pack(anchor="w", pady=(6, 0))

        def refresh(*_):
            vlist.delete(0, "end")
            voices = saved_voices()
            vlist._voices = voices
            for v in voices:
                when = datetime.datetime.fromtimestamp(
                    v["created"]).strftime("%Y-%m-%d")
                label = f"[{v['label']}] " if v["label"] else ""
                kind = {"cloned": "clone ", "custom": "preset"}.get(
                    v["kind"], "design")
                # Two engines can now clone voices, and a voice made for
                # one is unusable on the other -- shown plainly here
                # rather than left to fail deep inside a render.
                engine_tag = f"[{v.get('engine', 'qwen3')}] "
                desc = v["description"]
                if len(desc) > 40:
                    desc = desc[:37] + "..."
                take_s = f"t{v['take']}" if v["take"] else "    "
                vlist.insert("end", f"{kind} {take_s} {when}  "
                                    f"{engine_tag}{label}{desc}")
            if not voices:
                status.config(
                    text="No saved voices yet. Audition a description "
                         "below, or clone one from a recording.",
                    foreground="#666")

        def picked():
            sel = vlist.curselection()
            if not sel or not getattr(vlist, "_voices", None):
                status.config(text="Pick a voice first.", foreground="#a00")
                return None
            return vlist._voices[sel[0]]

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(8, 0))

        def do_play():
            v = picked()
            if not v:
                return
            if not v.get("reference"):
                status.config(
                    text="CustomVoice presets have no reference clip -- "
                         "they're a fixed speaker from the model itself, "
                         "not something recorded or designed.",
                    foreground="#666")
                return
            reveal_file(v["reference"])

        def do_use():
            v = picked()
            if not v:
                return
            engine_var.set(next(n for n, sp in ENGINES.items()
                               if sp["key"] == "qwen3"))
            refresh_voices()
            refresh_option_visibility()
            if v["kind"] == "custom":
                voice_var.set(encode_custom_voice(v["speaker"],
                                                  v["instruct"]))
                status.config(
                    text="Loaded into the Voice tab. CustomVoice presets "
                         "don't use the take number -- the speaker is "
                         "fixed, not designed.", foreground="#060")
            else:
                voice_var.set(v["description"])
                take_var.set(v["take"])
                status.config(
                    text="Loaded into the Voice tab. Its take was set "
                         "too, since description and take together "
                         "identify the voice.", foreground="#060")

        def do_label():
            v = picked()
            if not v:
                return
            dlg = tk.Toplevel(win)
            dlg.title("Label this voice")
            dlg.transient(win)
            f2 = ttk.Frame(dlg, padding=12)
            f2.pack(fill="both", expand=True)
            ttk.Label(f2, text="A short name to recognise it by:").pack(
                anchor="w")
            var = tk.StringVar(value=v["label"])
            ent = ttk.Entry(f2, textvariable=var, width=40)
            ent.pack(fill="x", pady=6)
            ent.focus_set()

            def save():
                try:
                    rename_voice(v["folder"], var.get().strip())
                except Exception as exc:
                    status.config(text=str(exc), foreground="#a00")
                dlg.destroy()
                refresh()
            ttk.Button(f2, text="Save", command=save).pack(side="left")
            ttk.Button(f2, text="Cancel", command=dlg.destroy).pack(
                side="right")

        def do_delete():
            v = picked()
            if not v:
                return
            if v["kind"] == "custom":
                if not messagebox.askyesno(
                        "Remove this preset",
                        f"Remove the saved preset '{v['label']}'? The "
                        "speaker itself is part of the model, not this "
                        "app -- this only forgets the label and "
                        "instruction you saved.", parent=win):
                    return
                delete_custom_voice_preset(v["label"])
                status.config(text="Removed.", foreground="#060")
                refresh()
                return
            if not messagebox.askyesno(
                    "Delete this voice",
                    f"Delete the saved voice for:\n\n{v['description']}\n"
                    f"(take {v['take']})\n\nAudio already rendered with "
                    "it is untouched. Re-rendering the same description "
                    "and take will design it again -- for a designed "
                    "voice that reproduces it, but a CLONED voice cannot "
                    "be rebuilt without the original recording.",
                    parent=win):
                return
            try:
                delete_voice(v["folder"])
                status.config(text="Deleted.", foreground="#060")
            except Exception as exc:
                status.config(text=f"Couldn't delete it: {exc}",
                             foreground="#a00")
            refresh()

        ttk.Button(row, text="Play reference", command=do_play).pack(
            side="left")
        ttk.Button(row, text="Use in Voice tab", command=do_use).pack(
            side="left", padx=6)
        ttk.Button(row, text="Label...", command=do_label).pack(side="left")
        ttk.Button(row, text="Delete", command=do_delete).pack(side="left",
                                                               padx=6)
        ttk.Button(row, text="Refresh", command=refresh).pack(side="right")

        nb = ttk.Notebook(frame)
        nb.pack(fill="x", pady=(12, 0))

        aud = ttk.Frame(nb, padding=10)
        nb.add(aud, text="Audition a description")
        ttk.Label(aud,
                 text="Designs the voice and plays its reference clip, "
                      "without narrating a document. Takes a minute or so "
                      "the first time.",
                 foreground="#666", wraplength=760, justify="left").pack(
            anchor="w")
        aud_desc = tk.StringVar(value=voice_var.get())
        ttk.Entry(aud, textvariable=aud_desc).pack(fill="x", pady=6)
        arow = ttk.Frame(aud)
        arow.pack(fill="x")
        ttk.Label(arow, text="Take").pack(side="left")
        aud_take = tk.IntVar(value=1)
        ttk.Spinbox(arow, from_=1, to=99, width=4,
                    textvariable=aud_take).pack(side="left", padx=6)
        aud_btn = ttk.Button(arow, text="Audition")
        aud_btn.pack(side="left")

        def do_audition():
            desc = aud_desc.get().strip()
            if not desc:
                status.config(text="Describe the voice first.",
                             foreground="#a00")
                return
            aud_btn.config(state="disabled")
            status.config(text="Designing -- progress is in the main log.",
                         foreground="#000")
            clear_log()
            set_running(True)

            def work():
                try:
                    ref, _ = ensure_qwen_voice(desc, int(aud_take.get()), log)
                    root.after(0, lambda: (
                        status.config(text="Done -- playing the reference "
                                          "clip.", foreground="#060"),
                        aud_btn.config(state="normal"), refresh(),
                        reveal_file(ref)))
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    log("Audition failed: " + msg)
                    root.after(0, lambda: (
                        status.config(text=msg, foreground="#a00"),
                        aud_btn.config(state="normal")))
                finally:
                    root.after(0, lambda: set_running(False))
            threading.Thread(target=work, daemon=True).start()
        aud_btn.config(command=do_audition)

        clone = ttk.Frame(nb, padding=10)
        nb.add(clone, text="Clone from a recording")
        ttk.Label(clone,
                 text="Record a few seconds of clear speech, then type "
                      "exactly what you said -- Qwen3 matches the words "
                      "against the audio to learn the voice. Nothing "
                      "leaves this machine.",
                 foreground="#666", wraplength=760, justify="left").pack(
            anchor="w")
        crow = ttk.Frame(clone)
        crow.pack(fill="x", pady=6)
        clone_path = tk.StringVar()
        ttk.Entry(crow, textvariable=clone_path).pack(side="left", fill="x",
                                                      expand=True)
        ttk.Button(crow, text="Browse...",
                  command=lambda: clone_path.set(
                      filedialog.askopenfilename(
                          title="Choose a recording", parent=win,
                          filetypes=[("Audio", "*.wav *.flac *.mp3 *.m4a"),
                                    ("All files", "*.*")]) or clone_path.get()
                  )).pack(side="left", padx=6)
        ttk.Label(clone, text="Exactly what you said:").pack(anchor="w")
        clone_text = tk.StringVar()
        ttk.Entry(clone, textvariable=clone_text).pack(fill="x", pady=(2, 6))
        ttk.Label(clone, text="A name for this voice:").pack(anchor="w")
        clone_desc = tk.StringVar()
        ttk.Entry(clone, textvariable=clone_desc).pack(fill="x", pady=(2, 6))
        clone_btn = ttk.Button(clone, text="Save this voice")
        clone_btn.pack(anchor="w")

        def do_clone():
            try:
                folder = clone_voice_from_recording(
                    clone_path.get().strip(), clone_text.get(),
                    clone_desc.get().strip() or "my own voice", log)
            except Exception as exc:
                status.config(text=str(exc), foreground="#a00")
                return
            status.config(
                text=f"Saved. It's in the list now, and works like any "
                     "other voice.", foreground="#060")
            log(f"Cloned voice saved: {folder}")
            refresh()
        clone_btn.config(command=do_clone)

        custom = ttk.Frame(nb, padding=10)
        nb.add(custom, text="CustomVoice (preset speakers)")
        ttk.Label(custom,
                 text="Qwen3's fixed studio speakers, plus an optional "
                      "instruction for how to read it (e.g. \"speak "
                      "slowly and warmly\"). The speaker list isn't in "
                      "the package -- fetching it downloads the "
                      "CustomVoice model itself (several GB, one time).",
                 foreground="#666", wraplength=760, justify="left").pack(
            anchor="w")
        crow1 = ttk.Frame(custom)
        crow1.pack(fill="x", pady=6)
        ttk.Label(crow1, text="Speaker").pack(side="left")
        speaker_var = tk.StringVar()
        speaker_menu = ttk.Combobox(crow1, textvariable=speaker_var,
                                    state="readonly", width=30,
                                    values=qwen_custom_speakers())
        speaker_menu.pack(side="left", padx=6)
        fetch_btn = ttk.Button(crow1, text="Fetch speaker list...")
        fetch_btn.pack(side="left")

        def do_fetch_speakers():
            fetch_btn.config(state="disabled")
            status.config(text="Fetching the speaker list -- progress is "
                              "in the main log.", foreground="#000")
            clear_log()
            set_running(True)

            def work():
                try:
                    speakers = fetch_qwen_custom_speakers(log)
                    save_qwen_custom_speakers(speakers)
                    def done():
                        speaker_menu.config(values=speakers)
                        if speakers:
                            speaker_var.set(speakers[0])
                        status.config(
                            text=f"Found {len(speakers)} speaker(s).",
                            foreground="#060")
                        fetch_btn.config(state="normal")
                    root.after(0, done)
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    log("Fetching speakers failed: " + msg)
                    root.after(0, lambda: (
                        status.config(text=msg, foreground="#a00"),
                        fetch_btn.config(state="normal")))
                finally:
                    root.after(0, lambda: set_running(False))
            threading.Thread(target=work, daemon=True).start()
        fetch_btn.config(command=do_fetch_speakers)

        ttk.Label(custom, text="Instruction (optional)").pack(anchor="w")
        instruct_var = tk.StringVar()
        ttk.Entry(custom, textvariable=instruct_var).pack(fill="x",
                                                          pady=(2, 6))
        ttk.Label(custom, text="A name to save this as:").pack(anchor="w")
        preset_label_var = tk.StringVar()
        ttk.Entry(custom, textvariable=preset_label_var).pack(fill="x",
                                                              pady=(2, 6))
        crow2 = ttk.Frame(custom)
        crow2.pack(fill="x")
        save_preset_btn = ttk.Button(crow2, text="Save as preset")
        save_preset_btn.pack(side="left")
        use_now_btn = ttk.Button(crow2, text="Use in Voice tab now")
        use_now_btn.pack(side="left", padx=6)

        def do_save_preset():
            speaker = speaker_var.get().strip()
            label = preset_label_var.get().strip()
            if not speaker:
                status.config(
                    text="Fetch the speaker list and pick one first.",
                    foreground="#a00")
                return
            if not label:
                status.config(text="Give it a name to save it under.",
                             foreground="#a00")
                return
            save_custom_voice_preset(label, speaker, instruct_var.get())
            status.config(text=f"Saved '{label}'.", foreground="#060")
            refresh()
        save_preset_btn.config(command=do_save_preset)

        def do_use_custom_now():
            speaker = speaker_var.get().strip()
            if not speaker:
                status.config(
                    text="Fetch the speaker list and pick one first.",
                    foreground="#a00")
                return
            engine_var.set(next(n for n, sp in ENGINES.items()
                               if sp["key"] == "qwen3"))
            refresh_voices()
            refresh_option_visibility()
            voice_var.set(encode_custom_voice(speaker, instruct_var.get()))
            status.config(text="Loaded into the Voice tab.",
                         foreground="#060")
        use_now_btn.config(command=do_use_custom_now)

        ttk.Button(frame, text="Close", command=win.destroy).pack(
            side="bottom", anchor="e", pady=(10, 0))
        refresh()

    def open_timeline_editor(manifest_path=None):
        """The timeline: a waveform of the finished take with every
        sentence marked, click to place the playhead, drag to select a
        range, and the full text below with the sentence under the
        playhead highlighted. Selecting anywhere -- on the waveform or in
        the text -- picks the same sentence, because both are views of the
        same manifest.
        """
        if manifest_path:
            try:
                lr = load_manifest(manifest_path)
            except Exception as exc:
                messagebox.showerror(
                    "Couldn't open that take",
                    f"{type(exc).__name__}: {exc}", parent=root)
                return
        else:
            lr = current_take()
        if not lr or not os.path.isfile(lr.get("out_path", "")):
            messagebox.showinfo(
                "Nothing to edit yet",
                "Render something first, or use Open a take... to load a "
                "manifest from an earlier session.")
            return

        flat, man = session_mod.flatten_take(lr)
        if not flat:
            messagebox.showinfo("Nothing to edit",
                               "That take has no sentence information.")
            return
        total = max(man["duration"], flat[-1]["end"]) or 1.0

        win = tk.Toplevel(root)
        win.title(f"Timeline -- {os.path.basename(lr['out_path'])}")
        win.geometry("980x660")
        win.transient(root)
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        W, H = 940, 130
        canvas = tk.Canvas(frame, width=W, height=H, bg="#1b1b1b",
                          highlightthickness=1, highlightbackground="#444")
        canvas.pack(fill="x")
        pos_lbl = ttk.Label(frame, text="", foreground="#666",
                           font=("TkDefaultFont", 8))
        pos_lbl.pack(anchor="w", pady=(2, 6))

        state_t = {"env": [], "sel": 0, "drag": None,
                  "range": None}      # range = (start, end) seconds

        def x_for(t):
            return (t / total) * W

        def t_for(x):
            return max(0.0, min(total, (x / W) * total))

        def draw():
            canvas.delete("all")
            env = state_t["env"]
            mid = H / 2
            if env:
                step = W / len(env)
                for i, v in enumerate(env):
                    x = i * step
                    h = v * (H / 2 - 6)
                    canvas.create_line(x, mid - h, x, mid + h,
                                      fill="#3d6d8f")
            else:
                canvas.create_text(W / 2, mid, fill="#888",
                                  text="reading waveform...")
            # sentence boundaries
            for item in flat:
                x = x_for(item["start"])
                canvas.create_line(x, 0, x, H, fill="#2f2f2f")
            rng = state_t["range"]
            if rng:
                canvas.create_rectangle(x_for(rng[0]), 0, x_for(rng[1]), H,
                                       fill="#4ea3ff", stipple="gray25",
                                       outline="")
            cur = flat[state_t["sel"]]
            canvas.create_rectangle(x_for(cur["start"]), 0,
                                   x_for(cur["end"]), H,
                                   outline="#ffd24d", width=2)
            ph = state_t.get("playhead", cur["start"])
            canvas.create_line(x_for(ph), 0, x_for(ph), H, fill="#ff7b4d",
                              width=1)

        def fmt(t):
            return f"{int(t) // 60}:{t % 60:05.2f}"

        def select_index(i, from_canvas=False):
            state_t["sel"] = max(0, min(len(flat) - 1, i))
            cur = flat[state_t["sel"]]
            listbox.selection_clear(0, "end")
            listbox.selection_set(state_t["sel"])
            listbox.see(state_t["sel"])
            editbox.delete("1.0", "end")
            editbox.insert("1.0", cur["text"])
            if state_t.get("ready"):
                refresh_words()
            rng = state_t["range"]
            pos_lbl.config(
                text=f"sentence {state_t['sel'] + 1} of {len(flat)}   "
                     f"{fmt(cur['start'])} - {fmt(cur['end'])}   "
                     f"(chunk {cur['chunk'] + 1})"
                     + (f"   selection {fmt(rng[0])} - {fmt(rng[1])}"
                        if rng else ""))
            draw()

        def index_at(t):
            return session_mod.sentence_at(flat, t)

        def on_press(ev):
            state_t["drag"] = t_for(ev.x)
            state_t["range"] = None
            state_t["playhead"] = state_t["drag"]

        def on_move(ev):
            if state_t["drag"] is None:
                return
            a, b = state_t["drag"], t_for(ev.x)
            if abs(b - a) > 0.05:
                state_t["range"] = (min(a, b), max(a, b))
                draw()

        def on_release(ev):
            if state_t["drag"] is None:
                return
            a, b = state_t["drag"], t_for(ev.x)
            state_t["drag"] = None
            if abs(b - a) <= 0.05:
                state_t["range"] = None
                state_t["playhead"] = a
                select_index(index_at(a), from_canvas=True)
            else:
                state_t["range"] = (min(a, b), max(a, b))
                select_index(index_at(min(a, b)), from_canvas=True)

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_release)

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        listframe = ttk.Frame(body)
        listframe.pack(side="left", fill="both", expand=True)
        listbox = tk.Listbox(listframe, height=12, exportselection=False,
                             font=("TkFixedFont", 9))
        listbox.pack(side="left", fill="both", expand=True)
        lsb = ttk.Scrollbar(listframe, orient="vertical",
                            command=listbox.yview)
        lsb.pack(side="left", fill="y")
        listbox.config(yscrollcommand=lsb.set)
        for item in flat:
            preview = item["text"].strip().replace("\n", " ")
            if len(preview) > 92:
                preview = preview[:89] + "..."
            listbox.insert("end", f"[{fmt(item['start'])}] {preview}")
        listbox.bind("<<ListboxSelect>>",
                     lambda _e: (listbox.curselection()
                                and select_index(listbox.curselection()[0])))

        side = ttk.Frame(body)
        side.pack(side="left", fill="y", padx=(10, 0))
        ttk.Label(side, text="Selected sentence").pack(anchor="w")
        editbox = scrolledtext.ScrolledText(side, height=6, width=34,
                                            wrap="word",
                                            font=("TkDefaultFont", 9))
        editbox.pack(fill="x")
        status = ttk.Label(side, text="", wraplength=250, justify="left")
        status.pack(anchor="w", pady=(6, 0))

        def play_selection():
            cur = flat[state_t["sel"]]
            rng = state_t["range"] or (cur["start"], cur["end"])
            out = os.path.join(tempfile.gettempdir(),
                              "narrator_timeline_span"
                              + os.path.splitext(lr["out_path"])[1])
            path = extract_span(lr["out_path"], rng[0], rng[1], out, log)
            if path:
                reveal_file(path)
            else:
                status.config(text="Couldn't extract that span.",
                             foreground="#a00")

        def run_fix(retry):
            cur = flat[state_t["sel"]]
            new_text = editbox.get("1.0", "end").strip()
            if not new_text:
                status.config(text="The sentence can't be empty.",
                             foreground="#a00")
                return
            for b in (play_btn, redo_btn, again_btn, pron_btn):
                b.config(state="disabled")
            status.config(text="Re-recording that sentence...",
                         foreground="#000")

            def work():
                try:
                    resplice_segment(lr, cur["chunk"], cur["seg"], new_text,
                                    log, retry=retry)
                    def done():
                        status.config(
                            text="Done. Reopen the timeline to see the "
                                 "updated waveform.", foreground="#060")
                        for b in (play_btn, redo_btn, again_btn, pron_btn):
                            b.config(state="normal")
                    win.after(0, done)
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    def failed():
                        status.config(text=msg, foreground="#a00")
                        for b in (play_btn, redo_btn, again_btn, pron_btn):
                            b.config(state="normal")
                    win.after(0, failed)

            threading.Thread(target=work, daemon=True).start()

        ttk.Label(side, text="Words in this sentence").pack(anchor="w",
                                                            pady=(8, 0))
        wordbox = tk.Listbox(side, height=6, width=34, exportselection=False,
                             font=("TkFixedFont", 8))
        wordbox.pack(fill="x")
        ttk.Label(side,
                 text="How Kokoro pronounces each word right now. "
                      "Double-click one to edit it -- then re-record the "
                      "sentence to hear the change.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=250, justify="left").pack(anchor="w")

        def refresh_words():
            wordbox.delete(0, "end")
            wordbox._words = []
            if lr["engine_key"] != "kokoro":
                wordbox.insert("end",
                              " (per-word detail is Kokoro-only)")
                return
            text = editbox.get("1.0", "end")

            def bg():
                res = kokoro_words_phonemes(words_in(text), log,
                                            load_pronunciations())
                win.after(0, lambda: fill(res))

            def fill(res):
                wordbox.delete(0, "end")
                if res.get("error"):
                    wordbox.insert("end", f" {res['error']}")
                    wordbox._words = []
                    return
                mark = {"override": "*", "dictionary": " ",
                       "guessed": "~", "unknown": "!"}
                for w in res["words"]:
                    wordbox.insert(
                        "end", f"{mark.get(w['source'], ' ')} {w['word']:<16}"
                               f"{w['phonemes'] or '(cannot say)'}")
                wordbox._words = [w["word"] for w in res["words"]]

            threading.Thread(target=bg, daemon=True).start()

        def edit_selected_word():
            words = getattr(wordbox, "_words", None)
            picked = wordbox.curselection()
            if not words or not picked:
                status.config(text="Pick a word first.", foreground="#a00")
                return
            open_word_editor(words[picked[0]])

        # Double-click is convenient but undiscoverable, so the same action
        # also gets a plain button.
        wordbox.bind("<Double-Button-1>", lambda _e: edit_selected_word())
        ttk.Button(side, text="Edit this word...",
                  command=edit_selected_word).pack(fill="x", pady=(2, 0))

        play_btn = ttk.Button(side, text="Play selection",
                              command=play_selection)
        play_btn.pack(fill="x", pady=(8, 2))
        redo_btn = ttk.Button(side, text="Re-record with edits",
                              command=lambda: run_fix(0))
        redo_btn.pack(fill="x", pady=2)
        retry_n = {"n": 0}
        def try_again():
            retry_n["n"] += 1
            run_fix(retry_n["n"])
        again_btn = ttk.Button(side, text="Try again (same text)",
                               command=try_again)
        again_btn.pack(fill="x", pady=2)
        pron_btn = ttk.Button(side, text="Edit a word's pronunciation...",
                              command=lambda: open_word_editor())
        pron_btn.pack(fill="x", pady=2)
        ttk.Label(side,
                 text="Click the waveform to jump to a sentence, or drag "
                      "to select a range. Re-recording replaces just that "
                      "sentence in the finished file.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=250, justify="left").pack(anchor="w",
                                                      pady=(8, 0))

        state_t["ready"] = True
        select_index(0)

        def load_wave():
            env = envelope(lr["out_path"], buckets=W, log=log)
            win.after(0, lambda: (state_t.__setitem__("env", env), draw()))
        threading.Thread(target=load_wave, daemon=True).start()

    def open_take_from_manifest():
        path = filedialog.askopenfilename(
            title="Open a take (its .manifest.json)",
            filetypes=[("Take manifest", "*.manifest.json"),
                      ("All files", "*.*")])
        if path:
            open_timeline_editor(path)

    AUDIO_FILETYPES = [("Audio", "*.mp3 *.m4a *.wav *.flac *.aac *.ogg "
                                "*.opus *.wma *.mp4 *.mkv"),
                       ("All files", "*.*")]

    def open_converter_dialog():
        """Full converter: format, quality, sample rate, depth, channels,
        and optional splitting into numbered parts by length or by a
        maximum file size. Works over a LIST of source files -- one file
        picked normally, several picked with shift/ctrl-click in the same
        dialog, or built up over time with Browse/Add so the dialog never
        has to be closed between one-off conversions. Every file in the
        list is converted with the same settings, one after another."""
        picked = filedialog.askopenfilenames(
            title="Choose one or more audio files to convert",
            filetypes=AUDIO_FILETYPES)
        if not picked:
            return
        sources = list(picked)

        win = tk.Toplevel(root)
        win.title("Convert audio")
        win.geometry("640x620")
        win.transient(root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)

        src_box = ttk.LabelFrame(frame, text="Files to convert", padding=8)
        src_box.pack(fill="x")
        src_list = tk.Listbox(src_box, height=5, exportselection=False,
                              font=("TkDefaultFont", 9))
        src_list.pack(fill="x")
        src_info = ttk.Label(src_box, text="", foreground="#666",
                            font=("TkDefaultFont", 8))
        src_info.pack(anchor="w", pady=(4, 0))
        src_btns = ttk.Frame(src_box)
        src_btns.pack(fill="x", pady=(6, 0))

        def refresh_sources():
            src_list.delete(0, "end")
            total_secs, total_bytes = 0.0, 0
            for p in sources:
                try:
                    secs = duration_of(p) or 0
                    size = os.path.getsize(p)
                    total_secs += secs
                    total_bytes += size
                    src_list.insert(
                        "end", f"{os.path.basename(p)}   "
                              f"({secs / 60:.1f} min, {size / 1e6:.1f} MB)")
                except Exception:
                    src_list.insert("end", os.path.basename(p))
            n = len(sources)
            if n == 0:
                src_info.config(text="No files -- use Browse to add some.")
            elif n == 1:
                src_info.config(
                    text=f"{total_secs / 60:.1f} minutes, "
                        f"{total_bytes / 1e6:.1f} MB")
            else:
                src_info.config(
                    text=f"{n} files -- {total_secs / 60:.1f} minutes, "
                        f"{total_bytes / 1e6:.1f} MB total. Each is "
                        "converted separately with the same settings "
                        "below.")

        def browse_add():
            more = filedialog.askopenfilenames(
                title="Add audio files to convert",
                filetypes=AUDIO_FILETYPES)
            if not more:
                return
            for p in more:
                if p not in sources:
                    sources.append(p)
            refresh_sources()

        def remove_selected():
            sel = list(src_list.curselection())
            for i in reversed(sel):
                del sources[i]
            refresh_sources()

        ttk.Button(src_btns, text="Browse... (add more)",
                  command=browse_add).pack(side="left")
        ttk.Button(src_btns, text="Remove selected",
                  command=remove_selected).pack(side="left", padx=(6, 0))
        refresh_sources()

        out_box = ttk.LabelFrame(frame, text="Output", padding=8)
        out_box.pack(fill="x", pady=(10, 0))
        out_box.columnconfigure(1, weight=1)
        ttk.Label(out_box, text="Format").grid(row=0, column=0, sticky="w",
                                               pady=2)
        fmt_var = tk.StringVar(value=format_var.get())
        fmt_menu = ttk.Combobox(out_box, textvariable=fmt_var,
                                state="readonly", width=42,
                                values=list(AUDIO_FORMATS))
        fmt_menu.grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(out_box, text="Quality").grid(row=1, column=0, sticky="w",
                                                pady=2)
        qrow = ttk.Frame(out_box)
        qrow.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        cq_var = tk.IntVar(value=int(quality_var.get()))
        cq_scale = ttk.Scale(qrow, from_=0, to=100, variable=cq_var,
                             orient="horizontal", length=220)
        cq_scale.pack(side="left")
        cq_lbl = ttk.Label(qrow, text="", width=28, foreground="#666",
                          font=("TkDefaultFont", 8))
        cq_lbl.pack(side="left", padx=6)

        ttk.Label(out_box, text="Sample rate").grid(row=2, column=0,
                                                    sticky="w", pady=2)
        rate_var = tk.StringVar(value="48000")
        ttk.Combobox(out_box, textvariable=rate_var, state="readonly",
                     width=10, values=["22050", "44100", "48000"]).grid(
            row=2, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(out_box, text="Bit depth (WAV/FLAC)").grid(
            row=3, column=0, sticky="w", pady=2)
        depth_var = tk.StringVar(value="16")
        ttk.Combobox(out_box, textvariable=depth_var, state="readonly",
                     width=10, values=["16", "24"]).grid(
            row=3, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(out_box, text="Channels").grid(row=4, column=0, sticky="w",
                                                 pady=2)
        ch_var = tk.StringVar(value="Keep as-is")
        ttk.Combobox(out_box, textvariable=ch_var, state="readonly",
                     width=12,
                     values=["Keep as-is", "Mono", "Stereo"]).grid(
            row=4, column=1, sticky="w", padx=6, pady=2)

        split_box = ttk.LabelFrame(frame, text="Split into parts",
                                   padding=8)
        split_box.pack(fill="x", pady=(10, 0))
        split_mode = tk.StringVar(value="none")
        ttk.Radiobutton(split_box, text="Don't split", variable=split_mode,
                        value="none").grid(row=0, column=0, columnspan=3,
                                           sticky="w")
        ttk.Radiobutton(split_box, text="Every", variable=split_mode,
                        value="time").grid(row=1, column=0, sticky="w")
        mins_var = tk.StringVar(value="20")
        ttk.Spinbox(split_box, from_=1, to=600, width=6,
                    textvariable=mins_var).grid(row=1, column=1, sticky="w")
        ttk.Label(split_box, text="minutes").grid(row=1, column=2,
                                                  sticky="w")
        ttk.Radiobutton(split_box, text="Keep each part under",
                        variable=split_mode, value="size").grid(
            row=2, column=0, sticky="w")
        mb_var = tk.StringVar(value="25")
        ttk.Spinbox(split_box, from_=1, to=2000, width=6,
                    textvariable=mb_var).grid(row=2, column=1, sticky="w")
        ttk.Label(split_box, text="MB").grid(row=2, column=2, sticky="w")
        ttk.Label(split_box,
                 text="Only length can be set directly, so a size limit is "
                      "worked out from the converted file's real bitrate "
                      "and then checked -- if a part still comes out over, "
                      "it splits again more finely.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=560, justify="left").grid(row=3, column=0,
                                                      columnspan=3,
                                                      sticky="w",
                                                      pady=(6, 0))

        status = ttk.Label(frame, text="", wraplength=580, justify="left")
        status.pack(anchor="w", pady=(10, 0))
        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        go = ttk.Button(btns, text="Convert")
        go.pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(
            side="right")

        def describe_quality(*_):
            spec = AUDIO_FORMATS.get(fmt_var.get(), {})
            idx = slider_index(int(cq_var.get()))
            if spec.get("bitrates"):
                cq_lbl.config(text=f"{spec['bitrates'][idx]} kbps")
            elif spec.get("compression_levels"):
                cq_lbl.config(
                    text=f"compression {spec['compression_levels'][idx]} "
                         "(same audio, smaller file)")
            else:
                cq_lbl.config(text="uncompressed -- quality has no effect")
        cq_scale.config(command=describe_quality)
        fmt_menu.bind("<<ComboboxSelected>>", describe_quality)
        describe_quality()

        def do_convert():
            if not sources:
                status.config(text="No files to convert -- add some "
                                   "with Browse first.", foreground="#a00")
                return
            fmt = fmt_var.get()
            spec = AUDIO_FORMATS[fmt]
            channels = {"Mono": 1, "Stereo": 2}.get(ch_var.get())
            mode = split_mode.get()
            try:
                seconds = float(mins_var.get()) * 60
                max_bytes = float(mb_var.get()) * 1_000_000
            except ValueError:
                status.config(text="Those split numbers aren't valid.",
                             foreground="#a00")
                return
            batch = list(sources)  # a snapshot: edits mid-run don't retarget it
            go.config(state="disabled")
            n = len(batch)
            status.config(
                text=(f"Converting 1/{n} -- progress is in the main log."
                     if n > 1 else
                     "Converting -- progress is in the main log."),
                foreground="#000")
            clear_log()
            set_running(True)

            def work():
                made_files, failures = [], []
                for idx, one_src in enumerate(batch, 1):
                    folder = os.path.dirname(one_src) or state["root"]
                    stem = os.path.splitext(os.path.basename(one_src))[0]
                    dst = unique_path(os.path.join(
                        folder, f"{stem}_converted.{spec['ext']}"))
                    prefix = f"[{idx}/{n}] " if n > 1 else ""
                    if n > 1:
                        root.after(0, lambda i=idx: status.config(
                            text=f"Converting {i}/{n} -- progress is in "
                                "the main log.", foreground="#000"))
                    try:
                        log(f"{prefix}Converting "
                           f"{os.path.basename(one_src)} -> {fmt}")
                        out = convert_audio(one_src, dst, fmt,
                                            int(cq_var.get()),
                                            int(rate_var.get()),
                                            int(depth_var.get()), channels,
                                            log)
                        if not out:
                            raise RuntimeError(
                                "Conversion failed -- see the log above.")
                        log(f"  {os.path.basename(out)}, "
                           f"{os.path.getsize(out) / 1e6:.1f} MB")
                        made = out
                        if mode != "none":
                            part_dir = os.path.join(folder,
                                                    f"{stem}_parts")
                            log(f"{prefix}Splitting...")
                            parts = split_audio(
                                out, part_dir, stem, spec["ext"],
                                seconds=seconds if mode == "time"
                                       else None,
                                max_bytes=max_bytes if mode == "size"
                                          else None,
                                log=log)
                            made = parts[0]
                            log(f"  {len(parts)} part(s) in "
                               f"{os.path.basename(part_dir)}")
                        made_files.append(made)
                    except Exception as exc:
                        msg = f"{type(exc).__name__}: {exc}"
                        log(f"{prefix}Failed: {msg}")
                        failures.append((os.path.basename(one_src), msg))
                        # One bad file in a batch shouldn't block the rest
                        # of the list -- each conversion stands alone.
                        continue

                if failures:
                    fail_note = "; ".join(f"{name}: {msg}"
                                         for name, msg in failures)
                    if made_files:
                        note = (f"{len(made_files)}/{n} converted, "
                               f"{len(failures)} failed -- {fail_note}")
                        color = "#a60"
                    else:
                        note = f"All {n} failed -- {fail_note}"
                        color = "#a00"
                elif n > 1:
                    note = f"Done -- all {n} files converted."
                    color = "#060"
                else:
                    note = f"Done -- {os.path.basename(made_files[0])}"
                    color = "#060"
                log("\n" + note)

                def finish():
                    status.config(text=note, foreground=color)
                    go.config(state="normal")
                    if made_files:
                        reveal_file(made_files[-1])
                root.after(0, finish)
                root.after(0, lambda: set_running(False))

            threading.Thread(target=work, daemon=True).start()

        go.config(command=do_convert)

    def open_word_editor(initial_word=None):
        """Edit any word's pronunciation, not only the ones the scanner
        flags. A word can be in Kokoro's dictionary -- so never flagged --
        and still read wrong, which is the case this exists for."""
        win = tk.Toplevel(root)
        win.title("Edit word pronunciation")
        win.geometry("640x560")
        win.transient(root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame,
                 text="Type any word. The list shows dictionary entries as "
                      "you type; words that aren't in the dictionary can "
                      "still be edited -- just type the whole word and "
                      "press Check.",
                 foreground="#666", wraplength=600, justify="left").pack(
            anchor="w")

        searchrow = ttk.Frame(frame)
        searchrow.pack(fill="x", pady=(8, 4))
        ttk.Label(searchrow, text="Word").pack(side="left")
        query_var = tk.StringVar()
        entry = ttk.Entry(searchrow, textvariable=query_var, width=28)
        entry.pack(side="left", padx=6)
        check_btn = ttk.Button(searchrow, text="Check")
        check_btn.pack(side="left")
        count_lbl = ttk.Label(searchrow, text="", foreground="#666",
                             font=("TkDefaultFont", 8))
        count_lbl.pack(side="left", padx=8)

        listframe = ttk.Frame(frame)
        listframe.pack(fill="both", expand=True)
        results = tk.Listbox(listframe, height=11, exportselection=False,
                             font=("TkFixedFont", 9))
        results.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(listframe, orient="vertical",
                           command=results.yview)
        sb.pack(side="left", fill="y")
        results.config(yscrollcommand=sb.set)

        detail = ttk.LabelFrame(frame, text="Pronunciation", padding=8)
        detail.pack(fill="x", pady=(8, 0))
        now_lbl = ttk.Label(detail, text="Pick or check a word.",
                           wraplength=580, justify="left")
        now_lbl.pack(anchor="w")
        ttk.Label(detail,
                 text="Respell it with ordinary words that sound right, "
                      "separated by spaces. Put * before the stressed "
                      "piece.  e.g.  an on nim my *nation",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=580, justify="left").pack(anchor="w",
                                                      pady=(6, 2))
        respell_var = tk.StringVar()
        ttk.Entry(detail, textvariable=respell_var).pack(fill="x")
        preview_lbl = ttk.Label(detail, text="", foreground="#666",
                               font=("TkFixedFont", 9), wraplength=580,
                               justify="left")
        preview_lbl.pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        save_btn = ttk.Button(btns, text="Save override")
        save_btn.pack(side="left")
        clear_btn = ttk.Button(btns, text="Remove override")
        clear_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="Close", command=win.destroy).pack(
            side="right")
        status = ttk.Label(frame, text="", wraplength=600, justify="left")
        status.pack(anchor="w", pady=(6, 0))

        sel = {"word": None}
        pending = {"job": None}

        def overrides():
            return load_pronunciations()

        def show_word(word):
            sel["word"] = word
            info = kokoro_current_phonemes(word, log, overrides())
            if info.get("error"):
                now_lbl.config(text=f"{word}: {info['error']}",
                              foreground="#a00")
                return
            origin = {"override": "your override",
                     "dictionary": "Kokoro's dictionary",
                     "guessed": "guessed (not in the dictionary)"}.get(
                         info["source"], info["source"])
            now_lbl.config(
                text=f"{word}  ->  {info['phonemes']}      [{origin}]",
                foreground="#000")

        def run_search(*_):
            # Debounced: a keystroke cancels the previous pending search so
            # a fast typist doesn't queue one lookup per character.
            if pending["job"]:
                win.after_cancel(pending["job"])
            pending["job"] = win.after(220, do_search)

        def do_search():
            pending["job"] = None
            q = query_var.get().strip()
            res = kokoro_lookup_words(q, log, 150, overrides())
            results.delete(0, "end")
            if res.get("error"):
                count_lbl.config(text="")
                status.config(text=res["error"], foreground="#a00")
                return
            status.config(text="")
            for m in res["matches"]:
                mark = "*" if m["source"] == "override" else " "
                results.insert("end", f"{mark} {m['word']:<24} "
                                      f"{m['phonemes']}")
            results._words = [m["word"] for m in res["matches"]]
            shown, total = len(res["matches"]), res["total"]
            count_lbl.config(
                text=f"{shown} of {total} shown" if total > shown
                     else f"{total} match(es)")

        def on_pick(*_):
            i = results.curselection()
            if i and getattr(results, "_words", None):
                show_word(results._words[i[0]])

        def do_check():
            word = query_var.get().strip()
            if word:
                show_word(word)

        def do_preview(*_):
            pieces = respell_var.get().split()
            if not pieces:
                preview_lbl.config(text="")
                return
            stress = next((i for i, p in enumerate(pieces)
                          if p.startswith("*")), 0)
            clean = [p.lstrip("*") for p in pieces]
            ipa, failed = respell_to_ipa(clean, stress)
            if failed:
                preview_lbl.config(
                    text=f"'{failed}' isn't a word Kokoro knows -- try a "
                         "different real word that sounds like that part.",
                    foreground="#a00")
            else:
                preview_lbl.config(text=f"would become:  {ipa}",
                                  foreground="#060")

        def do_save():
            word = sel["word"] or query_var.get().strip()
            if not word:
                status.config(text="Pick or check a word first.",
                             foreground="#a00")
                return
            pieces = respell_var.get().split()
            if not pieces:
                status.config(text="Type a respelling first.",
                             foreground="#a00")
                return
            stress = next((i for i, p in enumerate(pieces)
                          if p.startswith("*")), 0)
            clean = [p.lstrip("*") for p in pieces]
            ipa, failed = respell_to_ipa(clean, stress)
            if failed or not ipa:
                status.config(
                    text=f"Couldn't build that: '{failed}' isn't a word "
                         "Kokoro knows.", foreground="#a00")
                return
            data = overrides()
            data[word.lower()] = ipa
            data[word.lower() + "__respelling"] = respell_var.get().strip()
            save_pronunciations(data)
            log(f"Pronunciation override saved: {word} -> {ipa}")
            show_word(word)
            do_search()
            # After do_search, which clears the status line on success.
            status.config(text=f"Saved: {word} -> {ipa}", foreground="#060")

        def do_clear():
            word = sel["word"] or query_var.get().strip()
            data = overrides()
            removed = data.pop(word.lower(), None)
            data.pop(word.lower() + "__respelling", None)
            if removed is None:
                status.config(text=f"No override saved for '{word}'.",
                             foreground="#666")
                return
            save_pronunciations(data)
            show_word(word)
            do_search()
            status.config(text=f"Override removed for '{word}'.",
                         foreground="#060")

        if initial_word:
            query_var.set(initial_word)
            show_word(initial_word)
        query_var.trace_add("write", run_search)
        respell_var.trace_add("write", do_preview)
        results.bind("<<ListboxSelect>>", on_pick)
        check_btn.config(command=do_check)
        save_btn.config(command=do_save)
        clear_btn.config(command=do_clear)
        entry.focus_set()
        do_search()

    def open_ffgram_builder():
        """Build an ffmpeg audiogram command by parts.

        Every control here is generated from `ffgram.SOURCES` and
        `ffgram.EFFECTS`, so adding an option to that registry makes it
        appear with the right control and range -- a hand-written form
        would drift from what the code accepts, which is exactly the
        problem the render-settings schema solved.
        """
        win = tk.Toplevel(root)
        win.title("Audiogram command builder")
        win.geometry("1000x740")
        win.transient(root)
        outer = ttk.Frame(win, padding=10)
        outer.pack(fill="both", expand=True)
        spec = dict(settings.get("ffgram") or ffgram_mod.default_spec())
        spec.setdefault("effects", [])

        left, right = ttk.Frame(outer), ttk.Frame(outer)
        left.pack(side="left", fill="y")
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # --- audio source ---
        srow = ttk.Frame(left)
        srow.pack(fill="x")
        ttk.Label(srow, text="Audio").pack(side="left")
        audio_var = tk.StringVar(value=spec.get("audio", ""))
        ttk.Label(srow, textvariable=audio_var, foreground="#666",
                 wraplength=220).pack(side="left", padx=6)

        def pick_audio():
            path = filedialog.askopenfilename(
                title="Audio for the audiogram", parent=win,
                filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac"),
                          ("All files", "*.*")])
            if path:
                audio_var.set(path)
                spec["audio"] = path
                refresh()
        ttk.Button(srow, text="Choose...", command=pick_audio).pack(
            side="right")

        def current_audio():
            if audio_var.get() and os.path.isfile(audio_var.get()):
                return audio_var.get()
            take = current_take()
            path = (take or {}).get("out_path", "")
            return path if path and os.path.isfile(path) else None

        # --- visualiser ---
        vis = ttk.LabelFrame(left, text="Visualiser", padding=8)
        vis.pack(fill="x", pady=(8, 0))
        source_var = tk.StringVar(value=spec.get("source", "showwaves"))
        labels = {k: v["label"] for k, v in ffgram_mod.SOURCES.items()}
        by_label = {v: k for k, v in labels.items()}
        source_menu = ttk.Combobox(vis, state="readonly", width=22,
                                   values=list(labels.values()))
        source_menu.set(labels[source_var.get()])
        source_menu.pack(anchor="w")
        vis_note = ttk.Label(vis, text="", foreground="#666",
                            font=("TkDefaultFont", 8), wraplength=250,
                            justify="left")
        vis_note.pack(anchor="w", pady=(2, 6))
        opts_frame = ttk.Frame(vis)
        opts_frame.pack(fill="x")

        size_row = ttk.Frame(vis)
        size_row.pack(fill="x", pady=(6, 0))
        ttk.Label(size_row, text="Drawn at").pack(side="left")
        rw_var = tk.StringVar(value=str(spec.get("render_width", 1920)))
        rh_var = tk.StringVar(value=str(spec.get("render_height", 360)))
        ttk.Entry(size_row, textvariable=rw_var, width=6).pack(side="left",
                                                                padx=3)
        ttk.Label(size_row, text="x").pack(side="left")
        ttk.Entry(size_row, textvariable=rh_var, width=6).pack(side="left",
                                                                padx=3)
        ttk.Label(size_row, text="fps").pack(side="left", padx=(8, 0))
        fps_var = tk.StringVar(value=str(spec.get("fps", 30)))
        ttk.Entry(size_row, textvariable=fps_var, width=4).pack(side="left",
                                                                padx=3)

        def build_option_rows():
            for child in opts_frame.winfo_children():
                child.destroy()
            key = by_label.get(source_menu.get(), "showwaves")
            spec["source"] = key
            meta = ffgram_mod.SOURCES[key]
            vis_note.config(text=meta["note"])
            spec.setdefault("source_options", {})
            values = {}
            for r, (name, (kind, default, choice, desc)) in enumerate(
                    meta["options"].items()):
                ttk.Label(opts_frame, text=name).grid(row=r * 2, column=0,
                                                      sticky="w")
                current = spec["source_options"].get(name, default)
                if kind == "bool":
                    var = tk.BooleanVar(value=bool(current))
                    ttk.Checkbutton(opts_frame, variable=var).grid(
                        row=r * 2, column=1, sticky="w", padx=6)
                elif kind == "choice":
                    var = tk.StringVar(value=str(current))
                    ttk.Combobox(opts_frame, textvariable=var, width=14,
                                 state="readonly", values=choice).grid(
                        row=r * 2, column=1, sticky="w", padx=6)
                else:
                    var = tk.StringVar(value=str(current))
                    ttk.Entry(opts_frame, textvariable=var, width=16).grid(
                        row=r * 2, column=1, sticky="w", padx=6)
                ttk.Label(opts_frame, text=desc, foreground="#666",
                         font=("TkDefaultFont", 8), wraplength=240,
                         justify="left").grid(row=r * 2 + 1, column=0,
                                              columnspan=2, sticky="w")
                values[name] = (var, kind)

            def collect(*_):
                for n, (v, k) in values.items():
                    raw = v.get()
                    if k == "bool":
                        spec["source_options"][n] = bool(raw)
                    elif k == "int":
                        try:
                            spec["source_options"][n] = int(float(raw))
                        except ValueError:
                            continue
                    elif k == "float":
                        try:
                            spec["source_options"][n] = float(raw)
                        except ValueError:
                            continue
                    else:
                        spec["source_options"][n] = raw
                refresh()
            for v, _k in values.values():
                v.trace_add("write", collect)
            # Options belong to the visualiser, so switching visualiser
            # must not carry the previous one's settings across.
            spec["source_options"] = {
                n: spec["source_options"].get(n, meta["options"][n][1])
                for n in meta["options"]}

        source_menu.bind("<<ComboboxSelected>>",
                        lambda _e: (build_option_rows(), refresh()))

        # --- effect stack ---
        fx = ttk.LabelFrame(left, text="Effects, applied in order",
                            padding=8)
        fx.pack(fill="x", pady=(8, 0))
        fx_list = tk.Listbox(fx, height=5, exportselection=False)
        fx_list.pack(fill="x")
        fx_note = ttk.Label(fx, text="", foreground="#666",
                           font=("TkDefaultFont", 8), wraplength=250,
                           justify="left")
        fx_note.pack(anchor="w", pady=(2, 4))
        add_row = ttk.Frame(fx)
        add_row.pack(fill="x")
        fx_choice = ttk.Combobox(
            add_row, state="readonly", width=18,
            values=[v["label"] for v in ffgram_mod.EFFECTS.values()])
        fx_choice.pack(side="left")
        fx_by_label = {v["label"]: k
                       for k, v in ffgram_mod.EFFECTS.items()}

        def refresh_fx_list():
            fx_list.delete(0, "end")
            for e in spec["effects"]:
                meta = ffgram_mod.EFFECTS.get(e["name"])
                fx_list.insert("end", meta["label"] if meta else e["name"])

        def add_effect():
            name = fx_by_label.get(fx_choice.get())
            if not name:
                return
            spec["effects"].append({"name": name, "options": {}})
            refresh_fx_list()
            refresh()

        def remove_effect():
            sel = fx_list.curselection()
            if sel:
                del spec["effects"][sel[0]]
                refresh_fx_list()
                refresh()

        def move_effect(delta):
            sel = fx_list.curselection()
            if not sel:
                return
            i = sel[0]
            j = i + delta
            if 0 <= j < len(spec["effects"]):
                spec["effects"][i], spec["effects"][j] = \
                    spec["effects"][j], spec["effects"][i]
                refresh_fx_list()
                fx_list.selection_set(j)
                refresh()

        ttk.Button(add_row, text="Add", command=add_effect).pack(side="left",
                                                                  padx=4)
        ttk.Button(add_row, text="Remove", command=remove_effect).pack(
            side="left")
        ttk.Button(add_row, text="Up",
                  command=lambda: move_effect(-1)).pack(side="left", padx=4)
        ttk.Button(add_row, text="Down",
                  command=lambda: move_effect(1)).pack(side="left")

        fx_opts = ttk.Frame(fx)
        fx_opts.pack(fill="x", pady=(6, 0))

        def show_effect_options(*_):
            for child in fx_opts.winfo_children():
                child.destroy()
            sel = fx_list.curselection()
            if not sel:
                fx_note.config(text="")
                return
            entry = spec["effects"][sel[0]]
            meta = ffgram_mod.EFFECTS.get(entry["name"])
            if not meta:
                return
            fx_note.config(text=meta["note"])
            entry.setdefault("options", {})
            vars_ = {}
            for r, (name, (kind, default, choice, desc)) in enumerate(
                    meta["options"].items()):
                ttk.Label(fx_opts, text=name).grid(row=r, column=0,
                                                   sticky="w")
                current = entry["options"].get(name, default)
                if kind == "choice":
                    var = tk.StringVar(value=str(current))
                    ttk.Combobox(fx_opts, textvariable=var, width=12,
                                 state="readonly", values=choice).grid(
                        row=r, column=1, sticky="w", padx=6)
                else:
                    var = tk.StringVar(value=str(current))
                    ttk.Entry(fx_opts, textvariable=var, width=14).grid(
                        row=r, column=1, sticky="w", padx=6)
                vars_[name] = (var, kind)

            def collect(*_):
                for n, (v, k) in vars_.items():
                    raw = v.get()
                    if k == "int":
                        try:
                            entry["options"][n] = int(float(raw))
                        except ValueError:
                            continue
                    elif k == "float":
                        try:
                            entry["options"][n] = float(raw)
                        except ValueError:
                            continue
                    else:
                        entry["options"][n] = raw
                refresh()
            for v, _k in vars_.values():
                v.trace_add("write", collect)
        fx_list.bind("<<ListboxSelect>>", show_effect_options)

        # --- output ---
        outbox = ttk.LabelFrame(left, text="Output", padding=8)
        outbox.pack(fill="x", pady=(8, 0))
        ttk.Label(outbox, text="Format").grid(row=0, column=0, sticky="w")
        enc_labels = {k: v["label"]
                     for k, v in ffgram_mod.ENCODERS.items()}
        enc_by_label = {v: k for k, v in enc_labels.items()}
        enc_var = tk.StringVar(value=enc_labels.get(spec.get("encoder"),
                                                    enc_labels["h264"]))
        ttk.Combobox(outbox, textvariable=enc_var, state="readonly",
                     width=34, values=list(enc_labels.values())).grid(
            row=0, column=1, sticky="w", padx=6)
        ttk.Label(outbox, text="Speed").grid(row=1, column=0, sticky="w")
        preset_var = tk.StringVar(value=spec.get("preset", "ultrafast"))
        ttk.Combobox(outbox, textvariable=preset_var, state="readonly",
                     width=12, values=ffgram_mod.PRESETS).grid(
            row=1, column=1, sticky="w", padx=6)
        ttk.Label(outbox, text="Background").grid(row=3, column=0,
                                                   sticky="w")
        bg_var = tk.StringVar(value=spec.get("chroma_key_background", ""))
        bg_menu = ttk.Combobox(
            outbox, state="readonly", width=18,
            values=["Black (plain)", "Solid green (key it out)",
                   "Solid magenta (key it out)", "Custom colour..."])
        current_bg = spec.get("chroma_key_background", "")
        bg_menu.set(
            "Solid green (key it out)"
            if current_bg == ffgram_mod.CHROMA_KEY_COLOR
            else "Solid magenta (key it out)" if current_bg == "0xFF00FF"
            else "Custom colour..." if current_bg else "Black (plain)")
        bg_menu.grid(row=3, column=1, sticky="w", padx=6)
        bg_custom = ttk.Entry(outbox, textvariable=bg_var, width=10)

        def on_bg_choice(*_):
            choice = bg_menu.get()
            if choice == "Black (plain)":
                bg_var.set("")
                bg_custom.grid_forget()
            elif choice == "Solid green (key it out)":
                bg_var.set(ffgram_mod.CHROMA_KEY_COLOR)
                bg_custom.grid_forget()
            elif choice == "Solid magenta (key it out)":
                bg_var.set("0xFF00FF")
                bg_custom.grid_forget()
            else:
                if not bg_var.get():
                    bg_var.set("0xFFFFFF")
                bg_custom.grid(row=4, column=1, sticky="w", padx=6,
                              pady=(2, 0))
            refresh()
        bg_menu.bind("<<ComboboxSelected>>", on_bg_choice)
        if bg_menu.get() == "Custom colour...":
            bg_custom.grid(row=4, column=1, sticky="w", padx=6, pady=(2, 0))
        ttk.Label(outbox,
                 text="A solid background can be chroma-keyed out in an "
                      "editor -- simpler to rely on than real "
                      "transparency, which depends on the editor trusting "
                      "the alpha channel.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=280, justify="left").grid(row=5, column=0,
                                                      columnspan=2,
                                                      sticky="w",
                                                      pady=(4, 0))

        ttk.Label(outbox,
                 text="The preset matters more than anything else here: "
                      "ultrafast is about three times quicker than medium "
                      "for the same picture, at the cost of a bigger file "
                      "— which doesn't matter if it's going into an "
                      "editor anyway.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=280, justify="left").grid(row=2, column=0,
                                                      columnspan=2,
                                                      sticky="w",
                                                      pady=(4, 0))

        # --- the command, explanation and estimate ---
        ttk.Label(right, text="The command",
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        cmd_box = scrolledtext.ScrolledText(right, height=6, wrap="word",
                                            font=("TkFixedFont", 8))
        cmd_box.pack(fill="x")
        ttk.Label(right, text="What it does", foreground="#666").pack(
            anchor="w", pady=(8, 0))
        why_box = scrolledtext.ScrolledText(right, height=7, wrap="word",
                                            font=("TkDefaultFont", 9))
        why_box.pack(fill="x")
        est_lbl = ttk.Label(right, text="", wraplength=560, justify="left")
        est_lbl.pack(anchor="w", pady=(8, 0))

        ttk.Label(right,
                 text="Your own filter graph (leave blank to use the one "
                      "built above):",
                 foreground="#666").pack(anchor="w", pady=(8, 0))
        custom_var = tk.StringVar(value=spec.get("custom_graph", ""))
        ttk.Entry(right, textvariable=custom_var).pack(fill="x")
        status = ttk.Label(right, text="", wraplength=560, justify="left")
        status.pack(anchor="w", pady=(6, 0))

        def refresh(*_):
            try:
                spec["render_width"] = int(rw_var.get())
                spec["render_height"] = int(rh_var.get())
                spec["fps"] = int(fps_var.get())
            except ValueError:
                pass
            spec["encoder"] = enc_by_label.get(enc_var.get(), "h264")
            spec["preset"] = preset_var.get()
            spec["chroma_key_background"] = bg_var.get().strip()
            spec["custom_graph"] = custom_var.get().strip()
            audio = current_audio() or "<your audio file>"
            ext = ffgram_mod.ENCODERS[spec["encoder"]]["ext"]
            cmd_box.delete("1.0", "end")
            cmd_box.insert("1.0", ffgram_mod.command_text(
                audio, "audiogram" + ext, spec))
            why_box.delete("1.0", "end")
            why_box.insert("1.0", "\n".join(
                "- " + line for line in ffgram_mod.explain(spec)))
            real = current_audio()
            seconds = (duration_of(real) or 0) if real else 0
            est_lbl.config(
                text=ffgram_mod.describe_estimate(spec, seconds)
                     if seconds else
                     "Choose an audio file to see a time estimate.")

        for v in (rw_var, rh_var, fps_var, enc_var, preset_var, custom_var,
                 bg_var):
            v.trace_add("write", refresh)

        def run(seconds=None):
            audio = current_audio()
            if not audio:
                status.config(text="Choose an audio file first.",
                             foreground="#a00")
                return
            ext = ffgram_mod.ENCODERS[spec["encoder"]]["ext"]
            name = ("audiogram_preview" if seconds else "audiogram") + ext
            out = unique_path(os.path.join(state["root"], name))
            status.config(text="Rendering...", foreground="#000")
            clear_log()
            set_running(True)

            def work():
                try:
                    path = ffgram_mod.render(audio, out, spec, log, seconds)
                    root.after(0, lambda: (
                        status.config(text=f"Done: "
                                          f"{os.path.basename(path)}",
                                      foreground="#060"),
                        reveal_file(path)))
                except Exception as exc:
                    msg = f"{exc}"
                    log("Failed: " + msg)
                    root.after(0, lambda: status.config(
                        text=msg[:400], foreground="#a00"))
                finally:
                    root.after(0, lambda: set_running(False))
            threading.Thread(target=work, daemon=True).start()

        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Preview 5 seconds",
                  command=lambda: run(5)).pack(side="left")
        ttk.Button(btns, text="Render it all",
                  command=lambda: run(None)).pack(side="left", padx=6)

        def save_spec():
            settings["ffgram"] = dict(spec)
            save_settings(settings)
            status.config(text="Saved.", foreground="#060")
        ttk.Button(btns, text="Save", command=save_spec).pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(
            side="right")

        build_option_rows()
        refresh_fx_list()
        refresh()

    def open_audiogram_dialog():
        """Lay out the audiogram, see it against the background image, and
        bake it to a transparent overlay. Baking is what makes it cheap for
        an editor to composite -- which is exactly why the layout has to be
        settled here, before it stops being adjustable."""
        if not require_components("pillow", "ffmpeg",
                                 feature="The audiogram"):
            return
        win = tk.Toplevel(root)
        win.title("Audiogram")
        win.geometry("980x680")
        win.transient(root)
        outer_f = ttk.Frame(win, padding=12)
        outer_f.pack(fill="both", expand=True)

        cfg = audiogram_mod.config_with_defaults(
            settings.get("audiogram") or {})
        PW, PH = 480, 270            # preview canvas, 16:9

        srcbox = ttk.Frame(outer_f)
        srcbox.pack(side="top", fill="x", pady=(0, 8))
        ttk.Label(srcbox, text="Waveform from").pack(side="left")
        src_lbl = ttk.Label(srcbox, text="", foreground="#666",
                           wraplength=520, justify="left")
        src_lbl.pack(side="left", padx=8)

        def take_audio():
            take = current_take()
            path = (take or {}).get("out_path", "")
            return path if path and os.path.isfile(path) else None

        def refresh_source(*_):
            src_lbl.config(
                text=audiogram_mod.source_note(cfg, take_audio()),
                foreground=("#a06000"
                            if "NOT the take" in
                            audiogram_mod.source_note(cfg, take_audio())
                            or "MISSING" in
                            audiogram_mod.source_note(cfg, take_audio())
                            else "#666"))

        def choose_source():
            path = filedialog.askopenfilename(
                title="Audio for the audiogram", parent=win,
                filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"),
                          ("All files", "*.*")])
            if path:
                cfg["audio_source"] = path
                refresh_source()
                for extra in _derived:
                    extra()

        def clear_source():
            cfg["audio_source"] = ""
            refresh_source()
            for extra in _derived:
                extra()

        ttk.Button(srcbox, text="Choose...", command=choose_source).pack(
            side="right")
        ttk.Button(srcbox, text="Use the take", command=clear_source).pack(
            side="right", padx=6)

        left = ttk.Frame(outer_f)
        left.pack(side="left", fill="y")
        right = ttk.Frame(outer_f)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        ttk.Label(right, text="Preview",
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        canvas = tk.Canvas(right, width=PW, height=PH, bg="#222",
                          highlightthickness=1,
                          highlightbackground="#555")
        canvas.pack(anchor="w", pady=(4, 6))
        hint = ttk.Label(right, text="", foreground="#666",
                        font=("TkDefaultFont", 8), wraplength=PW,
                        justify="left")
        hint.pack(anchor="w")
        keep = {}                    # keeps PhotoImages alive

        def redraw(*_):
            canvas.delete("all")
            try:
                from PIL import Image, ImageTk
            except ImportError:
                canvas.create_text(PW / 2, PH / 2, fill="#ccc",
                                  text="Preview needs Pillow "
                                       "(pip install pillow)")
                return
            img = Image.new("RGBA", (PW, PH), (34, 34, 34, 255))
            bg_path = state.get("video_image")
            if bg_path and os.path.isfile(bg_path):
                try:
                    bg = Image.open(bg_path).convert("RGBA")
                    bg.thumbnail((PW, PH))
                    img.paste(bg, ((PW - bg.width) // 2,
                                  (PH - bg.height) // 2), bg)
                except Exception:
                    pass
            # A mid-level frame drawn by the REAL renderer, not a sketch of
            # it, so the mockup can't disagree with the output.
            import numpy as np
            n = max(2, int(cfg["bars"]))
            demo = (0.35 + 0.55 * np.abs(np.sin(
                np.linspace(0, 3.4, n) * 1.7))).astype("float32")
            img.alpha_composite(
                audiogram_mod.draw_frame(demo, cfg, PW, PH))
            keep["img"] = ImageTk.PhotoImage(img)
            canvas.create_image(0, 0, anchor="nw", image=keep["img"])

            geo = audiogram_mod.layout(cfg, PW, PH)
            x0, y0, x1, y1 = geo["box"]
            canvas.create_rectangle(x0, y0, x1, y1, outline="#4ea3ff",
                                   dash=(4, 3))
            cx, cy = geo["center"]
            canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                              outline="#4dff88", width=2)
            canvas.create_text(cx + 8, cy - 10, text="centre", anchor="w",
                              fill="#4dff88", font=("TkDefaultFont", 7))
            px, py = geo["pivot"]
            canvas.create_line(px - 7, py, px + 7, py, fill="#ff7b4d",
                              width=2)
            canvas.create_line(px, py - 7, px, py + 7, fill="#ff7b4d",
                              width=2)
            canvas.create_text(px + 9, py + 9, text="pivot", anchor="w",
                              fill="#ff7b4d", font=("TkDefaultFont", 7))
            box = audiogram_mod.crop_box(cfg, 1920, 1080)
            frac = ((box[2] - box[0]) * (box[3] - box[1])) / (1920 * 1080)
            hint.config(
                text=("Dashed box: the audiogram's area. Green: centre. "
                     "Orange: rotation pivot.  "
                     f"Cropped export would cover {frac * 100:.0f}% of the "
                     "frame" + (" (rotation disables cropping)."
                                if cfg["rotation"] else ".")))

        # Readouts that depend on the layout but live outside the preview
        # picture. Filled in once those widgets exist, so every control
        # updates the estimate and the command as well as the drawing --
        # which is what "half the variables do nothing" was really about.
        _derived = []

        def add_row(parent, label, key, lo, hi, step, row, fmt="%.2f"):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                               pady=2)
            var = tk.StringVar(value=str(cfg[key]))
            def on_change(*_):
                try:
                    v = float(var.get())
                except ValueError:
                    return
                cfg[key] = max(lo, min(hi, v))
                redraw()
                for extra in _derived:
                    extra()
            var.trace_add("write", on_change)
            ttk.Spinbox(parent, from_=lo, to=hi, increment=step, width=8,
                        textvariable=var).grid(row=row, column=1, sticky="w",
                                               padx=6, pady=2)
            return var

        shape = ttk.LabelFrame(left, text="Shape", padding=8)
        shape.pack(fill="x")
        ttk.Label(shape, text="Geometry").grid(row=0, column=0, sticky="w")
        geom_var = tk.StringVar(value=cfg["geometry"])
        geom_menu = ttk.Combobox(shape, textvariable=geom_var, width=10,
                                 state="readonly",
                                 values=["linear", "polar"])
        geom_menu.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(shape, text="Layers").grid(row=1, column=0, sticky="nw")
        layerbox = ttk.Frame(shape)
        layerbox.grid(row=1, column=1, sticky="w", padx=6)
        layer_vars = {}
        for key, label in (("show_bars", "Bars"), ("show_line", "Line"),
                          ("show_fill", "Fill")):
            var = tk.BooleanVar(value=bool(cfg.get(key)))
            layer_vars[key] = var
            ttk.Checkbutton(layerbox, text=label, variable=var).pack(
                side="left")
        # Kept so an older saved layout still round-trips through the
        # dialog rather than losing its style on the first save.
        style_var = tk.StringVar(value=cfg["style"])
        add_row(shape, "Bars", "bars", 4, 512, 4, 2)
        add_row(shape, "Bar width", "bar_width", 0.05, 1.0, 0.05, 3)
        add_row(shape, "Line width", "line_width", 1, 40, 1, 4)
        add_row(shape, "Smoothing", "smoothing", 0.0, 0.95, 0.05, 5)
        mirror_var = tk.BooleanVar(value=cfg["mirror"])
        ttk.Checkbutton(shape, text="Mirror (grow both ways)",
                        variable=mirror_var).grid(row=6, column=0,
                                                  columnspan=2, sticky="w")

        place = ttk.LabelFrame(left, text="Position and size", padding=8)
        place.pack(fill="x", pady=(8, 0))
        lin_rows, pol_rows = [], []

        def remember(widget_rows, *keys):
            for k in keys:
                widget_rows.append(k)

        add_row(place, "X", "x", 0.0, 1.0, 0.01, 0)
        add_row(place, "Y", "y", 0.0, 1.0, 0.01, 1)
        add_row(place, "Width", "width", 0.02, 1.0, 0.01, 2)
        add_row(place, "Height", "height", 0.02, 1.0, 0.01, 3)
        add_row(place, "Centre X", "center_x", 0.0, 1.0, 0.01, 4)
        add_row(place, "Centre Y", "center_y", 0.0, 1.0, 0.01, 5)
        add_row(place, "Inner radius", "inner_radius", 0.0, 0.6, 0.01, 6)
        add_row(place, "Outer radius", "outer_radius", 0.02, 0.7, 0.01, 7)
        add_row(place, "Pivot X", "pivot_x", 0.0, 1.0, 0.01, 8)
        add_row(place, "Pivot Y", "pivot_y", 0.0, 1.0, 0.01, 9)
        add_row(place, "Rotation", "rotation", -180, 180, 5, 10)

        look = ttk.LabelFrame(left, text="Appearance", padding=8)
        look.pack(fill="x", pady=(8, 0))
        ttk.Label(look, text="Colour (#rrggbb)").grid(row=0, column=0,
                                                      sticky="w")
        color_var = tk.StringVar(value=cfg["color"])
        ttk.Entry(look, textvariable=color_var, width=10).grid(
            row=0, column=1, sticky="w", padx=6)
        ttk.Label(look, text="Line colour").grid(row=1, column=0, sticky="w")
        line_color_var = tk.StringVar(value=cfg.get("line_color", ""))
        ttk.Entry(look, textvariable=line_color_var, width=10).grid(
            row=1, column=1, sticky="w", padx=6)
        ttk.Label(look, text="Fill colour").grid(row=2, column=0, sticky="w")
        fill_color_var = tk.StringVar(value=cfg.get("fill_color", ""))
        ttk.Entry(look, textvariable=fill_color_var, width=10).grid(
            row=2, column=1, sticky="w", padx=6)
        ttk.Label(look, text="(blank = same as Colour)", foreground="#666",
                 font=("TkDefaultFont", 8)).grid(row=3, column=1, sticky="w",
                                                 padx=6)
        add_row(look, "Fill opacity", "fill_opacity", 0.0, 1.0, 0.05, 4)
        add_row(look, "Opacity", "opacity", 0.0, 1.0, 0.05, 5)

        def on_simple(*_):
            cfg["geometry"] = geom_var.get()
            cfg["style"] = style_var.get()
            cfg["mirror"] = bool(mirror_var.get())
            cfg["color"] = color_var.get().strip() or "#FFFFFF"
            cfg["line_color"] = line_color_var.get().strip()
            cfg["fill_color"] = fill_color_var.get().strip()
            for key, var in layer_vars.items():
                cfg[key] = bool(var.get())
            redraw()
            # After cfg is updated, not before -- the estimate and the
            # command are derived from it and would otherwise show the
            # previous state.
            for extra in _derived:
                extra()
        for v in (geom_var, style_var, mirror_var, color_var,
                 line_color_var, fill_color_var, *layer_vars.values()):
            v.trace_add("write", on_simple)

        fx = ttk.LabelFrame(right, text="Animate a value over time",
                            padding=8)
        fx.pack(fill="x", pady=(10, 0))
        ttk.Label(fx,
                 text="Any of these can be a formula instead of a number, "
                      "worked out fresh for every frame.",
                 foreground="#666", wraplength=PW, justify="left").pack(
            anchor="w")
        fxrow = ttk.Frame(fx)
        fxrow.pack(fill="x", pady=(6, 2))
        ttk.Label(fxrow, text="Value").pack(side="left")
        fx_param = tk.StringVar(value="opacity")
        fx_param_menu = ttk.Combobox(fxrow, textvariable=fx_param,
                                     state="readonly", width=16,
                                     values=list(audiogram_mod.ANIMATABLE))
        fx_param_menu.pack(side="left", padx=6)
        fx_entry_var = tk.StringVar()
        ttk.Entry(fx, textvariable=fx_entry_var).pack(fill="x")
        fx_msg = ttk.Label(fx, text="", foreground="#666",
                          font=("TkDefaultFont", 8), wraplength=PW,
                          justify="left")
        fx_msg.pack(anchor="w", pady=(2, 4))

        ttk.Label(fx, text="Available names (type above to filter):",
                 foreground="#666",
                 font=("TkDefaultFont", 8)).pack(anchor="w")
        fx_list = tk.Listbox(fx, height=5, font=("TkFixedFont", 8),
                             exportselection=False)
        fx_list.pack(fill="x")

        def fx_refresh_reference(token=""):
            fx_list.delete(0, "end")
            for item in expressions_mod.reference(token):
                kind = "var " if item["kind"] == "variable" else "func"
                fx_list.insert("end",
                              f"{kind} {item['name']:<12} {item['detail']}")

        def fx_current_token():
            """The word being typed right now, so the list filters to what
            is under the cursor rather than the whole formula."""
            text = fx_entry_var.get()
            token = ""
            for ch in reversed(text):
                if ch.isalnum() or ch == "_":
                    token = ch + token
                else:
                    break
            return token

        def fx_on_type(*_):
            fx_refresh_reference(fx_current_token())
            src = fx_entry_var.get().strip()
            if not src:
                fx_msg.config(text="Leave empty to keep using the plain "
                                  "number.", foreground="#666")
                return
            ok, message = expressions_mod.validate(src)
            fx_msg.config(text=message,
                         foreground="#060" if ok else "#a00")

        def fx_insert_selected(*_):
            sel = fx_list.curselection()
            if not sel:
                return
            name = fx_list.get(sel[0]).split()[1]
            token = fx_current_token()
            text = fx_entry_var.get()
            if token:
                text = text[:len(text) - len(token)]
            fx_entry_var.set(text + name)

        fx_entry_var.trace_add("write", fx_on_type)
        fx_list.bind("<Double-Button-1>", fx_insert_selected)
        ttk.Button(fx, text="Insert selected name",
                  command=fx_insert_selected).pack(anchor="w", pady=(2, 0))

        def fx_load_param(*_):
            value = cfg.get(fx_param.get())
            fx_entry_var.set(value if expressions_mod.is_expression(value)
                            else "")
        fx_param_menu.bind("<<ComboboxSelected>>", fx_load_param)

        def fx_apply():
            key = fx_param.get()
            src = fx_entry_var.get().strip()
            if not src:
                cfg[key] = audiogram_mod.DEFAULTS.get(key, 0.0)
                fx_msg.config(text=f"{key} is back to a plain number "
                                  f"({cfg[key]}).", foreground="#060")
            else:
                ok, message = expressions_mod.validate(src)
                if not ok:
                    fx_msg.config(text=message, foreground="#a00")
                    return
                cfg[key] = src
                fx_msg.config(text=f"{key} is now a formula. {message}",
                             foreground="#060")
            redraw()
        ttk.Button(fx, text="Apply to this value",
                  command=fx_apply).pack(anchor="w", pady=(4, 0))
        fx_refresh_reference()
        fx_load_param()

        export = ttk.LabelFrame(right, text="Bake to a transparent overlay",
                                padding=8)
        export.pack(fill="x", pady=(10, 0))
        ttk.Label(export,
                 text="Renders once here so your editor only composites it "
                      "-- no waveform recomputed per frame.",
                 foreground="#666", wraplength=PW, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(export, text="Format").grid(row=1, column=0, sticky="w")
        codec_var = tk.StringVar(
            value=audiogram_mod.CODECS["webm"]["label"])
        ttk.Combobox(export, textvariable=codec_var, state="readonly",
                     width=44,
                     values=[c["label"] for c in
                            audiogram_mod.CODECS.values()]).grid(
            row=1, column=1, sticky="w", padx=6)
        by_label = {c["label"]: k
                   for k, c in audiogram_mod.CODECS.items()}
        ttk.Label(export, text="Resolution").grid(row=2, column=0,
                                                  sticky="w")
        res_var = tk.StringVar(value="1920x1080")
        ttk.Combobox(export, textvariable=res_var, state="readonly",
                     width=12, values=["1280x720", "1920x1080",
                                       "2560x1440", "3840x2160"]).grid(
            row=2, column=1, sticky="w", padx=6)
        crop_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(export, text="Crop to the audiogram's area "
                                     "(much faster and smaller)",
                        variable=crop_var).grid(row=3, column=0,
                                                columnspan=2, sticky="w")
        ex_status = ttk.Label(export, text="", wraplength=PW,
                             justify="left")
        ex_status.grid(row=5, column=0, columnspan=2, sticky="w",
                       pady=(6, 0))
        ex_btn = ttk.Button(export, text="Render overlay...")
        ex_btn.grid(row=4, column=0, sticky="w", pady=(6, 0))

        def save_cfg():
            settings["audiogram"] = dict(cfg)
            save_settings(settings)

        def do_export():
            try:
                audio = audiogram_mod.resolve_audio_source(cfg,
                                                           take_audio())
            except FileNotFoundError as exc:
                if not messagebox.askyesno(
                        "No audio", str(exc) + "\n\nChoose a file now?",
                        parent=win):
                    return
                audio = filedialog.askopenfilename(
                    title="Choose the audio for the audiogram", parent=win,
                    filetypes=[("Audio", "*.mp3 *.m4a *.wav *.flac"),
                              ("All files", "*.*")])
                if not audio:
                    return
                cfg["audio_source"] = audio
                refresh_source()
            save_cfg()
            codec = by_label.get(codec_var.get(), "webm")
            w, h = (int(v) for v in res_var.get().split("x"))
            ext = audiogram_mod.CODECS[codec]["ext"]
            base = os.path.splitext(audio)[0] + "_audiogram"
            out = unique_path(base + ext) if ext else base
            frames = audiogram_mod.estimate_frames(audio, cfg["fps"])
            ex_btn.config(state="disabled")
            ex_status.config(
                text=f"Rendering {frames:,} frames -- progress is in the "
                     "main log.", foreground="#000")
            clear_log()
            set_running(True)

            def work():
                try:
                    path = audiogram_mod.render_overlay(
                        audio, out, cfg, log, width=w, height=h,
                        codec=codec, crop=crop_var.get())
                    ox, oy, fw, fh = audiogram_mod.render_overlay.last_crop
                    note = (f"Done: {os.path.basename(path)}"
                           + (f" -- place it at x={ox}, y={oy} in your "
                              f"editor ({fw}x{fh})."
                              if (fw, fh) != (w, h) else
                              " -- full frame, drop it straight on top."))
                    log("\n" + note)
                    root.after(0, lambda: (
                        ex_status.config(text=note, foreground="#060"),
                        ex_btn.config(state="normal"),
                        reveal_file(path)))
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    log("Audiogram export failed: " + msg)
                    root.after(0, lambda: (
                        ex_status.config(text=msg, foreground="#a00"),
                        ex_btn.config(state="normal")))
                finally:
                    root.after(0, lambda: set_running(False))

            threading.Thread(target=work, daemon=True).start()

        ex_btn.config(command=do_export)
        motion = ttk.LabelFrame(right, text="See it moving", padding=8)
        motion.pack(fill="x", pady=(10, 0))
        ttk.Label(motion,
                 text="A still frame can't show smoothing, blur or motion "
                      "at all. This renders a few seconds so you can watch "
                      "it.",
                 foreground="#666", wraplength=PW, justify="left").pack(
            anchor="w")
        mrow = ttk.Frame(motion)
        mrow.pack(fill="x", pady=(6, 0))
        ttk.Label(mrow, text="Seconds").pack(side="left")
        preview_secs = tk.IntVar(value=5)
        ttk.Spinbox(mrow, from_=1, to=audiogram_mod.PREVIEW_MAX_SECONDS,
                    width=4, textvariable=preview_secs).pack(side="left",
                                                              padx=6)
        preview_btn = ttk.Button(mrow, text="Preview motion")
        preview_btn.pack(side="left")
        which_lbl = ttk.Label(motion, text="", foreground="#666",
                             font=("TkDefaultFont", 8), wraplength=PW,
                             justify="left")
        which_lbl.pack(anchor="w", pady=(4, 0))

        def preview_source():
            """Whatever the audiogram is pointed at -- an explicitly
            chosen file, else the selected take."""
            try:
                return audiogram_mod.resolve_audio_source(cfg, take_audio())
            except FileNotFoundError:
                return None

        def refresh_which(*_):
            engine, why = audiogram_mod.preview_reason(cfg)
            name = ("fast ffmpeg path" if engine == "ffmpeg"
                    else "frame renderer")
            which_lbl.config(text=f"Will use the {name} -- {why}.")

        def do_preview_motion():
            audio = preview_source()
            if not audio:
                audio = filedialog.askopenfilename(
                    title="Choose audio to preview against", parent=win,
                    filetypes=[("Audio", "*.mp3 *.m4a *.wav *.flac"),
                              ("All files", "*.*")])
                if not audio:
                    return
                cfg["audio_source"] = audio
                refresh_source()
            preview_btn.config(state="disabled")
            ex_status.config(text="Rendering a short preview...",
                            foreground="#000")
            clear_log()
            set_running(True)

            def work():
                try:
                    path, engine = audiogram_mod.preview_clip(
                        audio, os.path.join(state["root"], "_preview"),
                        cfg, log, seconds=int(preview_secs.get()),
                        width=640, height=360)
                    root.after(0, lambda: (
                        ex_status.config(
                            text=f"Preview ready ({engine} renderer).",
                            foreground="#060"),
                        preview_btn.config(state="normal"),
                        reveal_file(path)))
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    log("Preview failed: " + msg)
                    root.after(0, lambda: (
                        ex_status.config(text=msg, foreground="#a00"),
                        preview_btn.config(state="normal")))
                finally:
                    root.after(0, lambda: set_running(False))
            threading.Thread(target=work, daemon=True).start()
        preview_btn.config(command=do_preview_motion)

        cmdbox = ttk.LabelFrame(right, text="The ffmpeg command", padding=8)
        cmdbox.pack(fill="x", pady=(10, 0))
        ttk.Label(cmdbox,
                 text="What the fast path will run. Put your own filter "
                      "graph below to use it instead; clear it to go back "
                      "to the built one.",
                 foreground="#666", wraplength=PW, justify="left").pack(
            anchor="w")
        cmd_text = scrolledtext.ScrolledText(cmdbox, height=4, wrap="word",
                                             font=("TkFixedFont", 8))
        cmd_text.pack(fill="x", pady=(4, 4))
        filter_var = tk.StringVar(value=cfg.get("filter_override", ""))
        frow = ttk.Frame(cmdbox)
        frow.pack(fill="x")
        ttk.Label(frow, text="Your filter graph").pack(side="left")
        ttk.Entry(frow, textvariable=filter_var).pack(side="left", fill="x",
                                                      expand=True, padx=6)

        def refresh_command(*_):
            audio = preview_source() or "<your audio file>"
            try:
                w, h = (int(v) for v in res_var.get().split("x"))
            except ValueError:
                return
            override = filter_var.get().strip() or None
            cmd_text.delete("1.0", "end")
            cmd_text.insert("1.0", audiogram_mod.command_preview(
                audio, "audiogram.mp4", cfg, w, h, seconds=None,
                filter_override=override))
            cfg["filter_override"] = filter_var.get().strip()
        filter_var.trace_add("write", refresh_command)

        est_lbl = ttk.Label(export, text="", foreground="#666",
                           font=("TkDefaultFont", 8), wraplength=PW,
                           justify="left")
        est_lbl.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def refresh_estimate(*_):
            audio = preview_source()
            seconds = (duration_of(audio) or 0) if audio else 0
            if not seconds:
                est_lbl.config(text="Render an episode first to see a time "
                                   "estimate for it.")
                return
            try:
                w, h = (int(v) for v in res_var.get().split("x"))
            except ValueError:
                return
            box = (audiogram_mod.crop_box(cfg, w, h) if crop_var.get()
                   else (0, 0, w, h))
            fraction = ((box[2] - box[0]) * (box[3] - box[1])) / (w * h)
            est = audiogram_mod.estimate_render(
                seconds, w, h, int(cfg.get("fps", 30) or 30), fraction,
                by_label.get(codec_var.get(), "webm"))
            est_lbl.config(
                text=f"For {seconds / 60:.0f} min of audio: "
                     + audiogram_mod.describe_estimate(est))

        def refresh_derived(*_):
            refresh_estimate()
            refresh_command()
            refresh_which()

        for var in (res_var, codec_var, crop_var):
            var.trace_add("write", refresh_derived)
        _derived.append(refresh_derived)
        _derived.append(refresh_source)

        ttk.Button(right, text="Save layout",
                  command=lambda: (save_cfg(),
                                   ex_status.config(text="Layout saved.",
                                                    foreground="#060"))
                  ).pack(anchor="w", pady=(10, 0))
        redraw()
        refresh_derived()

    def open_transcribe_dialog():
        """The reverse direction: an existing audio file back into a text
        document, subtitles and rough chapter marks. Works on any speech
        audio, not only takes this app produced."""
        if not require_components("faster-whisper",
                                 feature="Transcribing audio"):
            return
        src = filedialog.askopenfilename(
            title="Choose an audio file to transcribe",
            filetypes=[("Audio", "*.mp3 *.m4a *.wav *.flac *.aac *.ogg "
                                 "*.opus *.wma *.mp4 *.mkv"),
                      ("All files", "*.*")])
        if not src:
            return

        win = tk.Toplevel(root)
        win.title("Transcribe audio")
        win.geometry("560x360")
        win.transient(root)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=os.path.basename(src),
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(frame,
                 text="Speech recognition runs entirely on this machine. "
                      "The first run downloads the model. Expect it to "
                      "take roughly as long as the audio itself on a CPU, "
                      "less with a GPU.",
                 foreground="#666", wraplength=520, justify="left").pack(
            anchor="w", pady=(2, 10))

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Model").pack(side="left")
        model_var = tk.StringVar(
            value=settings.get("whisper_model", transcribe_mod.DEFAULT_MODEL))
        model_menu = ttk.Combobox(
            row, textvariable=model_var, state="readonly", width=46,
            values=[d for _, d in transcribe_mod.MODEL_SIZES])
        model_menu.pack(side="left", padx=8)
        by_desc = {d: k for k, d in transcribe_mod.MODEL_SIZES}
        for key, desc in transcribe_mod.MODEL_SIZES:
            if key == model_var.get():
                model_var.set(desc)

        srt_var = tk.BooleanVar(value=True)
        chap_var = tk.BooleanVar(value=True)
        stamp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Also write subtitles (.srt)",
                        variable=srt_var).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(frame, text="Also guess chapter marks from long "
                                    "pauses", variable=chap_var).pack(
            anchor="w")
        ttk.Checkbutton(frame, text="Put a timestamp before every line in "
                                    "the transcript", variable=stamp_var
                        ).pack(anchor="w")
        ttk.Label(frame,
                 text="Chapter marks here are guessed from silences -- "
                      "recognised speech carries no heading information, "
                      "so treat them as a starting point to edit.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=520, justify="left").pack(anchor="w",
                                                      pady=(6, 0))
        status = ttk.Label(frame, text="", wraplength=520, justify="left")
        status.pack(anchor="w", pady=(10, 0))
        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(10, 0))
        go_btn = ttk.Button(btns, text="Transcribe")
        go_btn.pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(
            side="right")

        def do_transcribe():
            size = by_desc.get(model_var.get(), transcribe_mod.DEFAULT_MODEL)
            settings["whisper_model"] = size
            save_settings(settings)
            go_btn.config(state="disabled")
            status.config(text="Working -- progress is in the main log.",
                         foreground="#000")
            clear_log()
            set_running(True)
            want_srt, want_chap = srt_var.get(), chap_var.get()
            want_stamps = stamp_var.get()

            def work():
                made = []
                try:
                    made = tasks_mod.transcribe_file(
                        src, log, model=size, want_srt=want_srt,
                        want_chapters=want_chap, timestamps=want_stamps,
                        out_dir=os.path.dirname(src) or state["root"])
                    log("\nDone.")

                    def finished():
                        status.config(
                            text=f"Done -- {len(made)} file(s) written "
                                 f"beside the audio.", foreground="#060")
                        go_btn.config(state="normal")
                        reveal_file(made[0])
                    root.after(0, finished)
                except transcribe_mod.TranscribeUnavailable as exc:
                    msg = str(exc)
                    log(msg)
                    root.after(0, lambda: (
                        status.config(text=msg, foreground="#a00"),
                        go_btn.config(state="normal")))
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    log("Transcription failed: " + msg)
                    root.after(0, lambda: (
                        status.config(text=msg, foreground="#a00"),
                        go_btn.config(state="normal")))
                finally:
                    root.after(0, lambda: set_running(False))

            threading.Thread(target=work, daemon=True).start()

        go_btn.config(command=do_transcribe)

    def convert_audio_to_wav():
        """Standalone converter: point it at any audio file and get an
        editing-ready WAV beside it. Same conversion the checkbox performs
        during a render, exposed separately so it also works on audio this
        app didn't produce -- older takes, downloads, anything already sitting
        on disk."""
        src = filedialog.askopenfilename(
            title="Choose an audio file to convert",
            filetypes=[("Audio", "*.mp3 *.m4a *.wav *.flac *.aac *.ogg "
                                 "*.opus *.wma *.mp4 *.mkv"),
                      ("All files", "*.*")])
        if not src:
            return
        rate = int(editing_wav_rate_var.get())
        channels = EDITING_WAV_CHANNELS.get(editing_wav_ch_var.get(), 1)
        dst = unique_path(
            os.path.splitext(src)[0] + f"_{rate // 1000}k.wav")

        clear_log()
        log(f"Converting {os.path.basename(src)}")
        log(f"  to {rate} Hz, "
            f"{'mono' if channels == 1 else 'stereo'}, 16-bit PCM WAV\n")
        set_running(True)

        def work():
            try:
                out = export_editing_wav(src, dst, rate, channels, log=log)
                if out:
                    log(f"Done.\n{out}")
                    root.after(0, lambda: reveal_file(out))
                else:
                    log("Conversion failed; see the message above.")
            except Exception as exc:
                log(f"\nSomething went wrong:\n  "
                    f"{type(exc).__name__}: {exc}")
            finally:
                root.after(0, lambda: set_running(False))

        threading.Thread(target=work, daemon=True).start()

    gen_btn = ttk.Button(btnbar, text="Generate audio",
                         command=lambda: start("generate"))
    gen_btn.pack(side="right", padx=4)
    def open_preferences_dialog():
        """Settings true across every document, not just the current
        render: engine environments, and podcast channel metadata."""
        from . import setup_engines as se

        win = tk.Toplevel(root)
        win.title("Preferences")
        win.geometry("640x460")
        win.transient(root)

        prefs_nb = ttk.Notebook(win)
        prefs_nb.pack(fill="both", expand=True, padx=12, pady=12)
        frame = ttk.Frame(prefs_nb, padding=12)
        prefs_nb.add(frame, text="Engines")

        ttk.Label(frame, text="Engine environments",
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(frame,
                 text="Each engine needs its own environment, because they "
                      "depend on conflicting versions of the same libraries. "
                      "This builds one for you. It downloads several GB and "
                      "takes a while; the window stays responsive.",
                 foreground="#666", wraplength=560,
                 justify="left").pack(anchor="w", pady=(2, 10))

        # Where environments live. Defaults to the app's own folder; can be
        # pointed at an older copy of Narrator (or anywhere kokoro-env /
        # qwen-env already exist) so a fresh copy of the app reuses them
        # instead of downloading everything again. Model weights are not
        # affected either way: the engines keep those in the Hugging Face
        # cache under your user profile, shared by every copy of the app.
        envrow = ttk.Frame(frame)
        envrow.pack(fill="x", pady=(0, 8))
        ttk.Label(envrow, text="Environments folder").pack(side="left")
        env_var = tk.StringVar(value=settings.get("env_root") or "")
        env_entry = ttk.Entry(envrow, textvariable=env_var)
        env_entry.pack(side="left", fill="x", expand=True, padx=6)

        def apply_env_root(path):
            path = (path or "").strip()
            if path and not os.path.isdir(path):
                messagebox.showwarning(
                    "Folder not found", f"{path}\n\ndoesn't exist.",
                    parent=win)
                return
            env_var.set(path)
            if path:
                settings["env_root"] = path
            else:
                settings.pop("env_root", None)
            save_settings(settings)
            forget_engine_probes()
            refresh_rows()

        def browse_env_root():
            chosen = filedialog.askdirectory(
                parent=win, title="Folder that contains kokoro-env / "
                                  "qwen-env (e.g. an older Narrator folder)",
                initialdir=env_var.get() or APP_DIR)
            if chosen:
                apply_env_root(chosen)

        ttk.Button(envrow, text="Browse...",
                  command=browse_env_root).pack(side="left")
        ttk.Button(envrow, text="Use app folder",
                  command=lambda: apply_env_root("")).pack(side="left",
                                                           padx=(4, 0))
        env_entry.bind("<Return>", lambda e: apply_env_root(env_var.get()))
        ttk.Label(frame,
                 text="Leave empty to use this app's own folder. Point it at "
                      "an older Narrator folder to reuse the environments "
                      "built there. (Already-downloaded model weights are "
                      "shared automatically -- they live in your user "
                      "profile, not in the app folder.)",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 8))

        rows = ttk.Frame(frame)
        rows.pack(fill="x")
        buttons = {}

        def refresh_rows():
            for child in rows.winfo_children():
                child.destroy()
            for r, (key, spec) in enumerate(se.ENGINE_SPECS.items()):
                exists, exe, importable = se.engine_status(key)
                state = ("ready" if importable else
                        "folder exists, engine missing" if exists else
                        "not set up")
                if importable and exe and spec["folder"]:
                    # Show WHICH environment was found, so a reused older
                    # install is visibly different from a fresh one.
                    same = (os.path.normcase(os.path.abspath(exe)) ==
                            os.path.normcase(os.path.abspath(sys.executable)))
                    if same:
                        state += "  (this Python)"
                    else:
                        where = os.path.dirname(os.path.dirname(exe))
                        state += f"  ({os.path.basename(where)})"
                ttk.Label(rows, text=spec["label"]).grid(
                    row=r, column=0, sticky="w", pady=3)
                ttk.Label(rows, text=state, foreground=(
                    "#2a7a2a" if importable else "#b33")).grid(
                    row=r, column=1, sticky="w", padx=10)
                b = ttk.Button(rows, text="Set up",
                              state="disabled" if exists else "normal",
                              command=lambda k=key: build(k))
                b.grid(row=r, column=2, sticky="e", padx=4)
                buttons[key] = b
            rows.columnconfigure(1, weight=1)

        def build(key):
            for b in buttons.values():
                b.config(state="disabled")
            win.destroy()
            clear_log()
            log("Setting up an engine environment.")
            log("This downloads several GB. Progress appears below.\n")
            set_running(True)

            def work():
                try:
                    se.create_environment(key, log=log)
                    log("\nReopen the app to pick the engine up.")
                except Exception as exc:
                    log(f"\nSetup failed:\n  {type(exc).__name__}: {exc}")
                finally:
                    root.after(0, lambda: set_running(False))

            threading.Thread(target=work, daemon=True).start()

        refresh_rows()

        ttk.Label(frame,
                 text="edge-tts installs into the Python running this app "
                      "rather than a folder of its own. Supporting programs "
                      "(ffmpeg, pandoc, espeak-ng) are installed normally, "
                      "not through this. None of it needs administrator "
                      "rights.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=560, justify="left").pack(anchor="w", pady=(12, 0))

        # --- podcast channel settings: true for every episode, so they
        # live here rather than on a per-document tab. ---
        pod_tab = ttk.Frame(prefs_nb, padding=12)
        prefs_nb.add(pod_tab, text="Podcast")
        pod_tab.columnconfigure(1, weight=1)
        pod = load_podcast_settings()
        pod_vars = {}
        pod_fields = [
            ("title", "Podcast title"), ("author", "Author / host name"),
            ("email", "Owner email (required by Apple/Spotify)"),
            ("description", "Podcast description"),
            ("website", "Website (optional; falls back to the hosting URL)"),
            ("audio_base_url", "Hosting URL for the audio files (where "
                               "you'll upload narrator_output/ to)"),
            ("artwork_url", "Artwork URL (square, 1400-3000px, already "
                            "hosted somewhere)"),
            ("category", "Apple Podcasts category (e.g. Education)"),
            ("language", "Language code (e.g. en-us)"),
        ]
        for r, (key, label) in enumerate(pod_fields):
            ttk.Label(pod_tab, text=label).grid(
                row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=pod.get(key, ""))
            ttk.Entry(pod_tab, textvariable=v).grid(
                row=r, column=1, sticky="ew", padx=8, pady=3)
            pod_vars[key] = v
        pod_explicit_var = tk.BooleanVar(value=bool(pod.get("explicit")))
        ttk.Checkbutton(pod_tab, text="Contains explicit content",
                        variable=pod_explicit_var).grid(
            row=len(pod_fields), column=0, columnspan=2, sticky="w",
            pady=(6, 0))
        ttk.Label(pod_tab,
                 text="This feeds the RSS feed podcast apps subscribe to. "
                      "Each individual episode's own title and notes are "
                      "set from the Publish tab when you publish it, not "
                      "here.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=520, justify="left").grid(
            row=len(pod_fields) + 1, column=0, columnspan=2, sticky="w",
            pady=(8, 0))

        def save_podcast(*_):
            data = {k: v.get().strip() for k, v in pod_vars.items()}
            data["explicit"] = bool(pod_explicit_var.get())
            save_podcast_settings(data)

        for v in pod_vars.values():
            v.trace_add("write", save_podcast)
        pod_explicit_var.trace_add("write", save_podcast)

        # --- intro / outro: one pair of assets for every episode, so
        # they belong here rather than on a per-render tab. ---
        audio_tab = ttk.Frame(prefs_nb, padding=12)
        prefs_nb.add(audio_tab, text="Intro / outro")
        audio_tab.columnconfigure(1, weight=1)
        ttk.Label(audio_tab,
                 text="Optional music or a spoken tag joined onto every "
                      "narration, crossfaded so nothing starts or stops "
                      "abruptly. Subtitles and chapter marks are shifted "
                      "to match automatically.",
                 foreground="#666", wraplength=540, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        bed_vars = {}
        for r, (key, label) in enumerate((("intro_audio", "Intro file"),
                                         ("outro_audio", "Outro file")),
                                        start=1):
            ttk.Label(audio_tab, text=label).grid(row=r, column=0, sticky="w",
                                                  pady=3)
            var = tk.StringVar(value=settings.get(key, "") or "")
            bed_vars[key] = var
            ttk.Entry(audio_tab, textvariable=var).grid(
                row=r, column=1, sticky="ew", padx=8, pady=3)

            def choose(k=key, v=var):
                path = filedialog.askopenfilename(
                    title="Choose an audio file", parent=win,
                    filetypes=[("Audio", "*.mp3 *.m4a *.wav *.flac *.ogg"),
                               ("All files", "*.*")])
                if path:
                    v.set(path)

            def clear(v=var):
                v.set("")

            btns = ttk.Frame(audio_tab)
            btns.grid(row=r, column=2, sticky="w")
            ttk.Button(btns, text="Browse...", command=choose).pack(
                side="left")
            ttk.Button(btns, text="Clear", command=clear).pack(
                side="left", padx=(4, 0))

        ttk.Label(audio_tab, text="Crossfade (seconds)").grid(
            row=3, column=0, sticky="w", pady=3)
        crossfade_var = tk.StringVar(
            value=str(settings.get("intro_crossfade", 1.0)))
        ttk.Spinbox(audio_tab, from_=0, to=10, increment=0.5, width=6,
                    textvariable=crossfade_var).grid(
            row=3, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(audio_tab,
                 text="0 joins them with no overlap at all.",
                 foreground="#666", font=("TkDefaultFont", 8)).grid(
            row=4, column=1, sticky="w", padx=8)

        def save_bed(*_):
            for k, v in bed_vars.items():
                settings[k] = v.get().strip()
            try:
                settings["intro_crossfade"] = max(
                    0.0, float(crossfade_var.get() or 0))
            except ValueError:
                pass
            save_settings(settings)

        for v in bed_vars.values():
            v.trace_add("write", save_bed)
        crossfade_var.trace_add("write", save_bed)

        # --- pacing: how much silence sits between the pieces, and how
        # expressive Qwen3 is allowed to be. Both are trades, so both are
        # dials rather than constants. ---
        pace_tab = ttk.Frame(prefs_nb, padding=12)
        prefs_nb.add(pace_tab, text="Pacing")
        pace_tab.columnconfigure(1, weight=1)
        ttk.Label(pace_tab,
                 text="Each part already ends on its own natural pause; "
                      "these set how much silence is added on top. Audio "
                      "is trimmed first, so the number below is the pause "
                      "you actually get. Lower it if narration sounds "
                      "over-punctuated or metronomic -- especially with "
                      "many small parts.",
                 foreground="#666", wraplength=540, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(pace_tab, text="Pause between parts (seconds)").grid(
            row=1, column=0, sticky="w", pady=3)
        gap_var = tk.StringVar(
            value=str(settings.get("chunk_gap", DEFAULT_CHUNK_GAP)))
        ttk.Spinbox(pace_tab, from_=0, to=2, increment=0.02, width=6,
                    textvariable=gap_var).grid(row=1, column=1, sticky="w",
                                               padx=8, pady=3)

        ttk.Label(pace_tab, text="Pause between sentences (Qwen3)").grid(
            row=2, column=0, sticky="w", pady=3)
        qgap_var = tk.StringVar(
            value=str(settings.get("qwen_group_gap", QWEN_GROUP_GAP)))
        ttk.Spinbox(pace_tab, from_=0, to=1, increment=0.02, width=6,
                    textvariable=qgap_var).grid(row=2, column=1, sticky="w",
                                                padx=8, pady=3)

        ttk.Label(pace_tab, text="Expressiveness (Qwen3)").grid(
            row=3, column=0, sticky="w", pady=(10, 3))
        expr_var = tk.DoubleVar(value=float(
            settings.get("expressiveness", 0.6)))
        expr_scale = ttk.Scale(pace_tab, from_=0.0, to=1.0,
                               variable=expr_var, orient="horizontal")
        expr_scale.grid(row=3, column=1, sticky="ew", padx=8, pady=(10, 3))
        expr_note = ttk.Label(pace_tab, text="", foreground="#666",
                             font=("TkDefaultFont", 8), wraplength=520,
                             justify="left")
        expr_note.grid(row=4, column=1, sticky="w", padx=8)

        def describe_expr(*_):
            frac = expr_var.get()
            lo, hi = EXPRESSIVENESS_RANGE
            temp = lo + (hi - lo) * frac
            if frac < 0.3:
                mood = ("steadiest voice, flattest reading -- the safest "
                        "choice for a long narration")
            elif frac < 0.7:
                mood = "a balance of steady voice and natural variation"
            else:
                mood = ("liveliest reading, but the voice is more likely "
                        "to shift between parts")
            expr_note.config(text=f"temperature {temp:.2f} -- {mood}.")

        def save_pace(*_):
            for key, var, lo, hi in (("chunk_gap", gap_var, 0.0, 2.0),
                                    ("qwen_group_gap", qgap_var, 0.0, 1.0)):
                try:
                    settings[key] = max(lo, min(hi, float(var.get() or 0)))
                except ValueError:
                    pass
            settings["expressiveness"] = round(expr_var.get(), 3)
            describe_expr()
            save_settings(settings)

        gap_var.trace_add("write", save_pace)
        qgap_var.trace_add("write", save_pace)
        expr_scale.config(command=save_pace)
        describe_expr()

        # --- the real per-model knobs, for when the simple dials above
        # aren't enough. Only parameters the engine genuinely accepts are
        # listed; the registry is the single source of truth. ---
        adv_tab = ttk.Frame(prefs_nb, padding=12)
        prefs_nb.add(adv_tab, text="Model parameters")
        adv_tab.columnconfigure(1, weight=1)
        ttk.Label(adv_tab,
                 text="Every value the installed models actually expose. "
                      "These override the simpler dials on the Pacing "
                      "tab. If a change makes things worse, Reset puts "
                      "the defaults back.",
                 foreground="#666", wraplength=540, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        adv_engine_var = tk.StringVar(value="qwen3")
        adv_body = ttk.Frame(adv_tab)
        adv_body.grid(row=2, column=0, columnspan=3, sticky="nsew")
        adv_body.columnconfigure(1, weight=1)
        engine_row = ttk.Frame(adv_tab)
        engine_row.grid(row=1, column=0, columnspan=3, sticky="w",
                        pady=(0, 8))
        ttk.Label(engine_row, text="Engine").pack(side="left")

        def build_param_rows(*_):
            for child in adv_body.winfo_children():
                child.destroy()
            key = adv_engine_var.get()
            spec = TUNABLE_PARAMS.get(key, [])
            if not spec:
                ttk.Label(adv_body,
                         text="This engine doesn't expose any tunable "
                              "generation parameters -- its speed and "
                              "voice are the only controls it has.",
                         foreground="#666", wraplength=520,
                         justify="left").grid(row=0, column=0,
                                              columnspan=3, sticky="w")
                return
            current = engine_params(key)
            vars_ = {}
            for r, (pkey, label, lo, hi, step, default,
                   helptext) in enumerate(spec):
                ttk.Label(adv_body, text=label).grid(row=r * 2, column=0,
                                                     sticky="w", pady=(6, 0))
                var = tk.StringVar(value=str(current[pkey]))
                vars_[pkey] = var
                ttk.Spinbox(adv_body, from_=lo, to=hi, increment=step,
                            width=8, textvariable=var).grid(
                    row=r * 2, column=1, sticky="w", padx=8, pady=(6, 0))
                ttk.Label(adv_body, text=f"default {default}",
                         foreground="#888",
                         font=("TkDefaultFont", 8)).grid(row=r * 2, column=2,
                                                          sticky="w")
                ttk.Label(adv_body, text=helptext, foreground="#666",
                         font=("TkDefaultFont", 8), wraplength=480,
                         justify="left").grid(row=r * 2 + 1, column=1,
                                              columnspan=2, sticky="w",
                                              padx=8)

            def save_params(*_):
                store = settings.setdefault("engine_params", {})
                block = store.setdefault(key, {})
                for pkey, var in vars_.items():
                    try:
                        block[pkey] = float(var.get())
                    except ValueError:
                        pass
                save_settings(settings)

            for var in vars_.values():
                var.trace_add("write", save_params)

            def reset():
                (settings.get("engine_params") or {}).pop(key, None)
                save_settings(settings)
                build_param_rows()

            ttk.Button(adv_body, text="Reset to defaults",
                      command=reset).grid(row=len(spec) * 2, column=1,
                                          sticky="w", padx=8, pady=(12, 0))

        adv_menu = ttk.Combobox(
            engine_row, textvariable=adv_engine_var, state="readonly",
            width=12, values=list(TUNABLE_PARAMS))
        adv_menu.pack(side="left", padx=8)
        adv_menu.bind("<<ComboboxSelected>>", build_param_rows)
        build_param_rows()

        ttk.Button(win, text="Close",
                  command=win.destroy).pack(side="bottom", anchor="e",
                                            padx=12, pady=(0, 12))

    sample_btn = ttk.Button(btnbar, text="Hear a sample",
                            command=lambda: start("sample"))
    sample_btn.pack(side="right", padx=4)
    compare_btn = ttk.Button(btnbar, text="Compare all voices",
                             command=lambda: start("compare"))
    compare_btn.pack(side="right", padx=4)
    open_btn = ttk.Button(btnbar, text="Open folder", command=open_folder)
    open_btn.pack(side="left", padx=8)
    fix_btn = ttk.Button(btnbar, text="Fix a chunk...",
                         command=open_fix_chunk_dialog)
    fix_btn.pack(side="left")
    timeline_btn = ttk.Button(btnbar, text="Timeline...",
                              command=lambda: open_timeline_editor())
    timeline_btn.pack(side="left", padx=6)

    # --- publish: RSS feed episode + transcript export ---
    def current_take():
        """Whichever finished take the Publish tab is pointed at. After a
        single render that is simply the last one; after a batch queue run
        several are available, and publishing the wrong document is a real
        mistake to make silently -- so it is an explicit choice."""
        return state["session"].take_named(take_pick_var.get())

    def refresh_publish_tab(*_):
        names = state["session"].take_names()
        take_pick_menu.config(values=names)
        if take_pick_var.get() not in names:
            latest = state["session"].last_render or {}
            take_pick_var.set(os.path.basename(latest.get("out_path", ""))
                             if latest else "")
        take_pick_menu.config(
            state="readonly" if len(names) > 1 else "disabled")
        lr = current_take()
        if lr and os.path.isfile(lr.get("out_path", "")):
            secs = duration_of(lr["out_path"]) or 0
            pub_status.config(
                foreground="#000",
                text=f"Ready to publish: {os.path.basename(lr['out_path'])}"
                     f"  ({secs / 60:.1f} min)")
            if not pub_title_var.get().strip():
                guess = os.path.splitext(
                    os.path.basename(lr.get("source_path") or ""))[0]
                pub_title_var.set(
                    guess.replace("_", " ").replace("-", " ").strip().title())
            publish_btn.config(state="normal")
        else:
            pub_status.config(
                foreground="#666",
                text="Render something on the Document/Voice/Output tabs "
                     "first, then come back here to publish it.")
            publish_btn.config(state="disabled")
        n = len(publish.load_episodes())
        feed_status.config(
            text=(f"{n} episode(s) currently in the feed "
                 f"(narrator_output/podcast.xml)." if n else
                 "No episodes published yet.") +
                " Channel details (hosting URL, artwork, etc.) are set "
                "under Settings -> Preferences -> Podcast.")

    def do_publish():
        lr = current_take()
        if not lr:
            return
        try:
            result = tasks_mod.publish_take(
                lr, pub_title_var.get(), pub_desc_box.get("1.0", "end"), log)
        except ValueError as exc:
            messagebox.showerror("Can't publish", str(exc), parent=root)
            return
        ep = result["episode"]
        if result["missing"]:
            log("  (set these under Settings -> Preferences -> Podcast)")
        if lr.get("source_path"):
            library.touch(lr["source_path"], status="published")
        refresh_publish_tab()
        refresh_library_list()

    def do_export_transcript():
        if not state["path"]:
            messagebox.showwarning("No file", "Choose a text file first.",
                                   parent=root)
            return
        try:
            folder = document_folder(state["root"], state["path"],
                                     use_subfolders_var.get())
            out_path = tasks_mod.export_transcript(state["path"], folder, log)
        except Exception as exc:
            messagebox.showerror("Couldn't export it",
                                 f"{type(exc).__name__}: {exc}", parent=root)
            return
        reveal_file(out_path)

    def do_generate_chapters():
        lr = current_take()
        if not lr or not os.path.isfile(lr.get("out_path", "")):
            messagebox.showwarning(
                "Nothing to work from",
                "Render something first, then come back here.", parent=root)
            return
        found, text = tasks_mod.chapters_for_take(lr, log)
        chapters_box.delete("1.0", "end")
        if not found:
            chapters_box.insert(
                "1.0", "No headings from this document could be matched "
                      "against this take -- either it has no headings, "
                      "or the source file has changed since this take "
                      "was rendered.")
            return
        chapters_box.insert("1.0", text)

    def do_embed_chapters():
        lr = current_take()
        if not lr or not os.path.isfile(lr.get("out_path", "")):
            messagebox.showwarning(
                "Nothing to work from",
                "Render something first, then come back here.", parent=root)
            return
        try:
            tasks_mod.embed_chapters_in_take(lr, log)
        except RuntimeError as exc:
            messagebox.showerror("Couldn't embed chapters", str(exc),
                                 parent=root)
            return

    gen_chapters_btn.config(command=do_generate_chapters)

    # --- library: the settings-per-document picker on the Document tab ---
    def refresh_library_list(*_):
        lib_list.delete(0, "end")
        for p in library.all_projects():
            status = library.STATUS_LABELS.get(p["status"], p["status"])
            when = library.relative_time(p.get("updated"))
            missing = "" if os.path.isfile(p["path"]) else "  [file missing]"
            lib_list.insert(
                "end", f"{status:<11} {p['label']}  -  {when}{missing}")
        lib_list._paths = [p["path"] for p in library.all_projects()]

    def selected_project_paths():
        sel = lib_list.curselection()
        if not sel or not hasattr(lib_list, "_paths"):
            return []
        return [lib_list._paths[i] for i in sel]

    def selected_project_path():
        sel = lib_list.curselection()
        if not sel or not hasattr(lib_list, "_paths"):
            return None
        return lib_list._paths[sel[0]]

    def load_project_into_ui(entry):
        path = entry["path"]
        if os.path.isfile(path):
            load_source_path(path)
        else:
            messagebox.showwarning(
                "File not found",
                f"{os.path.basename(path)} isn't at its saved location "
                "anymore. Its settings will still load below, but you'll "
                "need to browse to the file again before rendering.",
                parent=root)
            state["path"] = None
            filelabel.config(text="No file chosen", foreground="#777")

        cfg_saved = entry.get("cfg") or {}
        if not cfg_saved:
            log(f"Loaded {entry['label']} (no settings recorded for it "
               "yet -- it hasn't been rendered before).")
            return

        if cfg_saved.get("engine") in ENGINES:
            engine_var.set(cfg_saved["engine"])
        refresh_voices()
        refresh_option_visibility()
        s = spec()
        saved_voice = cfg_saved.get("voice")
        if saved_voice:
            if s["editable"]:
                voice_var.set(saved_voice)
            else:
                match = next((desc for vid, desc in s["voices"]
                            if vid == saved_voice), None)
                if match:
                    voice_var.set(match)
        if "take" in cfg_saved:
            take_var.set(cfg_saved["take"])
        if "speed" in cfg_saved:
            speed_var.set(cfg_saved["speed"])
            on_speed()
        if "chunk_count" in cfg_saved:
            chunk_var.set(cfg_saved["chunk_count"])
        if cfg_saved.get("chunk_mode") in CHUNK_MODE_LABELS:
            chunk_mode_var.set(CHUNK_MODE_LABELS[cfg_saved["chunk_mode"]])
        if cfg_saved.get("chunk_target"):
            chunk_target_var.set(int(cfg_saved["chunk_target"]))
        if cfg_saved.get("chars_per_token"):
            state["chars_per_token"] = cfg_saved["chars_per_token"]
        refresh_chunk_mode()
        if "subtitles" in cfg_saved:
            subtitles_var.set(cfg_saved["subtitles"])
        if "filename" in cfg_saved:
            filename_var.set(cfg_saved["filename"])
        if "format" in cfg_saved:
            format_var.set(cfg_saved["format"])
        if "sample_rate" in cfg_saved:
            samplerate_var.set(cfg_saved["sample_rate"])
        if "bit_depth" in cfg_saved:
            bitdepth_var.set(cfg_saved["bit_depth"])
        if "quality_pct" in cfg_saved:
            quality_var.set(cfg_saved["quality_pct"])
        refresh_format()
        if "use_subfolders" in cfg_saved:
            use_subfolders_var.set(cfg_saved["use_subfolders"])
        if "keep_chunks" in cfg_saved:
            keep_chunks_var.set(cfg_saved["keep_chunks"])
        if "editing_wav" in cfg_saved:
            editing_wav_var.set(cfg_saved["editing_wav"])
        if "editing_wav_rate" in cfg_saved:
            editing_wav_rate_var.set(cfg_saved["editing_wav_rate"])
        if "editing_wav_channels" in cfg_saved:
            reverse_ch = {v: k for k, v in EDITING_WAV_CHANNELS.items()}
            editing_wav_ch_var.set(
                reverse_ch.get(cfg_saved["editing_wav_channels"], "Mono"))
        refresh_wav_row()
        if "make_video" in cfg_saved:
            make_video_var.set(cfg_saved["make_video"])
        refresh_video_row()
        vi = cfg_saved.get("video_image")
        if vi:
            state["video_image"] = vi
            if os.path.isfile(vi):
                video_image_label.config(text=os.path.basename(vi),
                                        foreground="#000")
            else:
                video_image_label.config(text="No image chosen",
                                        foreground="#777")
        log(f"Loaded {entry['label']}'s settings from the library.")

    def do_load_selected():
        path = selected_project_path()
        if not path:
            messagebox.showinfo("Nothing selected",
                                "Pick a document in the list first.",
                                parent=root)
            return
        entry = next((p for p in library.load_projects()
                     if p["path"] == path), None)
        if entry:
            load_project_into_ui(entry)
            refresh_library_list()

    def do_remove_selected():
        path = selected_project_path()
        if not path:
            return
        if messagebox.askyesno(
                "Remove from library",
                f"Remove {os.path.basename(path)} from the library? Its "
                "saved settings will be forgotten -- the document and any "
                "audio already rendered are untouched.", parent=root):
            library.remove(path)
            refresh_library_list()

    lib_load_btn.config(command=do_load_selected)
    lib_remove_btn.config(command=do_remove_selected)
    lib_list.bind("<Double-Button-1>", lambda _e: do_load_selected())
    refresh_library_list()
    embed_chapters_btn.config(command=do_embed_chapters)
    publish_btn.config(command=do_publish)
    transcript_btn.config(command=do_export_transcript)
    refresh_engine_setup()
    notebook.bind("<<NotebookTabChanged>>", refresh_publish_tab, add="+")
    notebook.bind("<<NotebookTabChanged>>", refresh_library_list, add="+")
    refresh_publish_tab()

    settings_menu = tk.Menu(menubar, tearoff=False)
    settings_menu.add_command(label="Preferences...",
                              command=open_preferences_dialog)
    menubar.add_cascade(label="Settings", menu=settings_menu)

    tools_menu = tk.Menu(menubar, tearoff=False)

    text_menu = tk.Menu(tools_menu, tearoff=False)
    text_menu.add_command(label="Clean text only",
                          command=lambda: start("clean"))
    text_menu.add_command(label="Check pronunciation...",
                          command=lambda: open_pronunciation_dialog())
    text_menu.add_command(label="Edit a word's pronunciation...",
                          command=lambda: open_word_editor())
    text_menu.add_command(label="Export transcript (.md)",
                          command=lambda: do_export_transcript())
    tools_menu.add_cascade(label="Text tools", menu=text_menu)

    convert_menu = tk.Menu(tools_menu, tearoff=False)
    convert_menu.add_command(label="Convert audio...",
                             command=lambda: open_converter_dialog())
    convert_menu.add_command(label="Quick editing WAV...",
                             command=convert_audio_to_wav)
    convert_menu.add_command(label="Audio to text (transcribe)...",
                             command=lambda: open_transcribe_dialog())
    tools_menu.add_command(label="Voice studio...",
                           command=lambda: open_voice_studio())
    tools_menu.add_command(label="Components and add-ons...",
                           command=lambda: open_components_dialog())
    tools_menu.add_command(label="Audiogram layout...",
                           command=lambda: open_audiogram_dialog())
    tools_menu.add_command(label="Audiogram command builder...",
                           command=lambda: open_ffgram_builder())
    tools_menu.add_cascade(label="Convert", menu=convert_menu)

    tools_menu.add_separator()
    tools_menu.add_command(label="Open a take...",
                           command=lambda: open_take_from_manifest())
    tools_menu.add_command(label="Open output folder", command=open_folder)
    menubar.add_cascade(label="Tools", menu=tools_menu)

    missing = [n for n, s in ENGINES.items() if not s["detect"]()]
    if missing:
        log("Not installed yet: " + ", ".join(m.split(" (")[0]
                                              for m in missing))
    if not have_ffmpeg() and have_edge():
        log("Note: ffmpeg not found. Everything works, but installing it "
            "gives cleaner joins and even volume.")
    if not _have("pandoc"):
        log("Note: pandoc not found. .txt and .md files work fine; "
            ".docx/.odt/.html/.tex/.epub will need pandoc installed "
            "(pandoc.org) to be read.")

    drain()
    root.mainloop()
