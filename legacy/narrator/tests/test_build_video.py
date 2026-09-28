import os, sys, shutil, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
from narrator import audio as A
D = "/tmp/bvtest"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
log = lambda m: None
wav = f"{D}/a.wav"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","sine=frequency=300:duration=3","-ar","48000",wav],
               capture_output=True, check=True)
img = f"{D}/bg.png"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","color=c=navy:s=640x360","-frames:v","1",img],
               capture_output=True, check=True)

def probe_duration(path):
    return float(subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","csv=p=0",path], capture_output=True, text=True).stdout)

# --- the real function, real ffmpeg, real timing ---
out = A.build_video(wav, img, f"{D}/out.mp4", log=log)
assert out and os.path.isfile(out)
dur = probe_duration(out)
assert 2.7 < dur < 3.3, dur
print(f"V1 ok: a still image + 3s audio produces a {dur:.2f}s video, "
     "bounded correctly")

# --- the mechanism this depends on, checked directly against ffmpeg,
#     not inferred from the Python code: overlay's own shortest=1 is
#     what actually bounds a loop=1 image against a real-length audio
#     stream. -shortest as a bare output flag only works when the
#     shorter stream is separately MAPPED into the output -- an input
#     merely being present is not enough, which is an easy thing to
#     break by accident later (e.g. a video-only export mode). ---
def run(graph, extra_map, timeout=12):
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", img,
          "-i", wav, "-filter_complex", graph, "-map", "[out]"]
    cmd += extra_map + ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if not extra_map:
        cmd.append("-an")
    cmd += ["-shortest", f"{D}/probe.mp4"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)
        return probe_duration(f"{D}/probe.mp4")
    except subprocess.TimeoutExpired:
        return None

safe = ("[0:v]scale=640:360[bg];[1:a]showwaves=s=640x72[wave];"
       "[bg][wave]overlay=0:0:shortest=1[out]")
d1 = run(safe, [])   # video only, -an -- the risky shape
assert d1 is not None and 2.7 < d1 < 3.3, d1
print(f"V2 ok: overlay's own shortest=1 bounds a video-only export "
     f"correctly ({d1:.2f}s) even with no audio mapped at all")

unsafe = ("[0:v]scale=640:360[bg];[1:a]showwaves=s=640x72[wave];"
         "[bg][wave]overlay=0:0[out]")   # no shortest=1 on overlay
d2 = run(unsafe, [], timeout=8)
assert d2 is None, (
    "REGRESSION CHECK ITSELF IS STALE: the unsafe graph (no overlay-level "
    "shortest) no longer hangs on video-only export -- if ffmpeg's "
    "behaviour changed, this assumption needs re-verifying, not deleting")
print("V3 ok: confirmed the failure mode still exists without the fix -- "
     "video-only export with a bare output -shortest and no overlay-level "
     "guard genuinely hangs, which is exactly why build_video carries the "
     "guard even though it currently always maps audio too")

d3 = run(safe, ["-map", "1:a", "-c:a", "aac"])   # audio mapped too
assert d3 is not None and 2.7 < d3 < 3.3, d3
print(f"V4 ok: with audio mapped as well (build_video's actual shape), "
     f"it is correctly bounded regardless ({d3:.2f}s)")

print("\nALL BUILD_VIDEO TESTS PASSED")
