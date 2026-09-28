import os, sys, traceback, shutil, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
import tkinter as tk
from tkinter import ttk
from narrator import pipeline, config
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
            tools.invoke(real["Audiogram layout..."])
            self.after(1500, step2)
        except Exception:
            rep.append("STEP1 ERROR\n"+traceback.format_exc()); self.destroy()

    def step2():
        try:
            win = [w for w in walk(self) if isinstance(w, tk.Toplevel)][-1]
            checks = {str(c.cget("text")): c for c in walk(win)
                      if isinstance(c, ttk.Checkbutton)}
            for label in ("Bars", "Line", "Fill"):
                assert label in checks, list(checks)
            rep.append(f"layer toggles present: {[l for l in ('Bars','Line','Fill')]}")

            # the command box exists and shows a real ffmpeg command
            texts = [w for w in walk(win) if w.winfo_class() == "Text"]
            cmd = [t for t in texts if "ffmpeg" in t.get("1.0", "end")]
            assert cmd, "no ffmpeg command shown"
            shown = cmd[0].get("1.0", "end").strip()
            rep.append(f"command shown: {shown[:100]}...")
            assert "showwaves" in shown and "-filter_complex" in shown

            # switching to polar must change the command (fisheye appears)
            geom = [c for c in walk(win) if isinstance(c, ttk.Combobox)
                   and list(c.cget("values")) == ["linear", "polar"]][0]
            geom.set("polar"); self.update()
            after = cmd[0].get("1.0", "end")
            rep.append(f"polar command includes fisheye: "
                      f"{'v360' in after}")
            assert "v360" in after, after[:200]

            # a custom filter graph replaces it entirely
            entries = [w for w in walk(win) if isinstance(w, ttk.Entry)]
            fvar = None
            for e in entries:
                e.insert(0, "")
            # find the entry bound to the filter override by typing and
            # watching the command change
            for e in entries:
                before = cmd[0].get("1.0", "end")
                e.insert(0, "[0:a]showwaves=s=99x99[v]")
                self.update()
                if "99x99" in cmd[0].get("1.0", "end"):
                    fvar = e
                    break
                e.delete(0, "end"); self.update()
            assert fvar is not None, "no entry drives the filter override"
            rep.append("a custom filter graph replaces the built one in the "
                      "shown command")
            fvar.delete(0, "end"); self.update()
            assert "showwaves=s=99x99" not in cmd[0].get("1.0", "end")
            rep.append("clearing it restores the built command")

            # the motion preview button and its explanation
            assert by_text(win, ttk.Button, "Preview motion")
            why = [w for w in walk(win) if isinstance(w, ttk.Label)
                  and "Will use the" in str(w.cget("text"))]
            assert why, "no explanation of which renderer will be used"
            rep.append(f"renderer note: {why[0].cget('text')}")

            # turning on Fill must change that note to the frame renderer
            checks["Fill"].invoke(); self.update()
            note = [w for w in walk(win) if isinstance(w, ttk.Label)
                   and "Will use the" in str(w.cget("text"))][0]
            rep.append(f"after enabling Fill: {note.cget('text')}")
            assert "frame renderer" in note.cget("text")

            # the estimate updates with resolution
            est = [w for w in walk(win) if isinstance(w, ttk.Label)
                  and ("estimate" in str(w.cget("text"))
                       or "to render" in str(w.cget("text")))]
            assert est, "no render estimate shown"
            rep.append(f"estimate: {est[0].cget('text')[:80]}")
            win.destroy()
        except Exception:
            rep.append("STEP2 ERROR\n"+traceback.format_exc())
        self.destroy()
    self.after(900, go); orig(self, *a)
tk.Tk.mainloop = fake
from narrator.ui import launch
try: launch()
except Exception: rep.append("LAUNCH ERROR\n"+traceback.format_exc())
print("\n".join(rep))
