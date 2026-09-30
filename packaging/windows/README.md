# Windows desktop package

The desktop package is a PyInstaller **one-directory** build wrapped by an optional per-user Inno
Setup installer. It deliberately keeps mutable state outside the installation directory:

- application files: `%LOCALAPPDATA%\Programs\SPLICR Studio`
- user data: `%LOCALAPPDATA%\SPLICR Studio\data`
- logs: `%LOCALAPPDATA%\SPLICR Studio\data\logs`

Installing a newer version replaces application files but leaves jobs, SQLite state, credentials,
component settings, generated media, and external model environments untouched. Uninstalling the
application also leaves that data in place so a reinstall can resume it. The app never copies or
deletes the Kokoro, Qwen3-TTS, or Audio8 environments configured in Components.

## Build locally

Requirements:

- Windows x64
- Python 3.11+ and `uv`
- Node.js/npm
- FFmpeg and FFprobe on `PATH`
- Inno Setup 6, unless only the portable ZIP is needed

```powershell
.\packaging\windows\build.ps1 -Version 0.1.0
```

Use `-SkipInstaller` to build only the portable ZIP. `build.ps1` rebuilds the React assets, copies
FFmpeg/FFprobe into the private app bundle, builds the one-directory executable, creates checksums,
records the exact bundled media-tool build, and then compiles the installer. Generated vendor tools
and build outputs are ignored by Git. Every package also includes `THIRD_PARTY_NOTICES.md` and the
generated `BUILD_INFO.txt`; release publishers remain responsible for satisfying the license terms
of the particular FFmpeg build placed on `PATH`. The build locates Inno Setup from `PATH` or its
standard per-user and machine-wide installation directories, so installer builds do not require an
administrator-only Inno installation.

The development workstation currently resolves a `www.gyan.dev` FFmpeg 9.0 full build configured
with `--enable-gpl --enable-version3`. Treat packages produced from that binary as internal
acceptance candidates until the publisher either substitutes a compatible LGPL build or includes
the exact GPL notices, license, corresponding source/source offer, and any other obligations
identified during release review. `BUILD_INFO.txt` is the authoritative record for each candidate;
do not infer its license from an earlier build.

The small native lifecycle window owns the local FastAPI process. It opens `/studio/`, can reopen
the browser or data folder, writes startup diagnostics to `desktop.log`, and shuts the server down
cleanly when closed. Launching a second copy detects the existing local instance and opens it rather
than starting a competing service. `SPLICR Studio.exe --no-browser` runs the same lifecycle window
without automatically opening the browser, which is useful for managed launches and package
acceptance; the window still owns and cleanly stops the private server.

The complete fresh-install, upgrade, uninstall, portable, live-engine, evidence, and rollback matrix
is maintained in [`../../docs/RELEASE_CHECKLIST.md`](../../docs/RELEASE_CHECKLIST.md).
