from __future__ import annotations

import argparse
import asyncio
import getpass
import hmac
import shutil
import sys
from pathlib import Path

import uvicorn

from .auth import AuthManager
from .bootstrap import create_service
from .config import Settings
from .domain import (
    DeliveryControls,
    JobStatus,
    NonverbalFrequency,
    SpeechPace,
    TonePreset,
    VocalStyle,
)
from .storage import LocalJobStorage
from .store import SqliteJobStore
from .pronunciation import TextCustomizationStore
from .studio import (
    SqliteStudioStore,
    import_narrator_customizations,
    import_narrator_projects,
    import_narrator_voices,
    import_splicr_jobs,
    scan_narrator_data,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SPLICR long-document TTS service")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    synthesize = subparsers.add_parser("synthesize", help="synthesize one UTF-8 text file")
    synthesize.add_argument("input", type=Path)
    synthesize.add_argument("output", type=Path)
    synthesize.add_argument("--provider", default="gemini")
    synthesize.add_argument("--model")
    synthesize.add_argument("--voice")
    synthesize.add_argument("--instructions")
    synthesize.add_argument(
        "--tone", choices=[value.value for value in TonePreset], default=TonePreset.NEUTRAL
    )
    synthesize.add_argument(
        "--pace", choices=[value.value for value in SpeechPace], default=SpeechPace.NORMAL
    )
    synthesize.add_argument(
        "--vocal-style",
        choices=[value.value for value in VocalStyle],
        default=VocalStyle.NATURAL,
    )
    synthesize.add_argument(
        "--nonverbal-frequency",
        choices=[value.value for value in NonverbalFrequency],
        default=NonverbalFrequency.NEVER,
    )

    auth = subparsers.add_parser("auth", help="manage application authentication")
    auth_subparsers = auth.add_subparsers(dest="auth_command", required=True)
    set_password = auth_subparsers.add_parser(
        "set-password",
        help="create or reset the application password",
    )
    set_password.add_argument("--username", default="ember")
    set_password.add_argument(
        "--password-stdin",
        action="store_true",
        help="read one password line from standard input (for controlled automation)",
    )
    auth_subparsers.add_parser("status", help="show whether authentication is configured")

    migrate = subparsers.add_parser(
        "migrate-studio",
        help="import existing SPLICR jobs and optional Narrator metadata into Studio",
    )
    migrate.add_argument(
        "--narrator-data",
        type=Path,
        help="path to an existing Narrator narrator_data directory (read-only)",
    )
    migrate.add_argument(
        "--skip-splicr-jobs",
        action="store_true",
        help="only import Narrator metadata",
    )
    return parser


async def _synthesize_file(args: argparse.Namespace) -> int:
    text = args.input.read_text(encoding="utf-8")
    service = create_service(Settings.from_env())
    await service.start()
    try:
        job = await service.submit(
            text=text,
            provider_name=args.provider,
            model=args.model,
            voice=args.voice,
            instructions=args.instructions,
            controls=DeliveryControls(
                tone=TonePreset(args.tone),
                pace=SpeechPace(args.pace),
                vocal_style=VocalStyle(args.vocal_style),
                nonverbal_frequency=NonverbalFrequency(args.nonverbal_frequency),
            ),
        )
        last_completed = -1
        while True:
            job = service.get_job(job.id)
            if job.completed_chunks != last_completed:
                print(
                    f"[{job.status}] {job.completed_chunks}/{job.total_chunks} chunks",
                    flush=True,
                )
                last_completed = job.completed_chunks
            if job.status is JobStatus.COMPLETED:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(service.output_path(job.id), args.output)
                print(f"Wrote {args.output}", flush=True)
                return 0
            if job.status in {JobStatus.PAUSED, JobStatus.FAILED, JobStatus.CANCELLED}:
                detail = job.error or "no additional details"
                print(f"Synthesis stopped ({job.status}): {detail}", file=sys.stderr)
                return 1
            await asyncio.sleep(0.25)
    finally:
        await service.stop()


def _manage_auth(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    manager = AuthManager(
        settings.auth_credentials_path,
        session_seconds=settings.auth_session_seconds,
    )
    if args.auth_command == "status":
        if manager.is_configured:
            print(
                f"Authentication is configured for {manager.configured_username!r} "
                f"at {manager.path}."
            )
            return 0
        print(f"Authentication is not configured at {manager.path}.")
        return 1
    if args.auth_command == "set-password":
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("New SPLICR password: ")
            confirmation = getpass.getpass("Confirm new password: ")
            if not hmac.compare_digest(
                password.encode("utf-8"),
                confirmation.encode("utf-8"),
            ):
                print("Passwords do not match.", file=sys.stderr)
                return 2
        try:
            manager.set_password(args.username, password)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
        print(
            f"Authentication configured for {args.username!r}. "
            "All existing sessions have been invalidated."
        )
        return 0
    raise ValueError(f"unknown auth command: {args.auth_command}")


def _migrate_studio(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    studio_store = SqliteStudioStore(settings.database_path)
    studio_store.initialize()
    imported_jobs = []
    if not args.skip_splicr_jobs:
        job_store = SqliteJobStore(settings.database_path)
        job_store.initialize()
        job_storage = LocalJobStorage(settings.jobs_dir)
        job_storage.initialize()
        imported_jobs = import_splicr_jobs(
            job_store=job_store,
            job_storage=job_storage,
            studio_store=studio_store,
        )

    imported_projects = []
    imported_pronunciations = 0
    imported_substitutions = 0
    imported_voices = []
    warnings: tuple[str, ...] = ()
    if args.narrator_data is not None:
        snapshot = scan_narrator_data(args.narrator_data)
        imported_projects = import_narrator_projects(snapshot, studio_store)
        imported_voices = import_narrator_voices(snapshot, studio_store)
        imported_customizations = import_narrator_customizations(
            snapshot,
            TextCustomizationStore(settings.data_dir / "studio" / "language"),
        )
        imported_pronunciations = imported_customizations.pronunciations
        imported_substitutions = imported_customizations.substitutions
        warnings = snapshot.warnings

    print(
        "Studio migration complete: "
        f"{len(imported_jobs)} SPLICR job(s), "
        f"{len(imported_projects)} Narrator project(s), "
        f"{len(imported_voices)} Narrator voice(s), "
        f"{imported_pronunciations} pronunciation(s), "
        f"{imported_substitutions} substitution(s)."
    )
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.command in (None, "serve"):
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8000)
        reload = getattr(args, "reload", False)
        uvicorn.run("splicr.api:app", host=host, port=port, reload=reload)
        return
    if args.command == "synthesize":
        raise SystemExit(asyncio.run(_synthesize_file(args)))
    if args.command == "auth":
        raise SystemExit(_manage_auth(args))
    if args.command == "migrate-studio":
        raise SystemExit(_migrate_studio(args))
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
