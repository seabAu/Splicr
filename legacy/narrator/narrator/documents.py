"""Document loading and cleaning (formerly prep_for_tts.py).

Converts .docx/.odt/.html/.tex/.epub via pandoc, then strips
citations, reference lists, tables and markdown syntax so the text
reads cleanly aloud.
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


# Text handling
# ===========================================================================
# Document cleaning pipeline (from prep_for_tts.py)
#
# Turns a raw document -- .docx, .odt, .html, .tex, .epub via pandoc, or
# .md/.txt directly -- into clean, speakable text: citation markers, tables,
# reference lists, markdown syntax, and academic abbreviations are all
# handled before anything reaches a TTS engine. This used to be a separate
# script (prep_for_tts.py) that narrator_gui.py imported by file path; it's
# merged in directly so the whole tool is one file with one thing to run.
#
# The command-line entry point (`python narrator_gui.py --clean doc.docx`)
# is preserved at the bottom of this file for scripting use outside the GUI.
# ===========================================================================


# ---------------------------------------------------------------------------
# Configuration tables
# ---------------------------------------------------------------------------

# Headings after which everything is back-matter and should be dropped.
BACK_MATTER = [
    "references", "bibliography", "works cited", "reference list",
    "literature cited", "appendix", "appendices", "endnotes",
    "notes and references", "source list",
]

# Front-matter headings usually not worth narrating.
FRONT_MATTER = [
    "table of contents", "contents", "list of figures", "list of tables",
    "list of abbreviations", "list of acronyms", "nomenclature",
    "declaration", "copyright notice",
]

# Abbreviations -> how they should be spoken.
# Order matters: longer patterns first.
SPEAK_AS = [
    (r"\bet\s+al\.\s*", "and colleagues "),
    (r"\be\.\s*g\.\s*,?\s*", "for example, "),
    (r"\bi\.\s*e\.\s*,?\s*", "that is, "),
    (r"\bcf\.\s*", "compare "),
    (r"\bviz\.\s*", "namely "),
    (r"\bibid\.\s*", ""),
    (r"\bvs\.?\s+", "versus "),
    (r"\betc\.", "and so on."),
    (r"\bFigs?\.\s*", "Figure "),
    (r"\bEqs?\.\s*", "Equation "),
    (r"\bSect?s?\.\s*", "Section "),
    (r"\bpp\.\s*", "pages "),
    (r"\bp\.\s*(?=\d)", "page "),
    (r"\bch\.\s*(?=\d)", "chapter "),
    (r"\bno\.\s*(?=\d)", "number ")
    ,
    (r"\bapprox\.\s*", "approximately "),
    (r"\bw\.r\.t\.\s*", "with respect to "),
    (r"\ba\.k\.a\.\s*", "also known as "),
    (r"\bDr\.\s*", "Doctor "),
    (r"\bProf\.\s*", "Professor "),
    (r"\bvol\.\s*(?=\d)", "volume "),
    (r"\bed\.\s*", "edition "),
    (r"%", " percent"),
    (r"\s&\s", " and "),
    (r"\bR&D\b", "R and D"),
    (r"—", ", "),
    (r"–", " to "),
    (r"\.\.\.", ", "),
    (r"…", ", "),
]

CITATION_PATTERNS = [
    # [12]  [1,2,3]  [1-5]
    (r"\s*\[\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\]", "bracketed numeric citations"),
    # (ibid.) (op. cit.)
    (r"\s*\(\s*(?:ibid\.?|op\.\s*cit\.?|loc\.\s*cit\.?)\s*\)", "ibid / op. cit."),
    # (p. 45) (pp. 45-49)
    (r"\s*\(\s*pp?\.\s*\d+(?:\s*[-–]\s*\d+)?\s*\)", "bare page references"),
    # pandoc footnote markers
    (r"\[\^\w+\]", "footnote markers"),
]

# Any parenthetical containing a plausible publication year, checked by heuristic
# before removal so that prose like "(first proposed in 2014)" survives.
PAREN_WITH_YEAR = re.compile(r"\s*\([^()]{0,200}?\b(?:1[6-9]\d{2}|20\d{2})[a-z]?\b[^()]{0,60}?\)")

_CITE_LEAD = re.compile(r"^\s*(?:see\s+also\s+|see\s+|cf\.?\s*|e\.g\.,?\s*|i\.e\.,?\s*)?"
                        r"(?:[A-Z]|&)")


def _looks_like_citation(inner):
    """True if a parenthetical is a reference rather than ordinary prose.

    Citations start with a surname (or an editorial lead-in), stay short, and
    are dominated by capitalised tokens. Sentences like 'first proposed in 2014'
    fail all three tests.
    """
    inner = inner.strip().strip("()").strip()
    if not inner or len(inner.split()) > 20:
        return False
    if not _CITE_LEAD.match(inner):
        return False
    if re.search(r"\b(?:et\s+al|&|and\s+colleagues)\b", inner, re.I):
        return True
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", inner)]
    if not words:
        return False
    capped = sum(1 for w in words if w[0].isupper())
    # Ordinary prose in parentheses is mostly lowercase; citations are not.
    return capped / len(words) >= 0.6

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+|doi:\s*\S+", re.I)

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load(path):
    """Read a document into raw text, converting via pandoc if needed.

    Raises DocumentLoadError (never sys.exit) for anything that goes wrong,
    so this is safe to call from a long-running program like a GUI -- a
    library function that can kill the whole host process on a bad input is
    a defect, not a feature. main() is the only place sys.exit belongs; it
    catches DocumentLoadError at its own boundary and converts it there.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".txt", ".markdown"):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if ext == ".pdf":
        raise DocumentLoadError(
            "PDF input: run `pdftotext -layout in.pdf out.txt` first, "
            "then pass the .txt. PDF text order is too unreliable to "
            "clean blindly.")
    if not _have("pandoc"):
        raise DocumentLoadError(
            f"Need pandoc to read {ext} files, and it isn't installed (or "
            f"isn't on PATH). Install it from pandoc.org, or export your "
            f"document to .txt/.md and use that instead.")
    try:
        out = subprocess.run(
            # gfm forces pipe tables; simple/multiline tables are undetectable
            # once the pipes are gone.
            ["pandoc", "-t", "gfm", "--wrap=none", path],
            capture_output=True, text=True, check=True)
        # out.stdout should always be a string here (capture_output=True,
        # text=True), but a None has been observed reaching normalise() on
        # at least one real Windows setup -- cause not fully pinned down,
        # so guard it explicitly rather than let a bare AttributeError
        # surface as a raw, unhelpful error dialog.
        if out.stdout is None:
            raise DocumentLoadError(
                f"pandoc ran but returned no text for {path}. The file may "
                f"be empty, corrupted, or in a format pandoc can open but "
                f"not extract text from. Try opening it in Word and using "
                f"Save As to a fresh .docx, or export to .txt instead.")
        return out.stdout
    except subprocess.CalledProcessError as exc:
        raise DocumentLoadError(f"pandoc failed on {path}:\n{exc.stderr}")
    except OSError as exc:
        # pandoc claimed to be on PATH by _have() but couldn't actually be
        # launched (permissions, a broken shim, antivirus interference).
        raise DocumentLoadError(f"Could not run pandoc on {path}: {exc}")


def normalise(text):
    """Undo converter artefacts before any pattern matching happens."""
    if text is None:
        # Should be unreachable now that load() guards its own return, but
        # kept as a second, independent line of defence -- cheap insurance
        # against a confusing AttributeError if some other caller ever
        # passes None here instead.
        raise DocumentLoadError(
            "The document converter returned nothing to clean. Try "
            "re-saving the source file and reading it again.")
    text = text.replace("\u00a0", " ").replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # pandoc escapes markdown-significant characters; \[3\] must become [3]
    # or the citation patterns will never fire.
    text = re.sub(r"\\([\[\]()*_#`~<>|$-])", r"\1", text)
    return text


def _have(binary):
    """True if `binary` is runnable from PATH. Uses shutil.which, not a
    subprocess call to the Unix `which` command -- that command doesn't
    exist on Windows, so calling it there would always report pandoc as
    absent even when it's correctly installed."""
    return shutil.which(binary) is not None


# ---------------------------------------------------------------------------
# Cleaning stages
# ---------------------------------------------------------------------------


def cut_back_matter(text, log):
    """Drop everything from the first References/Bibliography heading onward."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip().lstrip("#").strip().rstrip(":").lower()
        stripped = re.sub(r"^(chapter|section|appendix)?\s*[\dIVXivx]*[.\)]?\s*",
                          "", stripped).strip()
        if stripped in BACK_MATTER and _looks_like_heading(line):
            removed = len(lines) - i
            log.append(f"Cut back matter from line {i + 1} "
                       f"(heading: {line.strip()[:60]!r}) - {removed} lines removed")
            return "\n".join(lines[:i])
    log.append("No references/bibliography heading found - nothing cut from the end")
    return text


def _looks_like_heading(line):
    s = line.strip()
    if not s:
        return False
    if s.startswith("#"):
        return True
    # ALL CAPS or Title Case short line with no terminal punctuation
    if len(s) < 60 and not s.endswith((".", ",", ";", ":")):
        return s.isupper() or s.istitle()
    return False


def drop_front_matter_sections(text, log):
    """Remove TOC / list-of-figures style sections (heading + its body)."""
    lines = text.split("\n")
    out, skipping, dropped = [], False, 0
    for line in lines:
        key = line.strip().lstrip("#").strip().rstrip(":").lower()
        # Only a hard heading ends a front-matter section. Title-cased lines are
        # not enough: a table of contents is full of them.
        hard = line.strip().startswith("#") or (
            line.strip().isupper() and 0 < len(line.strip()) < 60)
        if hard:
            skipping = key in FRONT_MATTER
            if skipping:
                log.append(f"Dropped front-matter section: {line.strip()[:60]!r}")
        if skipping:
            dropped += 1
            continue
        out.append(line)
    if dropped:
        log.append(f"  ({dropped} front-matter lines removed)")
    return "\n".join(out)


def handle_tables(text, mode, log):
    """Markdown/grid tables read as gibberish aloud. Remove, describe, or narrate."""
    lines = text.split("\n")
    out, buf, count = [], [], 0

    def is_table_line(s):
        t = s.strip()
        if not t:
            return False
        if t.startswith("|") and t.count("|") >= 2:
            return True
        if re.fullmatch(r"[+|:\-=\s]{6,}", t):   # grid rules / separator rows
            return True
        return False

    def flush():
        nonlocal count
        if not buf:
            return
        count += 1
        if mode == "drop":
            pass
        elif mode == "mention":
            out.append(f"A table appears here in the written version; "
                       f"see the linked document for the full data.")
        elif mode == "keep":
            # Verbatim -- by the time this runs, load() has already put
            # any non-Markdown source (docx/odt/...) through pandoc, so
            # this is always valid Markdown table syntax already, not
            # whatever the original file format's table markup was.
            out.extend(buf)
        else:  # describe
            out.append(_narrate_table(buf, count))
        buf.clear()

    for line in lines:
        if is_table_line(line):
            buf.append(line)
        else:
            flush()
            out.append(line)
    flush()

    if count:
        log.append(f"Tables handled: {count} (mode: {mode})")
    else:
        log.append("No tables detected")
    return "\n".join(out)


def _narrate_table(rows, index):
    cells = []
    for r in rows:
        if re.fullmatch(r"[+|:\-=\s]{6,}", r.strip()):
            continue
        parts = [c.strip() for c in r.strip().strip("|").split("|")]
        parts = [p for p in parts if p]
        if parts:
            cells.append(parts)
    if not cells:
        return ""
    header = cells[0]
    body = cells[1:]
    text = (f"Table {index}. The columns are: " + ", ".join(header) + ". ")
    for row in body[:8]:
        pairs = [f"{h}, {v}" for h, v in zip(header, row)]
        text += "; ".join(pairs) + ". "
    if len(body) > 8:
        text += (f"The table continues for {len(body) - 8} further rows, "
                 "which are given in the written version. ")
    return text


def strip_citations(text, log):
    for pattern, label in CITATION_PATTERNS:
        text, n = re.subn(pattern, "", text)
        if n:
            log.append(f"Removed {n} {label}")

    removed = {"n": 0, "kept": 0}

    def decide(match):
        if _looks_like_citation(match.group(0)):
            removed["n"] += 1
            return ""
        removed["kept"] += 1
        return match.group(0)

    text = PAREN_WITH_YEAR.sub(decide, text)
    if removed["n"]:
        log.append(f"Removed {removed['n']} author-year parentheticals")
    if removed["kept"]:
        log.append(f"Kept {removed['kept']} parentheticals containing a year "
                   "(judged to be prose, not citations) - spot-check these")
    return text


def strip_urls(text, log):
    """Remove URLs. Short 'see <link> for details' sentences go entirely -
    the stub left behind is worse than silence when read aloud."""
    dropped = [0]

    def clean_sentence(sentence):
        if not URL_PATTERN.search(sentence):
            return sentence
        stripped = URL_PATTERN.sub("", sentence)
        if len(stripped.split()) < 12:
            dropped[0] += 1
            return ""
        return stripped

    out_paras = []
    for para in text.split("\n\n"):
        kept = [clean_sentence(s) for s in split_sentences(para)]
        kept = [s for s in kept if s.strip()]
        out_paras.append(" ".join(kept) if kept else "")
    text = "\n\n".join(out_paras)

    text, n = URL_PATTERN.subn("", text)
    total = n + dropped[0]
    if total:
        log.append(f"Removed {total} URLs / DOIs "
                   f"({dropped[0]} whole pointer sentences dropped)")
    return text


def handle_lists(text, log):
    """Turn bullet and numbered list items into standalone sentences.

    Without terminal punctuation a TTS engine runs list items together into one
    long breathless clause.
    """
    lines, out, n = text.split("\n"), [], 0
    marker = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
    for line in lines:
        m = marker.match(line)
        if m and m.group(1).strip():
            item = m.group(1).strip()
            if not item.endswith((".", "!", "?", ":", ";")):
                item += "."
            out.append(item)
            n += 1
        else:
            out.append(line)
    log.append(f"Converted {n} list items into standalone sentences")
    return "\n".join(out)


def strip_markdown(text, log):
    """Remove syntax that would be read aloud as punctuation soup."""
    subs = [
        (r"!\[[^\]]*\]\([^)]*\)", ""),               # images
        (r"\[([^\]]+)\]\([^)]*\)", r"\1"),           # links -> link text
        (r"^\s*[:>]\s?", "", re.M),                  # blockquote / defn markers
        (r"`{1,3}([^`]*)`{1,3}", r"\1"),             # code spans
        (r"\*\*\*([^*]+)\*\*\*", r"\1"),
        (r"\*\*([^*]+)\*\*", r"\1"),
        (r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1"),
        (r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1"),
        (r"^\s*[-*+]\s+", "", re.M),                 # bullets
        (r"^\s*\d+[.)]\s+", "", re.M),               # numbered list markers
        (r"^\s*[-=]{3,}\s*$", "", re.M),             # horizontal rules
        (r"\{[^{}]*\}", ""),                         # pandoc attribute blocks
        (r"\\\[|\\\]|\\\(|\\\)", ""),                # escaped math delims
    ]
    for sub in subs:
        if len(sub) == 3:
            text = re.sub(sub[0], sub[1], text, flags=sub[2])
        else:
            text = re.sub(sub[0], sub[1], text)
    log.append("Stripped markdown formatting, links, images, and list markers")
    return text


def handle_headings(text, keep, log, headings_out=None):
    """Convert headings into spoken section transitions, remove them, or
    (keep="markup") preserve them as real Markdown headings -- for the
    transcript export, which is read, not narrated.

    If `headings_out` is a list, (title, level, hint) is appended for every
    heading that has body text after it -- regardless of `keep`, so the
    normal narration path (keep=False) can collect this for free without
    changing what's actually narrated. `hint` is up to 80 characters of
    that following text, already run through the same abbreviation
    expansion and whitespace tidying the real pipeline applies afterward
    (expand_abbreviations/tidy), so it matches the form that text will
    actually take in a rendered chunk -- the thing this exists to be
    searched for later (see chapters.py).
    """
    lines, out, n = text.split("\n"), [], 0
    pending = None  # (title, level) waiting for the next content line
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            n += 1
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip().rstrip(".")
            if headings_out is not None:
                pending = (title, level)
            if keep:
                out.append("")
                if keep == "markup":
                    out.append("#" * max(1, min(level, 6)) + " " + title)
                else:
                    out.append(f"{title}.")
                out.append("")
            continue
        if pending is not None and stripped:
            _dummy = []
            hint = tidy(expand_abbreviations(stripped, _dummy), _dummy)[:80]
            if hint:
                headings_out.append((pending[0], pending[1], hint))
            pending = None
        out.append(line)
    mode = ("kept as headings" if keep == "markup" else
           "spoken as transitions" if keep else "removed")
    log.append(f"Headings: {n} found ({mode})")
    return "\n".join(out)


def expand_abbreviations(text, log):
    total = 0
    for pattern, replacement in SPEAK_AS:
        text, n = re.subn(pattern, replacement, text)
        total += n
    log.append(f"Expanded {total} abbreviations and symbols into spoken forms")
    return text


def tidy(text, log):
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([.,;:!?])", r"\1", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"([.,;:!?]){2,}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(l.strip() for l in text.split("\n"))
    log.append("Collapsed whitespace and orphaned punctuation")
    return text.strip()


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk(text, size):
    """Pack sentences into chunks under `size` characters, never mid-sentence."""
    chunks, current = [], ""
    for para in text.split("\n\n"):
        for sentence in split_sentences(para):
            if len(current) + len(sentence) + 1 > size and current:
                chunks.append(current.strip())
                current = ""
            current += sentence + " "
        current += "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


class DocumentLoadError(Exception):
    """A document couldn't be read or converted (missing pandoc, corrupt
    file, unsupported format). A normal exception, not sys.exit -- library
    callers like narrator_gui.py need to catch this and show a message
    without the whole program exiting."""


def clean_document(path, tables="describe", keep_headings=False,
                   headings_out=None):
    """Run the full cleaning pipeline on one file.

    Returns (text, log, original_words). This is the same sequence main()
    drives from the command line, exposed as a plain function so other tools
    (narrator_gui.py) can call it directly instead of re-implementing
    document loading and cleanup.

    `headings_out`, if a list, collects (title, level, hint) for every
    heading with body text after it -- see handle_headings. Passing it
    doesn't change the returned text even at the default keep_headings, so
    the exact call already used for real narration can be reused to also
    recover chapter information, guaranteeing the text it's matched against
    is identical to what was actually chunked and rendered.

    Raises FileNotFoundError if `path` doesn't exist, and DocumentLoadError
    for anything that goes wrong reading or converting it (missing pandoc,
    pandoc failing on a corrupt file, an unsupported format like .pdf).
    Never calls sys.exit -- that would kill the calling process, which is
    fine for the command line but wrong for a long-running GUI.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    log = []
    raw = normalise(load(path))
    original_words = len(raw.split())

    text = cut_back_matter(raw, log)
    text = drop_front_matter_sections(text, log)
    text = handle_tables(text, tables, log)
    text = strip_citations(text, log)
    text = strip_urls(text, log)
    text = handle_lists(text, log)
    text = strip_markdown(text, log)
    text = handle_headings(text, keep_headings, log, headings_out=headings_out)
    text = expand_abbreviations(text, log)
    text = tidy(text, log)
    return text, log, original_words


# ---------------------------------------------------------------------------

TITLES = (r"Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|Rev|Hon|Gen|Col|Lt|Sgt|Capt"
          r"|Ave|Blvd|Inc|Ltd|Co|Corp|Dept|Univ|Fig|Eq|Vol|No|pp|p"
          r"|vs|etc|al|eds|ed|approx|est|cf|viz")


def split_sentences(text):
    """Split on sentence ends, protecting initials, decimals and titles."""
    guard = re.sub(rf"\b({TITLES})\.", r"\1<D>", text)
    guard = re.sub(r"(\b[A-Z])\.(?=\s*[A-Z])", r"\1<D>", guard)
    guard = re.sub(r"(\d)\.(\d)", r"\1<D>\2", guard)
    parts = re.split(r"(?<=[.!?])\s+", guard)
    return [p.replace("<D>", ".").strip() for p in parts if p.strip()]


# How a document gets divided. "parts" = a count (split evenly into N);
# "tokens" = aim for a phoneme-token budget per part (Kokoro's unit -- see
# engines.KOKORO_TOKEN_LIMIT); "chars" = a plain character budget.
CHUNK_MODES = ("parts", "tokens", "chars")

# Until a document is actually measured, tokens<->characters needs SOME
# ratio. This is a starting estimate only, and is labelled as such
# wherever it reaches the user: Kokoro's phoneme string includes stress
# marks and separators, so it runs close to the character count but never
# exactly equal. measure_kokoro_phonemes() replaces this with the real
# ratio for the specific document in hand, which beats any constant that
# could be hardcoded here.
DEFAULT_CHARS_PER_TOKEN = 1.05


def chunk_limit_for(text, mode, value, engine_cap,
                    chars_per_token=DEFAULT_CHARS_PER_TOKEN):
    """The character limit to hand chunk_text(), whichever way the user
    chose to express the division. One function so the on-screen preview
    and the actual render can never disagree about what a setting means."""
    value = max(1, int(value or 1))
    if mode == "tokens":
        limit = int(value * max(0.1, chars_per_token))
    elif mode == "chars":
        limit = value
    else:  # parts
        limit = len(text) // value + 1
    return max(200, min(limit, engine_cap))


def chunk_text(text, size):
    """Pack whole sentences into chunks under `size` characters."""
    chunks, current = [], ""
    for para in text.split("\n\n"):
        for sentence in split_sentences(para):
            if len(current) + len(sentence) + 1 > size and current.strip():
                chunks.append(current.strip())
                current = ""
            current += sentence + " "
        current += "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text.strip()]


TEXT_EXTENSIONS = {".txt"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
# Formats the document-cleaning pipeline above can convert via pandoc.
# Anything outside this set and outside TEXT_EXTENSIONS/MARKDOWN_EXTENSIONS is
# read as plain text, which is safe for unknown-but-textual formats and
# merely unhelpful (not dangerous) for anything else -- the person hears the
# problem immediately rather than the app pretending to support a format it
# doesn't.
CONVERTIBLE_EXTENSIONS = {".docx", ".odt", ".html", ".htm", ".tex", ".epub"}

_TEXT_CACHE = {}    # path -> ((mtime, size), text), so the five call sites
                    # that read the current document don't re-run pandoc or
                    # re-clean on every keystroke/slider move, while a
                    # re-saved file is still picked up fresh


def read_text_file(path):
    """Read a source document as clean, speakable text.

    .docx/.odt/.html/.tex/.epub are converted via the document-cleaning
    pipeline above (pandoc-based). Reading these formats as raw bytes,
    which is what a plain open()-and-decode does, silently feeds binary/
    markup data to the TTS engines instead of failing loudly.

    .md/.markdown also goes through the same cleaning pipeline, so heading
    marks, bold/italic markers, and list bullets don't get read aloud as
    "hashtag" and "asterisk asterisk". .txt is returned as-is, since plain
    text has nothing to strip.

    Raises ValueError with a clear, user-facing message if the file can't be
    read -- callers are expected to catch this and show it, not let it
    propagate to a crash.
    """
    ext = os.path.splitext(path)[1].lower()

    try:
        stat = os.stat(path)
        cache_key = (stat.st_mtime, stat.st_size)
    except OSError:
        cache_key = None

    if cache_key is not None and path in _TEXT_CACHE:
        cached_key, cached_text = _TEXT_CACHE[path]
        if cached_key == cache_key:
            return cached_text

    text = _read_text_file_uncached(path, ext)

    if cache_key is not None:
        _TEXT_CACHE[path] = (cache_key, text)
    return text


def _read_text_file_uncached(path, ext):
    if ext in CONVERTIBLE_EXTENSIONS or ext in MARKDOWN_EXTENSIONS:
        try:
            text, _log, _orig_words = clean_document(path)
            return text
        except FileNotFoundError:
            raise ValueError(f"{os.path.basename(path)} doesn't exist.")
        except DocumentLoadError as exc:
            if ext in MARKDOWN_EXTENSIONS:
                # Markdown can always fall back to a plain read -- worst
                # case the person hears "hashtag" occasionally, which is
                # recoverable, unlike silently returning nothing for a
                # format (.docx etc.) that has no plain-text fallback at all.
                return _read_plain(path)
            raise ValueError(str(exc))
        except Exception as exc:
            # Last-resort net: something inside the cleaning pipeline broke
            # in a way not already covered above (an unusual document
            # structure, an encoding edge case, anything not yet seen).
            # Whatever it is, the person should get a message they can act
            # on -- retry, or fall back to plain text -- never a raw
            # AttributeError/TypeError with no next step attached to it.
            if ext in MARKDOWN_EXTENSIONS:
                return _read_plain(path)
            raise ValueError(
                f"{os.path.basename(path)} could not be cleaned "
                f"({type(exc).__name__}: {exc}). Try re-saving the file "
                f"from its original application, or converting it to "
                f".txt/.md and using that instead.")

    return _read_plain(path)


def _read_plain(path):
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, encoding=encoding) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def clean_main(argv):
    ap = argparse.ArgumentParser(
        description="Clean an academic document into speakable text for TTS.")
    ap.add_argument("input")
    ap.add_argument("--outdir", default="tts_out")
    ap.add_argument("--chunk", type=int, default=4000,
                    help="Max characters per chunk (default 4000). "
                         "ElevenLabs free: 2500. Gemini: much higher. "
                         "edge-tts: no practical limit, use 20000.")
    ap.add_argument("--tables", choices=["describe", "mention", "drop"],
                    default="describe",
                    help="What to do with tables (default: describe)")
    ap.add_argument("--keep-headings", action="store_true",
                    help="Speak headings as section transitions instead of "
                         "deleting them")
    ap.add_argument("--wpm", type=int, default=155,
                    help="Words per minute for the runtime estimate")
    args = ap.parse_args(argv)

    try:
        text, log, original_words = clean_document(
            args.input, args.tables, args.keep_headings)
    except FileNotFoundError:
        sys.exit(f"No such file: {args.input}")
    except DocumentLoadError as exc:
        sys.exit(str(exc))

    words = len(text.split())
    minutes = words / args.wpm

    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.input))[0]

    clean_path = os.path.join(args.outdir, f"{stem}_clean.txt")
    with open(clean_path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")

    parts = chunk(text, args.chunk)
    for i, part in enumerate(parts, 1):
        with open(os.path.join(args.outdir, f"{stem}_chunk_{i:03d}.txt"),
                  "w", encoding="utf-8") as fh:
            fh.write(part + "\n")

    report = [
        f"Source:            {args.input}",
        f"Words before:      {original_words:,}",
        f"Words after:       {words:,}  ({original_words - words:,} removed)",
        f"Characters:        {len(text):,}",
        f"Estimated runtime: {int(minutes)} min {int((minutes % 1) * 60)} sec "
        f"at {args.wpm} wpm",
        f"Chunks written:    {len(parts)} (max {args.chunk} chars each)",
        "",
        "What was done:",
    ] + [f"  - {line}" for line in log] + [
        "",
        "REVIEW BEFORE NARRATING:",
        "  - Search the clean file for '(' and '[' - leftover parentheticals",
        "    usually mean an unusual citation style the patterns missed.",
        "  - Check any equations; they need rewriting by hand into words.",
        "  - Read the first and last 200 words aloud yourself. If you stumble,",
        "    the TTS engine will too.",
    ]
    report_text = "\n".join(report)
    with open(os.path.join(args.outdir, f"{stem}_report.txt"),
              "w", encoding="utf-8") as fh:
        fh.write(report_text + "\n")

    print(report_text)
    print(f"\nWrote {len(parts) + 2} files to {args.outdir}/")
