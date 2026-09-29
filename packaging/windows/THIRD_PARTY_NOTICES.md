# Third-party notices

SPLICR Studio packages include separate `ffmpeg.exe` and `ffprobe.exe` command-line programs so
local audio and video processing works without a separate installation. FFmpeg is a third-party
project and is not owned by SPLICR Studio. FFmpeg builds may be distributed under the GNU Lesser
General Public License (LGPL) or GNU General Public License (GPL), depending on their configured
features.

The adjacent `BUILD_INFO.txt` records the version, configuration, and license banner reported by
the exact executables bundled in this package. FFmpeg licensing information and source releases are
available from:

- https://ffmpeg.org/legal.html
- https://ffmpeg.org/download.html

The release publisher must review the recorded configuration and provide all notices, license text,
and corresponding source or source offer required by that particular build before distributing the
package publicly.

Advanced audiogram rendering also includes these Python libraries in the frozen desktop package:

- NumPy, distributed under the BSD 3-Clause license: https://numpy.org/doc/stable/license.html
- Pillow, distributed under the HPND historical permission notice and disclaimer:
  https://github.com/python-pillow/Pillow/blob/main/LICENSE

Other Python and JavaScript dependency licenses remain available from their respective installed
packages and lockfiles in the SPLICR Studio source distribution. Before a public release, preserve
the license/notice files emitted by the frozen package and review this list against the resolved
`uv.lock` and `studio-web/package-lock.json` dependency graphs.
