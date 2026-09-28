"""What a render takes as settings, described once.

Until now this lived only as a dict literal in `ui.py`, assembled by
reading about twenty-five Tk variables. That made the settings *implicit*:
the only way to know what a render accepts, what a value may be, or what
happens when one is missing was to read the widget code. A second
interface would have had to rediscover all of it, and a cfg arriving from
a saved project or an API call had nowhere to be checked.

So the schema is the source of truth and the widgets are one way of
filling it in. `coerce()` takes anything dict-shaped -- from widgets, from
a saved project, from JSON -- and returns a clean cfg plus a list of
problems in plain language. Nothing here imports tkinter.

Values are validated, not merely defaulted: a bad sample rate or an
unknown format is reported rather than silently replaced, because a
render that quietly used settings you didn't choose is worse than one
that refuses.
"""

import os

# Each field: (default, kind, spec, description)
#   kind "text"   -- spec unused
#   kind "path"   -- spec is "file" | "dir" | "any"; "" means unset
#   kind "bool"
#   kind "int"    -- spec is (low, high)
#   kind "float"  -- spec is (low, high)
#   kind "choice" -- spec is a callable returning the allowed values, so
#                    engine and format lists stay in their own modules
#                    rather than being duplicated here
FIELDS = {
    "path": (None, "path", "file", "The document to narrate."),
    "root": (None, "path", "dir", "Where output is written."),
    "engine": (None, "choice", None, "Which narration engine."),
    "voice": ("", "text", None,
              "Voice id, or a description for engines that design one."),
    "take": (1, "int", (1, 99),
             "Which roll of a designed voice. Same description plus take "
             "gives the same narrator back."),
    "speed": (0, "int", (-50, 50), "Speech rate, as a percentage change."),
    "chunk_mode": ("parts", "choice", None,
                   "How the document is divided: parts, tokens or chars."),
    "chunk_count": (1, "int", (1, 500), "Number of parts, in parts mode."),
    "chunk_target": (500, "int", (1, 100000),
                     "Target size per part, in tokens or chars mode."),
    "chars_per_token": (None, "float", (0.05, 20.0),
                        "Measured characters per Kokoro token, if known."),
    "subtitles": (False, "bool", None, "Write an .srt beside the audio."),
    "filename": ("", "text", None, "Override the output filename stem."),
    "format": (None, "choice", None, "Output audio format."),
    "sample_rate": (48000, "choice", None, "Output sample rate in Hz."),
    "bit_depth": (16, "choice", None, "Bit depth for WAV and FLAC."),
    "quality_pct": (70.0, "float", (0.0, 100.0),
                    "Quality/compression, 0 to 100."),
    "use_subfolders": (False, "bool", None,
                       "Give each document its own output folder."),
    "keep_chunks": (False, "bool", None, "Keep the per-part audio files."),
    "make_video": (False, "bool", None, "Also render a video."),
    "editing_wav": (False, "bool", None,
                    "Also write an uncompressed editing WAV."),
    "editing_wav_rate": (48000, "choice", None, "Editing WAV sample rate."),
    "editing_wav_channels": (1, "int", (1, 2), "Editing WAV channel count."),
    "video_image": (None, "path", "file", "Background image for video."),
    "intro_audio": (None, "path", "file", "Audio joined before narration."),
    "outro_audio": (None, "path", "file", "Audio joined after narration."),
    "intro_crossfade": (1.0, "float", (0.0, 30.0),
                        "Crossfade seconds at the intro/outro joins."),
}

# Fields with no sensible default -- a render cannot proceed without them.
REQUIRED = ("path", "root", "engine", "voice", "format")


def _choices(key):
    """Allowed values for a choice field, asked of the module that owns
    them so there is no second copy to fall out of date."""
    if key == "engine":
        from .pipeline import ENGINES
        return list(ENGINES)
    if key == "chunk_mode":
        from .documents import CHUNK_MODES
        return list(CHUNK_MODES)
    if key == "format":
        from .audio import AUDIO_FORMATS
        return list(AUDIO_FORMATS)
    if key in ("sample_rate", "editing_wav_rate"):
        return [22050, 44100, 48000]
    if key == "bit_depth":
        return [16, 24]
    return []


def defaults():
    return {key: spec[0] for key, spec in FIELDS.items()}


def describe():
    """Every field with its type, allowed values and description -- what a
    settings screen, an API doc or a validation message can be built
    from."""
    out = []
    for key, (default, kind, spec, description) in FIELDS.items():
        entry = {"key": key, "kind": kind, "default": default,
                "description": description,
                "required": key in REQUIRED}
        if kind == "choice":
            entry["choices"] = _choices(key)
        elif kind in ("int", "float") and spec:
            entry["min"], entry["max"] = spec
        elif kind == "path":
            # "file" or "dir" -- a settings screen needs this to know
            # whether picking this field means browsing to select a
            # single file (a document, an image) or navigating into a
            # folder (an output root).
            entry["path_kind"] = spec
        out.append(entry)
    return out


def _coerce_one(key, value, problems):
    default, kind, spec, _desc = FIELDS[key]

    if value is None or value == "":
        if key in REQUIRED:
            problems.append(f"{key} is required.")
            return None
        return default if value is None else value

    try:
        if kind == "bool":
            return bool(value)
        if kind == "int":
            number = int(float(value))
            low, high = spec
            if not low <= number <= high:
                problems.append(
                    f"{key} must be between {low} and {high} (got {number}).")
                return max(low, min(high, number))
            return number
        if kind == "float":
            number = float(value)
            low, high = spec
            if not low <= number <= high:
                problems.append(
                    f"{key} must be between {low} and {high} (got {number}).")
                return max(low, min(high, number))
            return number
        if kind == "choice":
            allowed = _choices(key)
            if allowed and value not in allowed:
                # Numeric choices often arrive as strings from a form.
                if isinstance(allowed[0], int):
                    try:
                        number = int(value)
                        if number in allowed:
                            return number
                    except (TypeError, ValueError):
                        pass
                problems.append(
                    f"{key}: {value!r} isn't one of {allowed}.")
                return default
            return value
        if kind == "path":
            text = str(value)
            if spec == "file" and not os.path.isfile(text):
                problems.append(f"{key}: no file at {text}")
            elif spec == "dir" and not os.path.isdir(text):
                problems.append(f"{key}: no folder at {text}")
            return text
        return str(value)
    except (TypeError, ValueError):
        problems.append(f"{key}: {value!r} isn't a valid "
                        f"{kind} (using {default!r}).")
        return default


def coerce(raw, strict_paths=True):
    """(cfg, problems) from anything dict-shaped.

    Missing fields take their default; present ones are range-checked and
    type-converted. Unknown keys are dropped and reported rather than
    passed through, so a typo in a saved project can't silently do
    nothing. With `strict_paths` false, path existence isn't checked --
    useful for validating a settings form before the files are chosen.
    """
    problems = []
    cfg = defaults()
    for key, value in (raw or {}).items():
        if key not in FIELDS:
            problems.append(f"{key} isn't a render setting; ignored.")
            continue
        if not strict_paths and FIELDS[key][1] == "path":
            cfg[key] = value if value in (None, "") else str(value)
            continue
        cfg[key] = _coerce_one(key, value, problems)
    for key in REQUIRED:
        if cfg.get(key) in (None, ""):
            message = f"{key} is required."
            if message not in problems:
                problems.append(message)
    return cfg, problems


def is_valid(raw):
    _cfg, problems = coerce(raw)
    return not problems
