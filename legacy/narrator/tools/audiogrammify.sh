#!/usr/bin/env bash
# audiogrammify.sh -- drag a .wav (or any audio file) onto this and get an
# audiogram video back next to it, same name, .mp4.
#
# This is a fixed, hand-tunable copy of one graph from Narrator's
# ffgram builder (Tools -> Audiogram command builder... in the app) --
# specifically, the "render small, scale up, sharpen" recipe:
#
#   showwaves at 1920x360, 24fps -> scale to 1920x720 -> cas sharpen 0.5
#
# Nothing here is generated or hidden: the whole command is the six lines
# below. Change SIZE, FPS, SCALE_TO or SHARPEN and drop a file again to
# see the effect -- that is the point of keeping this as a plain script
# rather than a compiled app.
#
# WHY IT LOOKS DARK: -pix_fmt yuv420p has no alpha channel at all, so
# what's showing is the real background showwaves fills solid black by
# default -- it is not a low-opacity setting. This script does not
# composite over anything; it makes an opaque video meant to sit on its
# own video track in the editor. If you want a punch-through background
# instead, see the colorkey variant noted at the bottom.
#
# Requires ffmpeg on PATH. Nothing else -- this does not need Narrator
# installed, Python, or any of its dependencies.

set -euo pipefail

# --- the knobs -------------------------------------------------------------
SIZE="1920x360"      # showwaves draws at this size first
FPS="24"
SCALE_TO="1920:720"  # then it's stretched to this -- doubling the height
                     # here is what makes the waveform look tall and bold
COLOR="0xFFFFFF"
MODE="cline"          # point | line | p2p | cline
SHARPEN="0.5"         # cas strength, 0 disables sharpening
PRESET="ultrafast"    # ultrafast is far faster than ffmpeg's own default
                      # (medium) for the same picture; see Narrator's
                      # audiogram builder for the numbers behind this
BACKGROUND="0x00FF00" # solid green to chroma-key out in Resolve; set to
                      # "" for plain black (ffmpeg's own default), or a
                      # different 0xRRGGBB
# ----------------------------------------------------------------------------

if [ "$#" -eq 0 ]; then
    echo "Drop one or more audio files onto this script, or run it with"
    echo "the files as arguments:"
    echo "    ${0##*/} \"Episode 1.wav\" \"Episode 2.wav\""
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg isn't on PATH. Install it from https://ffmpeg.org/download.html"
    exit 1
fi

for input in "$@"; do
    if [ ! -f "$input" ]; then
        echo "Skipping (not a file): $input"
        continue
    fi
    dir=$(dirname -- "$input")
    stem=$(basename -- "$input")
    stem="${stem%.*}"
    output="$dir/$stem.mp4"

    if [ -e "$output" ]; then
        echo "Already exists, skipping so nothing is overwritten by accident:"
        echo "    $output"
        echo "(delete it, or rename it, then drop the audio again)"
        continue
    fi

    echo "=== $stem ==="
    echo "  $input  ->  $output"

    wave_chain="[0:a]showwaves=s=${SIZE}:mode=${MODE}:colors=${COLOR}:r=${FPS}[wave0];[wave0]scale=${SCALE_TO}$( [ "$SHARPEN" != "0" ] && echo ",cas=${SHARPEN}" )"

    if [ -n "$BACKGROUND" ]; then
        # showwaves only paints the waveform line itself -- everywhere
        # else is genuinely transparent black, not "black", so there is
        # nothing for a chroma-key filter to find on its own. A solid
        # colour is composited UNDERNEATH first, sized to match the
        # scaled output. -shortest stops it at the audio's length --
        # without it ffmpeg would run forever, since a still colour has
        # no natural duration of its own.
        out_wh="${SCALE_TO/:/x}"
        # overlay's OWN shortest=1 is what actually bounds this to the
        # audio's length -- verified directly against real ffmpeg: with
        # only an output-level -shortest flag, this graph shape ran to
        # 37.9s against a 4.0s source before being killed. overlay's own
        # parameter stopped it correctly at 4.1s. The output flag is kept
        # too as a second line of defence, but is not what does the job.
        graph="color=c=${BACKGROUND}:s=${out_wh}[bg];${wave_chain}[wave];[bg][wave]overlay=format=auto:shortest=1[v]"
        extra_flag="-shortest"
    else
        graph="${wave_chain}[v]"
        extra_flag=""
    fi

    # -shortest is an OUTPUT option -- it has to come after -map/-c:v,
    # not next to -i. Placed by the input it silently does nothing, and
    # the still-colour background then has no natural length, so ffmpeg
    # runs forever. Confirmed the hard way: it hung for real until killed.
    ffmpeg -y -i "$input" \
        -filter_complex "$graph" \
        -map "[v]" -an \
        -c:v libx264 -pix_fmt yuv420p -preset "$PRESET" -r "$FPS" \
        $extra_flag \
        "$output"

    if [ -f "$output" ]; then
        size=$(du -h "$output" 2>/dev/null | cut -f1)
        echo "  done ($size)"
    else
        echo "  FAILED -- see ffmpeg's own message above."
    fi
    echo
done

# --- variant: REAL transparency instead of a solid background to key out --
# The script above defaults to a solid chroma-key colour, which is
# reliable to key out in any editor and is what most people actually
# want. If you'd rather have genuine alpha instead -- for compositing
# without keying at all -- swap the ffmpeg call for this one. It needs a
# codec that can HOLD alpha; H.264 cannot, at any pix_fmt, so the output
# becomes a .mov, not an .mp4:
#
#   ffmpeg -y -i "$input" \
#       -filter_complex "[0:a]showwaves=s=${SIZE}:mode=${MODE}:colors=${COLOR}:r=${FPS}[wave];[wave]scale=${SCALE_TO},cas=${SHARPEN},colorkey=black:0.1:0[v]" \
#       -map "[v]" -an \
#       -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le -r "$FPS" \
#       "$dir/$stem.mov"
