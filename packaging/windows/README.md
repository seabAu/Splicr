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
- Network access for the pinned, checksum-verified LGPL-shared FFmpeg download (recommended), or a
  reviewed FFmpeg/FFprobe directory supplied explicitly with `-FfmpegBin`
- Inno Setup 6, unless only the portable ZIP is needed

```powershell
$ffmpegBin = .\packaging\windows\fetch-ffmpeg-lgpl.ps1
.\packaging\windows\build.ps1 -Version 0.1.0 -FfmpegBin $ffmpegBin
```

Use `-SkipInstaller` to build only the portable ZIP. `build.ps1` rebuilds the React assets, copies
FFmpeg/FFprobe and required shared DLLs into the private app bundle, builds the one-directory
executable, creates checksums, records the exact bundled media-tool build, and then compiles the
installer. The fetcher pins the BtbN release tag, asset name, and SHA-256 digest; it also creates a
`SOURCE_INFO.txt` record. Generated vendor tools and build outputs are ignored by Git. Every package
includes `THIRD_PARTY_NOTICES.md`, generated `BUILD_INFO.txt`, and the FFmpeg `LICENSE.txt` and
`SOURCE_INFO.txt` beside the bundled media tools. The build locates Inno Setup from `PATH` or its
standard per-user and machine-wide installation directories, so installer builds do not require an
administrator-only Inno installation.

Omitting `-FfmpegBin` retains the legacy behavior of copying `ffmpeg.exe` and `ffprobe.exe` from
`PATH`; that fallback does not discover or copy shared DLLs and must be reviewed independently.
`BUILD_INFO.txt` is authoritative for every candidate. For a public release, also host the exact
corresponding FFmpeg source, add the required attribution/source link to the download surface, and
complete the [FFmpeg legal checklist](https://ffmpeg.org/legal.html); bundling an LGPL build and its
license is necessary but is not, by itself, a legal review.

The small native lifecycle window owns the local FastAPI process. It opens `/studio/`, can reopen
the browser or data folder, writes startup diagnostics to `desktop.log`, and shuts the server down
cleanly when closed. Launching a second copy detects the existing local instance and opens it rather
than starting a competing service. `SPLICR Studio.exe --no-browser` runs the same lifecycle window
without automatically opening the browser, which is useful for managed launches and package
acceptance; the window still owns and cleanly stops the private server.

## Package acceptance

Run the artifact-level harness only on a disposable Windows VM or CI runner. It installs and
uninstalls the real package and therefore writes the normal per-user uninstall registration and
Start menu entry while it runs. The harness requires PowerShell 7 (`pwsh`):

```powershell
.\packaging\windows\test-package.ps1 -Version 0.1.0
```

The harness independently verifies the checksum manifest, extracts the portable ZIP to a path with
spaces, proves portable smoke leaves every package file unchanged, redirects mutable state to a
separate per-user data root, silently installs the real installer, checks FFmpeg's shared LGPL
configuration and provenance files, renders and probes an OpenH264/AAC MP4, uninstalls, and proves
the application directory is removed while user data remains. It writes a machine-readable
`SPLICR-Studio-<version>-Windows-x64-ACCEPTANCE.json` beside the packages. The release workflow
runs this gate before uploading any artifact.

This automated harness does not replace the release checklist's interactive clean-VM checks for
the lifecycle window, browser launch/reuse, real document playback, upgrade migration, Windows
Settings, Start menu behavior, or signing/malware review.

## Removing local data manually

Windows uninstall intentionally removes only the application and shortcuts. To erase projects,
profiles, job history, generated media, settings, logs, and locally stored credential material,
first close SPLICR Studio and back up anything needed, then delete
`%LOCALAPPDATA%\SPLICR Studio\data` in File Explorer. This action is permanent and is deliberately
separate from uninstall so upgrading or reinstalling cannot silently destroy in-progress work.

The complete fresh-install, upgrade, uninstall, portable, live-engine, evidence, and rollback matrix
is maintained in [`../../docs/RELEASE_CHECKLIST.md`](../../docs/RELEASE_CHECKLIST.md).
