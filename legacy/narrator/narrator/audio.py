"""All ffmpeg work: format conversion, joining, chunk polishing,
the editing WAV export, subtitle building, and video export.
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

from .config import _no_window, have_ffmpeg, unique_path
from .subtitles import build_chunk_srt, shift_srt


# ---------------------------------------------------------------------------
# Output format, chunk polishing, and video export
# ---------------------------------------------------------------------------

# Each format: file extension, whether it's lossy, the ffmpeg codec, and the
# quality control the compression slider drives for that format. Lossy
# formats map the slider to a bitrate table; FLAC maps it to its own
# lossless compression_level (smaller file, same audio, slower to encode);
# WAV has no compression concept at all -- it's raw samples -- so the slider
# is disabled for it in the UI rather than pretending it does something.
AUDIO_FORMATS = {
    "MP3 (most compatible)": {
        "ext": "mp3", "lossy": True, "codec": "libmp3lame",
        # MP3 only supports a fixed table of bitrates (32/40/48/56/64/80/96/
        # 112/128/160/192/224/256/320); anything else gets silently rounded
        # by the encoder to whichever of those is nearest, so every value
        # here must be one of them or the slider position and the actual
        # output would quietly disagree.
        "bitrates": [64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 320],
    },
    "M4A / AAC (smaller, still widely supported)": {
        "ext": "m4a", "lossy": True, "codec": "aac",
        # ffmpeg's built-in AAC encoder silently plateaus around 195k on
        # mono audio no matter how much higher you ask -- confirmed by
        # testing every step from 48k to 320k directly. Narration is always
        # mono, so this table stops at 192k rather than offering values
        # like 256k that look meaningful on the slider but produce
        # identical output to 192k in practice.
        "bitrates": [48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 192],
    },
    "WAV (uncompressed)": {
        "ext": "wav", "lossy": False, "codec": "pcm",
    },
    "FLAC (lossless, compressed)": {
        "ext": "flac", "lossy": False, "codec": "flac",
        # ffmpeg -compression_level 0-8 for flac. Higher = smaller file, same
        # audio, slower encode -- unlike the lossy table, this never changes
        # what you hear, only file size and encode time.
        "compression_levels": [0, 1, 2, 3, 4, 5, 6, 7, 8, 8, 8],
    },
}

DEFAULT_FORMAT = "MP3 (most compatible)"

SAMPLE_RATES = [16000, 22050, 24000, 44100, 48000]
BIT_DEPTHS = [16, 24]


def slider_index(pct):
    """0-100 in steps of 10 -> index 0-10 into the tables above.

    Uses round-half-up rather than Python's default round-half-to-even, so
    45 snaps to 50 the way a person expects, not down to 40.
    """
    import math
    return max(0, min(10, math.floor(pct / 10 + 0.5)))


def join_intro_outro(audio_path, intro, outro, crossfade, log):
    """Put an intro before and/or an outro after the finished narration,
    crossfading each join so nothing starts or stops abruptly.

    Returns how many seconds were prepended -- NOT just success/failure,
    because everything timed against the narration (subtitles, chapter
    marks, the segment manifest behind sentence-level fixes) has to move
    later by exactly that much or it all runs early. Returns 0.0 when
    there is nothing to add, or when the join fails: a failed join leaves
    the narration untouched, so no offset applies.
    """
    have_intro = bool(intro) and os.path.isfile(intro)
    have_outro = bool(outro) and os.path.isfile(outro)
    if not (have_intro or have_outro):
        return 0.0
    if not have_ffmpeg():
        log("  intro/outro skipped: ffmpeg isn't available.")
        return 0.0

    crossfade = max(0.0, float(crossfade or 0.0))
    parts = ([intro] if have_intro else []) + [audio_path] + \
            ([outro] if have_outro else [])

    # A crossfade can't be longer than the shortest thing it joins.
    shortest = min((duration_of(p) or 0.0) for p in parts)
    if crossfade > 0 and shortest <= crossfade:
        crossfade = max(0.0, shortest / 2)

    ext = os.path.splitext(audio_path)[1] or ".mp3"
    tmp = os.path.splitext(audio_path)[0] + "__joined" + ext
    cmd = ["ffmpeg", "-y"]
    for part in parts:
        cmd += ["-i", part]
    if crossfade > 0:
        steps, prev = [], "[0:a]"
        for i in range(1, len(parts)):
            label = "[out]" if i == len(parts) - 1 else f"[a{i}]"
            steps.append(f"{prev}[{i}:a]acrossfade=d={crossfade:g}"
                        f":c1=tri:c2=tri{label}")
            prev = label
        cmd += ["-filter_complex", ";".join(steps), "-map", "[out]"]
    else:
        streams = "".join(f"[{i}:a]" for i in range(len(parts)))
        cmd += ["-filter_complex",
                f"{streams}concat=n={len(parts)}:v=0:a=1[out]",
                "-map", "[out]"]
    cmd.append(tmp)

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=_no_window())
    if proc.returncode != 0 or not os.path.exists(tmp):
        log("  intro/outro couldn't be added (the narration itself is "
           "unaffected):\n    " + proc.stderr.strip()[-300:])
        return 0.0

    intro_seconds = 0.0
    if have_intro:
        # The crossfade overlaps the two, so the narration starts earlier
        # than the intro's full length.
        intro_seconds = max(0.0, (duration_of(intro) or 0.0) - crossfade)
    os.replace(tmp, audio_path)
    bits = []
    if have_intro:
        bits.append("intro")
    if have_outro:
        bits.append("outro")
    log(f"  added {' and '.join(bits)}"
       + (f" ({crossfade:g}s crossfade)" if crossfade else ""))
    return intro_seconds


def finalize_render(result, cfg, folder, stem, log, existing_path=None):
    """Turns one engine's raw result (master audio + cached chunks) into the
    files the person actually sees: format-converted audio, an SRT if
    requested, kept-and-polished chunk files if requested, and a video if
    requested. Every engine's run_* function is deliberately ignorant of all
    of this -- output folder, filename, format, subtitles, chunks, video are
    all decided here, once, regardless of which engine produced the audio.

    existing_path, when given, is written to directly rather than through
    unique_path() -- used when fixing one chunk of an already-published take,
    where the point is to correct the existing file in place, not produce a
    new numbered variant beside it.

    Returns the final audio path, or None if the format conversion itself
    failed (generation having already failed returns None before this is
    ever called).
    """
    if result is None:
        return None

    fmt_key = cfg.get("format", DEFAULT_FORMAT)
    spec = AUDIO_FORMATS[fmt_key]
    quality = cfg.get("quality_pct", 100)
    sample_rate = cfg.get("sample_rate", 44100)
    bit_depth = cfg.get("bit_depth", 16)

    out_path = existing_path or unique_path(
        os.path.join(folder, stem + "." + spec["ext"]))
    log(f"Converting to {spec['ext'].upper()}...")
    if not transcode_audio(result["master"], out_path, fmt_key, quality,
                           sample_rate, bit_depth, log):
        return None

    # Prepending an intro moves everything that follows it later. The
    # offset is recorded on `result` so the manifest (and therefore
    # chapter marks and sentence-level fixes) can account for it, and the
    # SRT written below is timed with it already applied.
    intro_offset = join_intro_outro(out_path, cfg.get("intro_audio"),
                                    cfg.get("outro_audio"),
                                    cfg.get("intro_crossfade", 0.0), log)
    result["intro_offset"] = intro_offset

    srt_path = None
    if cfg.get("subtitles"):
        srt_path = os.path.splitext(out_path)[0] + ".srt"
        if result.get("native_srt") and os.path.exists(result["native_srt"]):
            shutil.copy2(result["native_srt"], srt_path)
            shift_srt(srt_path, intro_offset)
        elif result.get("chunk_texts"):
            build_chunk_srt(result["chunk_texts"], result["chunk_durations"],
                           srt_path, gap_seconds=result.get("chunk_gap", 0.0),
                           offset=intro_offset)
        else:
            srt_path = None
        if srt_path:
            log(f"  wrote subtitles: {os.path.basename(srt_path)}")

    if cfg.get("keep_chunks") and result.get("chunk_paths"):
        chunk_dir = os.path.join(folder, stem + "_chunks")
        os.makedirs(chunk_dir, exist_ok=True)
        log(f"  saving {len(result['chunk_paths'])} chunk file(s) to "
            f"{os.path.basename(chunk_dir)}/")
        for i, src in enumerate(result["chunk_paths"], 1):
            polished = os.path.join(chunk_dir, f"_polish_{i:04d}.wav")
            final_chunk = os.path.join(chunk_dir, f"{i:04d}.{spec['ext']}")
            if polish_chunk(src, polished):
                transcode_audio(polished, final_chunk, fmt_key, quality,
                               sample_rate, bit_depth, log)
                try:
                    os.remove(polished)
                except OSError:
                    pass
            else:
                # Fading failed for some reason; still hand back a listenable
                # file rather than silently dropping this chunk.
                transcode_audio(src, final_chunk, fmt_key, quality,
                               sample_rate, bit_depth, log)

    if cfg.get("editing_wav"):
        rate = cfg.get("editing_wav_rate", 48000)
        wav_path = os.path.splitext(out_path)[0] + f"_{rate // 1000}k.wav"
        # Deliberately converted from the engine's own master, NOT from
        # out_path: out_path may already be lossy (MP3/M4A), and going
        # lossy -> WAV would bake those artefacts into a file whose whole
        # point is being clean enough to edit against.
        if export_editing_wav(result["master"], wav_path, rate,
                              cfg.get("editing_wav_channels", 1),
                              log=log):
            log(f"  wrote editing WAV: {os.path.basename(wav_path)}")

    if cfg.get("make_video") and cfg.get("video_image"):
        video_path = os.path.splitext(out_path)[0] + ".mp4"
        log("Building video (this can take a little while)...")
        if build_video(out_path, cfg["video_image"], video_path,
                       srt_path=srt_path, log=log):
            log(f"  wrote video: {os.path.basename(video_path)}")

    return out_path


def transcode_audio(src_path, dst_path, fmt_key, quality_pct,
                    sample_rate, bit_depth, log):
    """Convert `src_path` (whatever the engine produced) to the user's chosen
    final format, bitrate/compression, and sample rate, in one ffmpeg call.
    Runs for every engine's output, including formats that already match --
    cheap, and it guarantees sample rate and quality are always applied
    consistently regardless of what the source engine natively produced.
    """
    spec = AUDIO_FORMATS[fmt_key]
    idx = slider_index(quality_pct)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
          "-ar", str(sample_rate)]

    if spec["ext"] == "wav":
        cmd += ["-c:a", f"pcm_s{bit_depth}le"]
    elif spec["ext"] == "flac":
        cmd += ["-c:a", "flac", "-sample_fmt",
               "s16" if bit_depth == 16 else "s32",
               "-compression_level", str(spec["compression_levels"][idx])]
    elif spec["ext"] == "m4a":
        cmd += ["-c:a", "aac", "-b:a", f"{spec['bitrates'][idx]}k"]
    else:  # mp3
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{spec['bitrates'][idx]}k"]

    cmd.append(dst_path)
    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=_no_window())
    if result.returncode != 0:
        log(f"  ! format conversion failed: {result.stderr.strip()[:300]}")
        return False
    return True


def convert_audio(src_path, dst_path, fmt_key, quality_pct=70,
                  sample_rate=48000, bit_depth=16, channels=None,
                  log=print):
    """Standalone conversion, reusing the same transcode path a render
    uses so the two can never diverge. `channels` of None keeps whatever
    the source has."""
    if not transcode_audio(src_path, dst_path, fmt_key, quality_pct,
                           sample_rate, bit_depth, log):
        return None
    if channels:
        # A second pass: -c:a copy cannot change channel count, and
        # transcode_audio has no channel argument of its own.
        tmp = dst_path + ".ch" + os.path.splitext(dst_path)[1]
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", dst_path,
              "-ac", str(channels), tmp]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=_no_window())
        if r.returncode == 0 and os.path.exists(tmp):
            os.replace(tmp, dst_path)
        else:
            log("  ! couldn't change the channel count; left as-is.")
    return dst_path


def measured_bitrate(path):
    """Actual bytes per second of an encoded file. Used instead of the
    requested bitrate because VBR, container overhead and the encoder's
    own decisions all mean the requested number is not what lands on
    disk -- and splitting to a size limit depends on the real figure."""
    size = os.path.getsize(path) if os.path.exists(path) else 0
    dur = duration_of(path) or 0
    return (size / dur) if dur > 0 else 0


def split_audio(src_path, out_dir, stem, ext, seconds=None, max_bytes=None,
                log=print, max_passes=4):
    """Split an audio file into numbered parts, either every `seconds` or
    kept under `max_bytes` each.

    Only duration is directly controllable, so a size limit is met by
    estimating the duration that fits from the file's REAL bytes-per-second
    and then verifying: if any part still comes out over, the estimate is
    tightened and the split re-run. Bounded by `max_passes` so a pathological
    file can't loop forever -- it reports what it achieved instead of
    pretending it succeeded.
    """
    os.makedirs(out_dir, exist_ok=True)
    total = duration_of(src_path) or 0
    if total <= 0:
        raise RuntimeError("Couldn't read the length of that audio file.")

    if seconds:
        target = float(seconds)
    elif max_bytes:
        rate = measured_bitrate(src_path)
        if rate <= 0:
            raise RuntimeError("Couldn't measure the file's bitrate, so a "
                               "size limit can't be worked out.")
        target = max(1.0, max_bytes / rate * 0.97)   # 3% headroom
        log(f"  {rate / 1024:.0f} KB/s measured -> about "
           f"{target:.0f}s per part to stay under "
           f"{max_bytes / 1e6:.1f} MB")
    else:
        raise ValueError("Give either a duration or a maximum size.")

    for attempt in range(1, max_passes + 1):
        for old in list(_existing_parts(out_dir, stem, ext)):
            os.remove(old)
        pattern = os.path.join(out_dir, f"{stem}_part%03d.{ext}")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
              "-f", "segment", "-segment_time", f"{target:.3f}",
              "-reset_timestamps", "1", "-c", "copy", pattern]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=_no_window())
        if r.returncode != 0:
            # Stream copy can't split some formats on arbitrary boundaries;
            # re-encoding always can.
            cmd = [c for c in cmd if c not in ("-c", "copy")]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=_no_window())
            if r.returncode != 0:
                raise RuntimeError("Splitting failed:\n"
                                   + r.stderr.strip()[-300:])
        parts = _existing_parts(out_dir, stem, ext)
        if not parts:
            raise RuntimeError("Splitting produced no files.")
        if not max_bytes:
            break
        worst = max(os.path.getsize(p) for p in parts)
        if worst <= max_bytes:
            break
        if attempt == max_passes:
            log(f"  ! after {max_passes} attempts the largest part is "
               f"{worst / 1e6:.1f} MB, still over the "
               f"{max_bytes / 1e6:.1f} MB limit. Files are usable; try a "
               "lower bitrate or a smaller limit.")
            break
        target *= (max_bytes / worst) * 0.95
        log(f"  largest part was {worst / 1e6:.1f} MB, retrying at "
           f"{target:.0f}s per part")

    # ffmpeg's segment muxer can leave a final fragment of a few hundred
    # bytes containing no real audio -- it has no readable duration and
    # some players refuse it outright. Dropping it loses nothing (the
    # remaining parts still add up to the original length) and is much
    # better than handing over a file that won't open.
    parts, junk = [], []
    for path in _existing_parts(out_dir, stem, ext):
        dur = duration_of(path)
        (junk if (dur is None or dur < MIN_PART_SECONDS)
         else parts).append(path)
    for path in junk:
        try:
            os.remove(path)
        except OSError:
            pass
    if junk:
        log(f"  discarded {len(junk)} empty fragment(s) left by the split")
    if not parts:
        raise RuntimeError("Splitting produced no usable audio.")
    log(f"  {len(parts)} part(s), largest "
       f"{max(os.path.getsize(p) for p in parts) / 1e6:.1f} MB")
    return parts


# Below this, a 'part' is a container artefact rather than audio.
MIN_PART_SECONDS = 0.25


def _existing_parts(out_dir, stem, ext):
    if not os.path.isdir(out_dir):
        return []
    return sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir)
        if f.startswith(f"{stem}_part") and f.endswith("." + ext))


EDITING_WAV_RATES = [44100, 48000]
EDITING_WAV_CHANNELS = {"Mono": 1, "Stereo": 2}


def export_editing_wav(src_path, dst_path, sample_rate=48000, channels=1,
                       bit_depth=16, log=print):
    """Write an uncompressed PCM WAV sized for a video editor's timeline.

    This exists to delete a manual step: importing narration into Audacity
    purely to re-export it as WAV, because DaVinci Resolve (especially the
    free version, which ships a limited audio decoder set) handles
    compressed m4a/AAC unreliably -- silent tracks, missing waveforms, and
    waveform-vs-playback desync are all common. Uncompressed PCM always
    decodes, and matching the timeline's sample rate avoids on-the-fly
    resampling, which is the usual cause of the desync.

    48 kHz is the default because that is Resolve's own default timeline
    rate; 44.1 kHz is offered for projects that are already 44.1 throughout.
    Mono is the default since narration is single-voice -- half the file
    size, and no editor requires stereo to draw a waveform.
    """
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
          "-ar", str(sample_rate), "-ac", str(channels),
          "-c:a", f"pcm_s{bit_depth}le", dst_path]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=_no_window())
    if result.returncode != 0:
        log(f"  ! WAV export failed: {result.stderr.strip()[:300]}")
        return None
    return dst_path


def polish_chunk(src_path, dst_path, fade_ms=40):
    """A chunk that sounds seamless spliced into a longer file can click at
    the very start/end when played alone -- the join hides a hard edge that
    isolation reveals. A very short fade (default 40ms, well under
    perceptible as a fade, long enough to kill the click) fixes this without
    audibly changing the take."""
    fade_s = fade_ms / 1000.0
    dur = duration_of(src_path) or 0
    out_dur = max(0.05, dur - fade_s) if dur else None
    filt = f"afade=t=in:d={fade_s}"
    if out_dur:
        filt += f",afade=t=out:st={out_dur}:d={fade_s}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src_path,
          "-af", filt, dst_path]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=_no_window())
    return result.returncode == 0


def build_video(audio_path, image_path, out_path, srt_path=None,
                width=1920, height=1080, log=print):
    """Still image + audio, with an optional animated waveform and optional
    burned-in captions -- the same shape of output Descript's Audiogram
    feature or a standalone audiogram tool produces, built with ffmpeg alone.

    Layering, bottom to top: background image, scaled and padded to frame
    size; a waveform strip along the bottom third, drawn directly from the
    audio by ffmpeg's own showwaves filter (no separate visualization tool
    needed); captions on top if an SRT was provided, rendered by libass via
    ffmpeg's subtitles filter, which is what actually burns them into the
    pixels rather than leaving them as a togglable sidecar track.
    """
    wave_h = height // 5
    filter_parts = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black[bg]",
        # showwaves draws a white line on a black-filled background, not the
        # other way round -- confirmed by inspecting raw output pixels, since
        # this is easy to get backwards and silently produce an invisible
        # waveform (keying the wrong colour leaves the black background
        # opaque and removes the line instead). draw=full gives solid pixels
        # rather than showwaves' default antialiased/thin rendering, which
        # keys out cleanly; colorkey then removes exactly that black fill.
        f"[1:a]showwaves=s={width}x{wave_h}:mode=cline:colors=white:"
        f"draw=full,format=rgba,colorkey=0x000000:0.10:0.05[wave]",
        # shortest=1 HERE, on overlay itself, is what actually bounds this
        # to the audio's length -- not the -shortest OUTPUT flag below,
        # which only works when the shorter stream is separately mapped
        # into the output. This function happens to map "1:a" too, which
        # would make the output flag sufficient on its own here -- but
        # that makes the correctness of the whole function depend on
        # audio always being mapped, silently, with no error if it ever
        # isn't. Confirmed directly: the identical graph withOUT this
        # overlay-level flag, exported video-only (as a future
        # video-without-audio option might), ran a 3-second source out to
        # nearly 4 minutes before being killed by a timeout. See
        # ffgram.py's `_build_graph_with_background` for the full
        # writeup and the case that surfaced this.
        f"[bg][wave]overlay=0:{height - wave_h}:shortest=1[merged]",
    ]
    last = "[merged]"
    if srt_path and os.path.exists(srt_path):
        escaped = srt_path.replace("\\", "/").replace(":", "\\:")
        filter_parts.append(
            f"{last}subtitles='{escaped}':force_style="
            f"'FontSize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
            f"BorderStyle=1,Outline=2,MarginV=40'[captioned]")
        last = "[captioned]"

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
          "-loop", "1", "-i", image_path, "-i", audio_path,
          "-filter_complex", ";".join(filter_parts),
          "-map", last, "-map", "1:a",
          "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
          "-shortest", "-movflags", "+faststart", out_path]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            creationflags=_no_window())
    if result.returncode != 0:
        log(f"  ! video export failed: {result.stderr.strip()[:400]}")
        return None
    return out_path




def join_audio(parts, out, log):
    if have_ffmpeg():
        listfile = out + ".list"
        with open(listfile, "w", encoding="utf-8") as fh:
            for p in parts:
                escaped = os.path.abspath(p).replace("'", "'\\''")
                fh.write(f"file '{escaped}'\n")
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", listfile,
               "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
               "-c:a", "libmp3lame", "-b:a", "128k", out]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=_no_window())
        os.remove(listfile)
        if result.returncode == 0:
            log("  joined and loudness-normalised with ffmpeg")
            return
        log(f"  ffmpeg join failed, falling back: {result.stderr[:150]}")

    with open(out, "wb") as dest:
        for p in parts:
            with open(p, "rb") as src:
                shutil.copyfileobj(src, dest)
    log("  joined without ffmpeg (install ffmpeg for cleaner joins "
        "and even volume)")


def envelope(path, buckets=900, log=None):
    """A peak-per-bucket outline of a file's loudness, for drawing a
    waveform silhouette. Values are 0..1 relative to the file's own peak.

    Decodes through ffmpeg to raw mono PCM rather than reading the file
    directly: the finished output is usually mp3 or m4a, which soundfile
    cannot open, and the timeline has to draw whatever the person actually
    produced -- not only the intermediate WAVs.
    """
    import numpy as np
    if not have_ffmpeg():
        return []
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le",
          "-acodec", "pcm_s16le", "-ac", "1", "-ar", "8000", "-"]
    proc = subprocess.run(cmd, capture_output=True,
                          creationflags=_no_window())
    if proc.returncode != 0 or not proc.stdout:
        if log:
            log("  couldn't read the waveform: "
               + proc.stderr.decode("utf-8", "replace").strip()[-200:])
        return []
    samples = np.frombuffer(proc.stdout, dtype="<i2").astype("float32")
    if not len(samples):
        return []
    buckets = max(1, int(buckets))
    # Trim to a whole number of buckets so reshape is exact; the remainder
    # is at most one bucket's worth and would not be visible anyway.
    per = max(1, len(samples) // buckets)
    usable = per * buckets
    peaks = np.abs(samples[:usable].reshape(buckets, per)).max(axis=1)
    top = float(peaks.max()) or 1.0
    return (peaks / top).tolist()


def decode_to_array(path, rate=24000):
    """Any audio file -> (mono float32 samples, rate), via ffmpeg.

    Uniform across formats on purpose: dialogue pieces can come from
    engines that write WAV (Kokoro, Qwen3) or MP3 (edge-tts), and the
    joiner must not care which.
    """
    import numpy as np
    if not have_ffmpeg():
        return np.zeros(0, dtype="float32"), rate
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le",
         "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(rate), "-"],
        capture_output=True, creationflags=_no_window())
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros(0, dtype="float32"), rate
    return np.frombuffer(proc.stdout, dtype="<f4").copy(), rate


def join_pieces(paths, out_path, gap_seconds=None, rate=24000, log=print):
    """Join audio pieces in the given order with a controlled pause.

    Shares the pacing rules the narration path uses: each piece is trimmed
    of its own leading and trailing silence first, so the gap between
    turns is the gap asked for rather than that plus however long each
    speaker trailed off. Returns (master_path, durations, real_gap).
    """
    import numpy as np
    import soundfile as sf
    from .engines import TRIM_KEEP, chunk_gap_setting, trim_silence

    if gap_seconds is None:
        gap_seconds = chunk_gap_setting()
    inserted = max(0.0, gap_seconds - 2 * TRIM_KEEP)
    arrays, durations = [], []
    for i, path in enumerate(paths):
        data, rate = decode_to_array(path, rate)
        data = trim_silence(data, rate)
        durations.append(len(data) / rate if rate else 0.0)
        arrays.append(data)
        if i < len(paths) - 1:
            arrays.append(np.zeros(int(rate * inserted), dtype="float32"))
    master = np.concatenate(arrays) if arrays else np.zeros(1, dtype="float32")
    sf.write(out_path, master, rate)
    return out_path, durations, inserted


def extract_span(src_path, start, end, out_path, log=print):
    """Copy [start, end] seconds of any audio file to its own file, for
    listening to one part in isolation. Goes through ffmpeg so it works on
    compressed output, not only WAV."""
    duration = max(0.05, float(end) - float(start))
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}",
          "-t", f"{duration:.3f}", "-i", src_path, out_path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=_no_window())
    if r.returncode != 0:
        log("  couldn't extract that span: " + r.stderr.strip()[-200:])
        return None
    return out_path


def duration_of(path):
    if path.endswith(".wav"):
        try:
            with wave.open(path, "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            return None
    if have_ffmpeg():
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, creationflags=_no_window())
        try:
            return float(r.stdout.strip())
        except ValueError:
            return None
    return None
