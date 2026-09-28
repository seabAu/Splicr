"""A first-run setup wizard.

Welcome, engine choice, and a real progress page -- the shape of a classic
installer, built in tkinter rather than compiled, so it runs the same way
the rest of this app does and needed no new tools to build or test.

This is deliberately NOT a compiled Windows .exe/.msi installer. Producing
one reliably needs to be built and verified ON Windows (PyInstaller does not
cross-compile: run it on Linux and you get a Linux binary, not a Windows
one), which the environment this was written in cannot do. What follows
instead is a wizard that runs the moment you launch the app, using exactly
the engine-installation code in setup_engines.py, with nothing about its
correctness left unverified.
"""

import os
import queue
import threading

from .config import APP_DIR
from . import setup_engines as se


def needs_wizard():
    """True if neither offline engine is set up yet -- the condition the app
    checks on every normal launch to decide whether to show this first.
    edge-tts doesn't count: having it doesn't mean setup happened."""
    return not any(se.engine_status(k)[2]
                   for k, spec in se.ENGINE_SPECS.items() if spec["folder"])


def run_wizard(root):
    """Show the wizard as a modal sequence of pages inside `root`. Returns
    once the person closes it, whether or not they set anything up -- the
    main window always continues to load either way, since edge-tts needs
    no setup at all and works regardless."""
    import tkinter as tk
    from tkinter import ttk

    win = tk.Toplevel(root)
    win.title("Set up Narrator")
    win.geometry("640x460")
    # NOT win.transient(root). The main window is withdrawn while this runs,
    # and Tk makes a transient window inherit its master's state when it is
    # first mapped -- so a transient of a withdrawn root is itself created
    # withdrawn: never drawn, yet holding a grab and blocking in
    # wait_window(). That was the "terminal open, nothing happens" launch
    # on a fresh machine. Reproduced under a virtual display: with
    # transient() the window's state is "withdrawn" and winfo_viewable() is
    # 0; without it, "normal" and 1.
    win.resizable(False, False)
    win.deiconify()
    win.lift()
    win.focus_force()
    # Briefly topmost so it comes up in front of the terminal that launched
    # it, then released so it behaves like an ordinary window.
    win.attributes("-topmost", True)
    win.after(400, lambda: win.attributes("-topmost", False))
    win.protocol("WM_DELETE_WINDOW", win.destroy)  # closing it = skip
    win.grab_set()

    state = {"chosen": set(), "page": 0}

    body = ttk.Frame(win, padding=24)
    body.pack(fill="both", expand=True)
    navbar = ttk.Frame(win, padding=(24, 0, 24, 16))
    navbar.pack(fill="x", side="bottom")

    def clear_body():
        for w in body.winfo_children():
            w.destroy()

    # ---- Page 0: welcome ---------------------------------------------

    def page_welcome():
        clear_body()
        ttk.Label(body, text="Welcome to Narrator",
                 font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(body,
                 text="Turn documents into narrated audio, entirely on "
                      "this machine.\n\n"
                      "edge-tts is a 10 MB download that works right away "
                      "(it needs internet while narrating). Kokoro and "
                      "Qwen3-TTS are higher-quality offline engines, but "
                      "each needs its own environment and a download of a "
                      "few gigabytes -- optional, and can be done later "
                      "from \"Set up engines...\" in the main window if "
                      "you'd rather skip it now.\n\n"
                      "Nothing here needs administrator rights, and "
                      "everything is installed beside this folder or in "
                      "your own user profile.",
                 wraplength=560, justify="left", foreground="#333"
                 ).pack(anchor="w", pady=(14, 0))
        back_btn.config(state="disabled")
        next_btn.config(text="Next >", command=page_choose)

    # ---- Page 1: choose engines ---------------------------------------

    def page_choose():
        clear_body()
        ttk.Label(body, text="Choose what to set up",
                 font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(body,
                 text="Tick any you want now. Nothing is required -- "
                      "edge-tts needs none of this.",
                 foreground="#666", wraplength=560).pack(
            anchor="w", pady=(4, 14))

        vars_ = {}
        nothing_works = not any(se.engine_status(k)[2]
                                for k in se.ENGINE_SPECS)
        for key, spec in se.ENGINE_SPECS.items():
            exists, _exe, importable = se.engine_status(key)
            row = ttk.Frame(body)
            row.pack(fill="x", pady=4)
            # Pre-tick edge-tts when there is no working engine at all, so
            # "Next, Next, Finish" leaves the person with something usable.
            v = tk.BooleanVar(value=(key == "edge" and nothing_works))
            cb = ttk.Checkbutton(row, text=spec["label"], variable=v)
            cb.pack(side="left")
            if importable:
                ttk.Label(row, text="already set up",
                         foreground="#2a7a2a").pack(side="left", padx=10)
                cb.config(state="disabled")
            elif exists:
                ttk.Label(row, text="folder exists but incomplete",
                         foreground="#b33").pack(side="left", padx=10)
                cb.config(state="disabled")
            else:
                vars_[key] = v
            if spec.get("notes"):
                ttk.Label(body, text="  " + spec["notes"],
                         foreground="#666", font=("TkDefaultFont", 8)
                         ).pack(anchor="w")

        ttk.Label(body,
                 text="Downloads several GB total if both are ticked. You "
                      "can also do this later, one at a time.",
                 foreground="#666", font=("TkDefaultFont", 8),
                 wraplength=560).pack(anchor="w", pady=(14, 0))

        def go_next():
            state["chosen"] = {k for k, v in vars_.items() if v.get()}
            if state["chosen"]:
                page_progress()
            else:
                page_finish(skipped=True)

        back_btn.config(state="normal", command=page_welcome)
        next_btn.config(text="Next >", command=go_next)

    # ---- Page 2: progress ----------------------------------------------

    def page_progress():
        clear_body()
        ttk.Label(body, text="Setting up",
                 font=("TkDefaultFont", 13, "bold")).pack(anchor="w")

        current_label = ttk.Label(body, text="Starting...",
                                  wraplength=560)
        current_label.pack(anchor="w", pady=(14, 4))

        stage_bar = ttk.Progressbar(body, length=560, mode="determinate",
                                    maximum=100)
        stage_bar.pack(fill="x", pady=(0, 10))

        detail_label = ttk.Label(body, text="", foreground="#666",
                                 wraplength=560)
        detail_label.pack(anchor="w")

        detail_bar = ttk.Progressbar(body, length=560, mode="indeterminate")

        log_box = tk.Text(body, height=8, wrap="word",
                          font=("TkFixedFont", 8), foreground="#555")
        log_box.pack(fill="both", expand=True, pady=(14, 0))
        log_box.config(state="disabled")

        def append_log(msg):
            log_box.config(state="normal")
            log_box.insert("end", str(msg) + "\n")
            log_box.see("end")
            log_box.config(state="disabled")

        back_btn.config(state="disabled")
        next_btn.config(state="disabled")

        events = queue.Queue()
        engines_to_do = list(state["chosen"])
        results = {}

        def worker():
            for key in engines_to_do:
                events.put(("engine_start", key))
                try:
                    ok = se.create_environment(
                        key,
                        log=lambda m: events.put(("log", m)),
                        progress=lambda e, k=key: events.put(
                            ("progress", k, e)))
                except Exception as exc:  # never leave the page stuck
                    events.put(("log", f"  ! {type(exc).__name__}: {exc}"))
                    ok = False
                results[key] = ok
                events.put(("engine_done", key, ok))
            events.put(("all_done", None))

        threading.Thread(target=worker, daemon=True).start()

        def pump():
            try:
                while True:
                    item = events.get_nowait()
                    kind = item[0]

                    if kind == "log":
                        append_log(item[1])

                    elif kind == "engine_start":
                        current_label.config(
                            text=f"{se.ENGINE_SPECS[item[1]]['label']}")

                    elif kind == "progress":
                        e = item[2]
                        if e["kind"] == "stage":
                            stage_bar["value"] = (
                                100 * e["step"] / e["total"])
                            detail_label.config(text=e["label"] + "...")
                            detail_bar.pack_forget()
                        elif e["kind"] == "downloading":
                            detail_label.config(
                                text=f"Downloading {e['name']} "
                                    f"({e['size']}) -- this can take a "
                                    f"while depending on your connection.")
                            detail_bar.pack(fill="x", pady=(4, 0))
                            detail_bar.start(12)
                        elif e["kind"] == "downloaded":
                            detail_bar.stop()
                            detail_bar.pack_forget()

                    elif kind == "engine_done":
                        _key, ok = item[1], item[2]
                        detail_bar.stop()
                        detail_bar.pack_forget()

                    elif kind == "all_done":
                        page_finish(results=results)
                        return
            except queue.Empty:
                pass
            win.after(80, pump)

        pump()

    # ---- Page 3: finish -------------------------------------------------

    def page_finish(results=None, skipped=False):
        clear_body()
        ttk.Label(body, text="Done" if not skipped else "Skipped",
                 font=("TkDefaultFont", 14, "bold")).pack(anchor="w")

        if skipped:
            ttk.Label(body,
                     text="Nothing was set up. edge-tts is ready to use "
                          "right now; the others are available any time "
                          "from \"Set up engines...\" in the main window.",
                     wraplength=560, justify="left").pack(
                anchor="w", pady=(10, 0))
        else:
            for key, ok in (results or {}).items():
                label = se.ENGINE_SPECS[key]["label"]
                text = f"{'✓' if ok else '✗'}  {label}"
                ttk.Label(body, text=text,
                         foreground="#2a7a2a" if ok else "#b33",
                         font=("TkDefaultFont", 10, "bold")).pack(
                    anchor="w", pady=2)
            if not all((results or {}).values()):
                ttk.Label(body,
                         text="Something didn't finish. Scroll back to see "
                              "what happened, or try again from \"Set up "
                              "engines...\" in the main window -- it's "
                              "safe to retry.",
                         foreground="#666", wraplength=560).pack(
                    anchor="w", pady=(10, 0))

        back_btn.pack_forget()
        next_btn.config(text="Finish", state="normal", command=win.destroy)

    back_btn = ttk.Button(navbar, text="< Back")
    back_btn.pack(side="left")
    next_btn = ttk.Button(navbar, text="Next >")
    next_btn.pack(side="right")
    ttk.Button(navbar, text="Skip for now",
              command=win.destroy).pack(side="right", padx=8)

    page_welcome()
    win.wait_window()
