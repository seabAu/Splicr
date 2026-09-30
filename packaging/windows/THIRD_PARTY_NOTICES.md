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

The `0.1.0-dev.5` Windows acceptance candidate uses the checksum-pinned BtbN
`ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip` asset. Its recorded configuration enables
shared libraries and OpenH264 while disabling libx264, libx265, and other GPL-only codecs used by
the earlier internal candidate. The package preserves FFmpeg's `LICENSE.txt`, a `SOURCE_INFO.txt`
record containing the exact download URL and SHA-256, and the generated `BUILD_INFO.txt`. A public
publisher must still provide the exact corresponding source and complete the distribution review;
this notice does not itself make a legal determination.

## OpenH264

The bundled FFmpeg build exposes the OpenH264 encoder. The pinned OpenH264 source revision is
`8b2d28faade10d74d99ac80e199aef664c9c5a3b`.

OpenH264 source license SHA-256: dd5c1c9668512530fa5a96e4c29ac4033d70a7eeb0eed7a42fddb6dd794ebdbb

Copyright (c) 2013, Cisco Systems
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted
provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this list of conditions
  and the following disclaimer.
* Redistributions in binary form must reproduce the above copyright notice, this list of
  conditions and the following disclaimer in the documentation and/or other materials provided
  with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

This source license notice does not determine codec patent rights. In particular, SPLICR does not
claim that Cisco's separate patent terms for Cisco-distributed OpenH264 binaries apply to the
third-party BtbN build; that release review remains open.

Advanced audiogram rendering also includes these Python libraries in the frozen desktop package:

- NumPy, distributed under the BSD 3-Clause license: https://numpy.org/doc/stable/license.html
- Pillow, distributed under the HPND historical permission notice and disclaimer:
  https://github.com/python-pillow/Pillow/blob/main/LICENSE

Other Python and JavaScript dependency licenses remain available from their respective installed
packages and lockfiles in the SPLICR Studio source distribution. Before a public release, preserve
the license/notice files emitted by the frozen package and review this list against the resolved
`uv.lock` and `studio-web/package-lock.json` dependency graphs.
