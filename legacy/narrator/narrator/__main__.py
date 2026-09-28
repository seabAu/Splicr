"""Entry point. Dispatches between the GUI, the headless commands, and
the cross-environment worker.

    python -m narrator                     the GUI
    python -m narrator render doc.md ...   narrate, no GUI
    python -m narrator queue               render the library, no GUI
    python -m narrator transcribe a.mp3    audio back into text
    python -m narrator settings            what a render accepts
    python -m narrator --clean doc.docx    clean a document
    python -m narrator --worker job.json   internal, runs inside another venv

The headless commands exist for their own sake -- scripting a batch
overnight, or driving Narrator from something that isn't this GUI -- and
also as a standing check that the engine code really is independent of the
interface. If a command here needs something from `ui.py`, the separation
has regressed.

The worker path must never import tkinter, since the environment it runs
in (a Kokoro or Qwen3 venv) may have no Tk at all. That is why every
import below sits inside its branch rather than at module level.
"""

import sys


def _log(message):
    print(message, flush=True)


def _cmd_web(argv):
    """Serve the browser interface. Localhost only unless deliberately
    overridden -- this API can browse the filesystem and start processes."""
    import argparse
    import os

    parser = argparse.ArgumentParser(
        prog="narrator web",
        description="Open Narrator in a browser (local only).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1",
                        help="leave as localhost unless you understand "
                             "the exposure")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    try:
        from . import webapi
    except ImportError as exc:
        print("The browser interface needs FastAPI, uvicorn, and "
             "python-multipart (for file uploads, like cloning a voice "
             "from a recording):\n"
              "    pip install fastapi uvicorn python-multipart\n"
              f"({exc})", file=sys.stderr)
        return 1

    static = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "webui")
    if not os.path.isdir(static):
        print("The interface hasn't been built yet. From the web/ folder:\n"
              "    npm install && npm run build", file=sys.stderr)
        static = None
    webapi.serve(host=args.host, port=args.port, static_dir=static,
                 open_browser=not args.no_browser)
    return 0


def _cmd_settings(argv):
    """Print the render schema -- what a render accepts, and the allowed
    values. Generated from render_config, never hand-maintained."""
    from .render_config import describe
    for field in describe():
        bits = [field["kind"]]
        if field.get("choices"):
            shown = field["choices"]
            if len(shown) > 4:
                shown = shown[:4] + ["..."]
            bits.append("one of " + ", ".join(str(c) for c in shown))
        elif "min" in field:
            bits.append(f"{field['min']} to {field['max']}")
        if field["required"]:
            bits.append("REQUIRED")
        else:
            bits.append(f"default {field['default']!r}")
        print(f"  {field['key']:<22} {'; '.join(bits)}")
        print(f"  {'':<22} {field['description']}")
    return 0


def _cmd_render(argv):
    import argparse
    import os
    from .pipeline import ENGINES
    from .render_config import coerce
    from . import session as session_mod

    parser = argparse.ArgumentParser(
        prog="narrator render",
        description="Narrate a document without opening the app.")
    parser.add_argument("document")
    parser.add_argument("--engine", help="engine name; see 'settings'")
    parser.add_argument("--voice", help="voice id, or a description for "
                                        "engines that design one")
    parser.add_argument("--take", type=int)
    parser.add_argument("--speed", type=int)
    parser.add_argument("--format", dest="format")
    parser.add_argument("--out", dest="root", help="output folder")
    parser.add_argument("--subtitles", action="store_true")
    parser.add_argument("--chunk-mode", dest="chunk_mode",
                        choices=["parts", "tokens", "chars"])
    parser.add_argument("--chunk-target", dest="chunk_target", type=int)
    args = parser.parse_args(argv)

    raw = {k: v for k, v in vars(args).items()
          if v is not None and v is not False and k != "document"}
    raw["path"] = args.document
    raw.setdefault("root", os.path.dirname(os.path.abspath(args.document)))
    if not raw.get("engine"):
        available = [n for n, s in ENGINES.items() if s["detect"]()]
        if not available:
            print("No engine is set up. Run the app once to install one.",
                  file=sys.stderr)
            return 1
        raw["engine"] = available[0]
    spec = ENGINES.get(raw["engine"])
    if spec is None:
        print(f"Unknown engine {raw['engine']!r}. Try: "
              + ", ".join(ENGINES), file=sys.stderr)
        return 1
    if not raw.get("voice"):
        raw["voice"] = spec["voices"][0][0] if spec["voices"] else ""
    raw.setdefault("format", "MP3 (most compatible)")

    cfg, problems = coerce(raw)
    for problem in problems:
        print("  " + problem, file=sys.stderr)
    if any("required" in p or "isn't one of" in p or "no file at" in p
          or "no folder at" in p for p in problems):
        return 1

    out = session_mod.render_document(cfg, _log, spec, session_mod.Session())
    if not out:
        print("Rendering produced no output.", file=sys.stderr)
        return 1
    print(out)
    return 0


def _cmd_queue(argv):
    import argparse
    from .pipeline import ENGINES
    from . import library
    from . import session as session_mod

    parser = argparse.ArgumentParser(
        prog="narrator queue",
        description="Render library documents back to back.")
    parser.add_argument("paths", nargs="*",
                        help="document paths; default is every library "
                             "entry that has saved settings")
    args = parser.parse_args(argv)

    paths = args.paths or [p["path"] for p in library.all_projects()
                          if (p.get("cfg") or {}).get("engine")]
    if not paths:
        print("Nothing to render. Render a document once from the app "
              "first, so its settings are saved.", file=sys.stderr)
        return 1
    outcome = session_mod.run_queue(paths, _log, ENGINES,
                                    session_mod.Session())
    return 0 if not outcome["failed"] else 1


def _cmd_transcribe(argv):
    import argparse
    from . import tasks
    from .transcribe import MODEL_SIZES, TranscribeUnavailable

    parser = argparse.ArgumentParser(
        prog="narrator transcribe",
        description="Turn existing speech audio back into text.")
    parser.add_argument("audio")
    parser.add_argument("--model", default="base",
                        choices=[k for k, _d in MODEL_SIZES])
    parser.add_argument("--no-subtitles", action="store_true")
    parser.add_argument("--no-chapters", action="store_true")
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--out", dest="out_dir")
    args = parser.parse_args(argv)

    try:
        made = tasks.transcribe_file(
            args.audio, _log, model=args.model,
            want_srt=not args.no_subtitles,
            want_chapters=not args.no_chapters,
            timestamps=args.timestamps, out_dir=args.out_dir)
    except TranscribeUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for path in made:
        print(path)
    return 0


COMMANDS = {
    "web": _cmd_web,
    "render": _cmd_render,
    "queue": _cmd_queue,
    "transcribe": _cmd_transcribe,
    "settings": _cmd_settings,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--worker" in argv:
        i = argv.index("--worker")
        if len(argv) <= i + 1:
            raise SystemExit(
                "--worker requires a job file path.\n"
                "This flag is used internally when the app runs an engine "
                "inside another environment; you don't need to call it "
                "yourself. To start the app normally, run it with no "
                "arguments.")
        from .engines import worker_main
        worker_main(argv[i + 1])
        return

    if "--clean" in argv:
        i = argv.index("--clean")
        from .documents import clean_main
        clean_main(argv[i + 1:])
        return

    if argv and argv[0] in COMMANDS:
        raise SystemExit(COMMANDS[argv[0]](argv[1:]))

    if argv and not argv[0].startswith("-"):
        raise SystemExit(
            f"Unknown command {argv[0]!r}.\n"
            "Available: " + ", ".join(sorted(COMMANDS))
            + "\nRun with no arguments to open the app.")

    from .ui import launch
    launch()


if __name__ == "__main__":
    main()
