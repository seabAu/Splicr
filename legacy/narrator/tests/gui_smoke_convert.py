import os, sys, traceback, shutil, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
import tkinter as tk
from tkinter import ttk, filedialog
from narrator import pipeline, config
for s in pipeline.ENGINES.values(): s["detect"] = lambda: True

D = "/tmp/convert_smoke"
shutil.rmtree(D, ignore_errors=True)
os.makedirs(D)
srcs = []
for i in range(3):
    p = os.path.join(D, f"clip{i}.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={200+i*50}:duration=2",
                    "-ar", "44100", p], capture_output=True, check=True)
    srcs.append(p)
# a file that will fail to convert (not real audio), to exercise the
# batch continuing past one bad file rather than aborting
bad = os.path.join(D, "not_audio.wav")
open(bad, "w").write("this is not an audio file")

rep = []
def walk(w):
    yield w
    for c in w.winfo_children(): yield from walk(c)

orig = tk.Tk.mainloop
def fake(self, *a):
    def go():
        try:
            # first askopenfilenames call returns the two good files
            calls = {"n": 0}
            def fake_pick(*a, **k):
                calls["n"] += 1
                if calls["n"] == 1:
                    return (srcs[0], srcs[1])
                return (srcs[2],)  # the "Browse... add more" call
            filedialog.askopenfilenames = fake_pick

            menu = self.nametowidget(self.cget("menu"))
            ci = [i for i in range(menu.index("end")+1)
                 if menu.type(i) == "cascade"]
            tools = self.nametowidget(menu.entrycget(
                [i for i in ci if menu.entrycget(i, "label") == "Tools"][0],
                "menu"))
            real = {tools.entrycget(i, "label"): i
                   for i in range(tools.index("end")+1)
                   if tools.type(i) != "separator"}
            convert_menu = self.nametowidget(
                tools.entrycget(real["Convert"], "menu"))
            cvals = {convert_menu.entrycget(i, "label"): i
                    for i in range(convert_menu.index("end")+1)
                    if convert_menu.type(i) != "separator"}
            convert_menu.invoke(cvals["Convert audio..."])
            self.after(600, step2)
        except Exception:
            rep.append("STEP1 ERROR\n" + traceback.format_exc())
            self.destroy()

    def step2():
        try:
            win = [w for w in walk(self) if isinstance(w, tk.Toplevel)][-1]
            src_list = [w for w in walk(win) if isinstance(w, tk.Listbox)][0]
            n0 = src_list.size()
            assert n0 == 2, f"expected 2 files from multi-select, got {n0}"
            rep.append(f"multi-select at open populated the list with "
                      f"{n0} files")

            browse_btn = [w for w in walk(win) if isinstance(w, ttk.Button)
                         and "Browse" in str(w.cget("text"))][0]
            browse_btn.invoke()
            self.update()
            n1 = src_list.size()
            assert n1 == 3, f"expected 3 after Browse-add, got {n1}"
            rep.append("Browse (add more) appended a file without "
                      "closing the dialog")

            # add the deliberately-bad file directly to the in-memory list
            # via another Browse call, to exercise partial-failure handling
            from tkinter import filedialog as fd
            fd.askopenfilenames = lambda *a, **k: (bad,)
            browse_btn.invoke()
            self.update()
            assert src_list.size() == 4
            rep.append("batch now has 3 good files + 1 deliberately bad "
                      "file, to test the batch survives one failure")

            fmt_menu = [w for w in walk(win) if isinstance(w, ttk.Combobox)
                       and any("WAV" in v for v in w.cget("values"))]
            assert fmt_menu, "no format selector found"

            go_btn = [w for w in walk(win) if isinstance(w, ttk.Button)
                     and w.cget("text") == "Convert"][0]
            go_btn.invoke()
            self.after(6000, step3)
        except Exception:
            rep.append("STEP2 ERROR\n" + traceback.format_exc())
            self.destroy()

    def step3():
        try:
            win = [w for w in walk(self) if isinstance(w, tk.Toplevel)][-1]
            status = [w for w in walk(win) if isinstance(w, ttk.Label)
                     and ("converted" in str(w.cget("text")).lower()
                          or "failed" in str(w.cget("text")).lower()
                          or "done" in str(w.cget("text")).lower())]
            assert status, "no completion status shown"
            text = status[-1].cget("text")
            rep.append(f"batch completion status: {text}")
            assert "3/4" in text or ("3" in text and "1" in text), text
            made = [f for f in os.listdir(D) if "_converted" in f]
            rep.append(f"converted files on disk: {sorted(made)}")
            assert len(made) == 3, made
            win.destroy()
        except Exception:
            rep.append("STEP3 ERROR\n" + traceback.format_exc())
        self.destroy()

    self.after(600, go)
    orig(self, *a)

tk.Tk.mainloop = fake
from narrator.ui import launch
try:
    launch()
except SystemExit:
    pass
print("\n".join(rep))
if any("ERROR" in r for r in rep):
    sys.exit(1)
print("ALL CONVERT SMOKE TESTS PASSED")
