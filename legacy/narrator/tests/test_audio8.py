import os, sys, shutil, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "stubs"), os.path.dirname(HERE)]
os.environ["STUB_LOG"] = "/tmp/a8.jsonl"
APP = os.path.dirname(HERE)
shutil.rmtree(os.path.join(APP, "narrator_data"), ignore_errors=True)
if os.path.exists("/tmp/a8.jsonl"): os.remove("/tmp/a8.jsonl")
D = "/tmp/a8test"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)

from narrator import audio8_engine as A8
from narrator import engines, pipeline, config
import transformers as stub_tf

log_lines = []
def log(m): log_lines.append(str(m))

# --- registered correctly ---
assert "Audio8-TTS (offline, voice cloning, Preview)" in pipeline.ENGINES
spec = pipeline.ENGINES["Audio8-TTS (offline, voice cloning, Preview)"]
assert spec["key"] == "audio8" and spec["voices"] == []
assert "Preview" in spec["hint"] and "not a default" in spec["hint"].lower()
print("R1 ok: registered in ENGINES, cloning-only (no fixed voice list), "
     "hint says plainly this isn't a default narrator")

comp = [c for c in __import__("narrator.components",
                              fromlist=["COMPONENTS"]).COMPONENTS.values()
        if c.get("engine_key") == "audio8"][0]
assert "0.6B" in comp["licence"]
print(f"R2 ok: component entry flags the licence distinction: "
     f"{comp['licence']!r}")

# --- sentence chunking respects the model's 150-char cap ---
short = "A short sentence. Another one here."
pieces = A8._audio8_chunks(short)
assert pieces == ["A short sentence.", "Another one here."], pieces
print(f"C1 ok: normal sentences pass through unsplit: {pieces}")

# A single sentence, no internal punctuation to split on, genuinely over
# the cap -- three repeats of the phrase joined without periods, so
# split_sentences() treats it as one sentence.
long_sentence = "This is a very long sentence that keeps going and going and does not stop for quite a long while " * 2
pieces2 = A8._audio8_chunks(long_sentence)
assert all(len(p) <= A8.AUDIO8_MAX_CHARS for p in pieces2), \
    [len(p) for p in pieces2]
assert len(pieces2) > 1
rejoined = " ".join(pieces2)
assert rejoined.split() == long_sentence.split()
print(f"C2 ok: an oversized sentence splits into {len(pieces2)} pieces, "
     f"each under {A8.AUDIO8_MAX_CHARS} chars, with no words lost")

# a pathological no-space run still terminates and respects the cap
wall = "x" * 400
pieces3 = A8._audio8_chunks(wall)
assert all(len(p) <= A8.AUDIO8_MAX_CHARS for p in pieces3)
assert "".join(pieces3) == wall
print(f"C3 ok: text with no spaces at all still splits safely "
     f"({len(pieces3)} pieces)")

# --- duration plausibility screening ---
ok, reason = A8._plausible_duration("A normal sentence here.", 1.5)
assert ok, reason
ok2, reason2 = A8._plausible_duration("A" * 100, 0.5)
assert not ok2 and "too short" in reason2
ok3, reason3 = A8._plausible_duration("Hi.", 30.0)
assert not ok3 and "too long" in reason3
ok4, reason4 = A8._plausible_duration("Anything.", 0.0)
assert not ok4 and "no audio" in reason4
print(f"P1 ok: plausibility screening -- normal passes, too-short fails "
     f"({reason2!r}), too-long fails ({reason3!r}), silent fails")

# --- a saved voice, built the shared way ---
import subprocess
ref = f"{D}/ref.wav"
subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi",
                "-i","sine=frequency=200:duration=4","-ar","44100",ref],
               capture_output=True, check=True)
voice_dir = engines.clone_voice_from_recording(
    ref, "This is a sample of my voice speaking clearly.",
    "test narrator", log, engine_tag="audio8", min_seconds=3.0)
assert os.path.isfile(os.path.join(voice_dir, "voice.json"))
meta = json.load(open(os.path.join(voice_dir, "voice.json")))
assert meta["engine"] == "audio8" and meta["kind"] == "cloned"
print(f"V1 ok: a voice cloned via the shared function is tagged "
     f"engine={meta['engine']!r}, stored the same shape as a Qwen3 clone")

# it shows up in saved_voices() with its engine tag, so the UI can filter
voices = engines.saved_voices()
mine = [v for v in voices if v["folder"] == voice_dir][0]
assert mine["engine"] == "audio8"
qwen_like = [v for v in voices if v["engine"] == "qwen3"]
print(f"V2 ok: saved_voices() exposes engine={mine['engine']!r}, so an "
     "Audio8 voice is distinguishable from a Qwen3 one in the list")

# a too-short recording is refused with a reason naming the engine's own limit
try:
    engines.clone_voice_from_recording(
        ref, "text", "too short", log, engine_tag="audio8", min_seconds=10.0)
    raise SystemExit("should have refused")
except ValueError as e:
    assert "10" in str(e)
print("V3 ok: a too-short recording is refused, naming the actual "
     "minimum rather than a generic message")

# --- rendering: normal path ---
stub_tf.set_stub_mode("normal")
workdir = f"{D}/work1"; os.makedirs(workdir)
result = A8._run_audio8_local(
    ["Hello there, this is a test of the system."], voice_dir, 0, workdir,
    log)
assert len(result["chunk_paths"]) == 1
assert os.path.isfile(result["chunk_paths"][0])
import soundfile as sf
data, rate = sf.read(result["chunk_paths"][0])
assert len(data) / rate > 0.5
print(f"G1 ok: a normal render produces real audio "
     f"({len(data)/rate:.2f}s for the given text)")

# the processor really was called with the reference clip and transcript
calls = [json.loads(l) for l in open("/tmp/a8.jsonl") if l.strip()]
proc_calls = [c for c in calls if c.get("call") == "audio8_process"]
assert proc_calls and proc_calls[0]["ref_text_len"] > 0
print("G2 ok: the reference transcript was actually passed to the "
     "processor, not silently dropped")

# --- rendering: a piece that comes back too short triggers a retry ---
open("/tmp/a8.jsonl", "w").close()
stub_tf.set_stub_mode("recovers_on_retry")
workdir2 = f"{D}/work2"; os.makedirs(workdir2)
log_lines.clear()
result2 = A8._run_audio8_local(["A sentence that needs a retry to work."],
                               voice_dir, 0, workdir2, log)
assert any("retry" in l for l in log_lines), log_lines
data2, rate2 = sf.read(result2["chunk_paths"][0])
assert len(data2) / rate2 > 0.5
print(f"G3 ok: a piece that first comes back implausibly short is "
     f"retried and recovers, ending with {len(data2)/rate2:.2f}s of real "
     "audio rather than the bad first attempt")

# --- rendering: consistently bad output is kept (not silently dropped)
#     but the log says so plainly, after exhausting retries ---
stub_tf.set_stub_mode("too_short")
workdir3 = f"{D}/work3"; os.makedirs(workdir3)
log_lines.clear()
result3 = A8._run_audio8_local(["This will never come back right."],
                               voice_dir, 0, workdir3, log)
assert os.path.isfile(result3["chunk_paths"][0])
retries = [l for l in log_lines if "retry" in l]
gave_up = [l for l in log_lines if "kept the last attempt despite" in l]
# AUDIO8_MAX_RETRIES + 1 total attempts are made (the first try plus that
# many retries), so that many "retry N/M" lines are logged -- one per
# attempt, including the final one right before giving up.
assert len(retries) == A8.AUDIO8_MAX_RETRIES + 1, retries
assert gave_up, log_lines
print(f"G4 ok: output that never becomes plausible is attempted "
     f"{A8.AUDIO8_MAX_RETRIES + 1} times total, then kept with an "
     f"explicit 'gave up' note -- never an infinite loop, never a "
     "silent failure")
stub_tf.set_stub_mode("normal")

# --- caching: already-rendered parts are reused, not re-generated ---
open("/tmp/a8.jsonl", "w").close()
result4 = A8._run_audio8_local(
    ["Hello there, this is a test of the system."], voice_dir, 0, workdir,
    log)
calls2 = [json.loads(l) for l in open("/tmp/a8.jsonl") if l.strip()]
assert not [c for c in calls2 if c.get("call") == "audio8_generate"]
print("G5 ok: re-rendering the same chunk to the same workdir reuses the "
     "cached file rather than calling the model again")

# --- errors are refused with real reasons ---
try:
    A8._run_audio8_local(["text"], f"{D}/no-such-voice", 0,
                         f"{D}/work4", log)
    raise SystemExit("should have refused")
except RuntimeError as e:
    assert "cloned voice" in str(e)
print("E1 ok: a missing voice folder is refused with a clear reason")

no_transcript_dir = f"{D}/no_transcript_voice"
os.makedirs(no_transcript_dir)
json.dump({"description": "x", "kind": "cloned"},
          open(os.path.join(no_transcript_dir, "voice.json"), "w"))
shutil.copy(ref, os.path.join(no_transcript_dir, "reference.wav"))
try:
    A8._run_audio8_local(["text"], no_transcript_dir, 0, f"{D}/work5", log)
    raise SystemExit("should have refused")
except RuntimeError as e:
    assert "reference transcript" in str(e)
print("E2 ok: a voice missing its reference transcript is refused rather "
     "than crashing deep inside the model call")

print("\nALL AUDIO8 TESTS PASSED")
