import os, sys, traceback, shutil, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
D = "/tmp/ffgui"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
src = f"{D}/a.wav"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","sine=frequency=300:duration=4","-ar","48000","-ac","2",
                src], capture_output=True, check=True)
import tkinter as tk
from tkinter import ttk, filedialog
filedialog.askopenfilename = lambda **k: src
from narrator import pipeline, config, ffgram
for s in pipeline.ENGINES.values(): s["detect"] = lambda: True
rep = []
def walk(w):
    yield w
    for c in w.winfo_children(): yield from walk(c)
def by_text(r, cls, t):
    return [w for w in walk(r) if isinstance(w, cls) and t in str(w.cget("text"))]
orig = tk.Tk.mainloop
def fake(self, *a):
    def go():
        try:
            menu = self.nametowidget(self.cget("menu"))
            ci = [i for i in range(menu.index("end")+1) if menu.type(i)=="cascade"]
            tools = self.nametowidget(menu.entrycget(
                [i for i in ci if menu.entrycget(i,"label")=="Tools"][0], "menu"))
            real = {tools.entrycget(i,"label"): i for i in range(tools.index("end")+1)
                   if tools.type(i) != "separator"}
            assert "Audiogram command builder..." in real, list(real)
            tools.invoke(real["Audiogram command builder..."])
            self.after(1200, step2)
        except Exception:
            rep.append("STEP1 ERROR\n"+traceback.format_exc()); self.destroy()

    def step2():
        try:
            win = [w for w in walk(self) if isinstance(w, tk.Toplevel)][-1]
            texts = [w for w in walk(win) if w.winfo_class() == "Text"]
            cmd = [t for t in texts if "ffmpeg" in t.get("1.0","end")][0]
            why = [t for t in texts if "Waveform" in t.get("1.0","end")]
            assert why, "no explanation shown"
            rep.append(f"command: {cmd.get('1.0','end').strip()[:95]}...")
            rep.append(f"explains: {why[0].get('1.0','end').strip().splitlines()[0]}")

            # the visualiser list is generated from the registry
            vis = [c for c in walk(win) if isinstance(c, ttk.Combobox)
                  and "Waveform" in c.cget("values")][0]
            assert len(vis.cget("values")) == len(ffgram.SOURCES)
            rep.append(f"visualisers offered: {list(vis.cget('values'))}")

            # switching visualiser rebuilds its options AND the command
            vis.set("Spectrogram"); vis.event_generate("<<ComboboxSelected>>")
            self.update()
            after = cmd.get("1.0","end")
            assert "showspectrum" in after, after[:200]
            # showspectrum has no rate option -- the command must not add one
            assert ":r=" not in after.split("showspectrum")[1].split(",")[0]
            rep.append("switching to Spectrogram rebuilt the command and "
                      "correctly omitted the rate option it doesn't accept")

            vis.set("Waveform"); vis.event_generate("<<ComboboxSelected>>")
            self.update()

            # add an effect from the registry and see it in the command
            fxc = [c for c in walk(win) if isinstance(c, ttk.Combobox)
                  and "Bend into a ring" in c.cget("values")][0]
            fxc.set("Bend into a ring")
            by_text(win, ttk.Button, "Add")[0].invoke()
            self.update()
            assert "v360" in cmd.get("1.0","end")
            rep.append("adding the ring effect put v360 into the command")

            # ordering: add blur, then move it up, and watch the order change
            fxc.set("Blur"); by_text(win, ttk.Button, "Add")[0].invoke()
            self.update()
            text_before = cmd.get("1.0","end")
            assert text_before.index("v360") < text_before.index("gblur")
            lb = [w for w in walk(win) if isinstance(w, tk.Listbox)][0]
            rows = [lb.get(i) for i in range(lb.size())]
            rep.append(f"effect stack: {rows}")
            # Select by name: the default spec already contains a resize,
            # so a fixed index picks the wrong entry.
            blur_at = rows.index("Blur")
            lb.selection_clear(0,"end"); lb.selection_set(blur_at)
            by_text(win, ttk.Button, "Up")[0].invoke()
            self.update()
            text_after = cmd.get("1.0","end")
            assert text_after.index("gblur") < text_after.index("v360")
            rep.append("moving an effect up reordered the filter chain")

            # Pick the audio first -- the estimate needs a duration to
            # work from, and says so rather than inventing one.
            by_text(win, ttk.Button, "Choose...")[0].invoke()
            self.update()

            # the estimate reacts to the preset
            preset = [c for c in walk(win) if isinstance(c, ttk.Combobox)
                     and "ultrafast" in c.cget("values")][0]
            est = [w for w in walk(win) if isinstance(w, ttk.Label)
                  and ("About" in str(w.cget("text"))
                       or "estimate" in str(w.cget("text")))][0]
            preset.set("medium"); self.update()
            slow_text = est.cget("text")
            rep.append(f"estimate at medium: {slow_text[:90]}")
            assert "ultrafast" in slow_text, slow_text
            preset.set("ultrafast"); self.update()
            rep.append(f"estimate at ultrafast: {est.cget('text')[:70]}")

            # the background picker is wired to the command
            bg = [c for c in walk(win) if isinstance(c, ttk.Combobox)
                 and "Solid green (key it out)" in c.cget("values")][0]
            before = cmd.get("1.0", "end")
            assert "color=c=" not in before
            bg.set("Solid green (key it out)")
            bg.event_generate("<<ComboboxSelected>>")
            self.update()
            after_bg = cmd.get("1.0", "end")
            rep.append(f"choosing a solid green background added: "
                      f"{'color=c=0x00FF00' in after_bg}")
            assert "color=c=0x00FF00" in after_bg and "-shortest" in after_bg
            bg.set("Black (plain)")
            bg.event_generate("<<ComboboxSelected>>")
            self.update()
            assert "color=c=" not in cmd.get("1.0", "end")
            rep.append("switching back to plain removed the background "
                      "from the command")
            bg.set("Solid green (key it out)")
            bg.event_generate("<<ComboboxSelected>>")
            self.update()

            # a real render through the built command -- this spec now
            # stacks ring+blur+background, so it needs longer than the
            # earlier plain-waveform runs
            by_text(win, ttk.Button, "Preview 5 seconds")[0].invoke()
            self.after(15000, lambda: step3(win))
        except Exception:
            rep.append("STEP2 ERROR\n"+traceback.format_exc()); self.destroy()

    def step3(win):
        try:
            all_labels = [(str(w.cget("text"))[:100]) for w in walk(win)
                          if isinstance(w, ttk.Label) and str(w.cget("text")).strip()]
            rep.append("all label texts at step3:\n  " + "\n  ".join(all_labels))
            st = [w for w in walk(win) if isinstance(w, ttk.Label)
                 and str(w.cget("text")).startswith(("Done:", "ffmpeg"))]
            rep.append(f"render status: {st[0].cget('text')[:90] if st else '(none)'}")
            assert st and st[0].cget("text").startswith("Done:")
            import glob
            made = glob.glob(os.path.join(APP, "narrator_output",
                                          "audiogram_preview*"))
            made += glob.glob("audiogram_preview*")
            rep.append(f"file produced: {bool(made)}")
        except Exception:
            rep.append("STEP3 ERROR\n"+traceback.format_exc())
        self.destroy()
    self.after(900, go); orig(self, *a)
tk.Tk.mainloop = fake
from narrator.ui import launch
try: launch()
except Exception: rep.append("LAUNCH ERROR\n"+traceback.format_exc())
print("\n".join(rep))
