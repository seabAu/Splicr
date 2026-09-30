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

```text
Copyright (c) 2013, Cisco Systems
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice, this
  list of conditions and the following disclaimer in the documentation and/or
  other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

This source license notice does not determine codec patent rights. In particular, SPLICR does not
claim that Cisco's separate patent terms for Cisco-distributed OpenH264 binaries apply to the
third-party BtbN build; that release review remains open.

## libogg

The bundled FFmpeg dependency graph includes libogg at pinned source revision
`06a5e0262cdc28aa4ae6797627a783b5010440f0`.

libogg source license SHA-256: d2ab5758336489da61c12cc5bb757da5339c4ae9001f9bb0562b4370249af814

```text
Copyright (c) 2002, Xiph.org Foundation

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

- Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

- Neither the name of the Xiph.org Foundation nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE FOUNDATION
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## mingw-std-threads

The pinned Windows dependency graph includes mingw-std-threads at source revision
`c931bac289dd431f1dd30fc4a5d1a7be36668073`.

mingw-std-threads source license SHA-256: 86c148320eb0acc26607ed347e0fde9f49a236d0ec5291d36dc6a7e0e1d26b9f

```text
Copyright (c) 2016, Mega Limited
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

```

## libopus

The bundled FFmpeg dependency graph includes libopus at pinned source revision
`503d81b138d76621aae4b12786e90de48aa8db3a`.

libopus source license SHA-256: 01e1167d54a096d123cf6dfbbeb19587278845c6481d2d66d545669846079551

```text
Copyright 2001-2023 Xiph.Org, Skype Limited, Octasic,
                    Jean-Marc Valin, Timothy B. Terriberry,
                    CSIRO, Gregory Maxwell, Mark Borgerding,
                    Erik de Castro Lopo, Mozilla, Amazon

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

- Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

- Neither the name of Internet Society, IETF or IETF Trust, nor the
names of specific contributors, may be used to endorse or promote
products derived from this software without specific prior written
permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Opus is subject to the royalty-free patent licenses which are
specified at:

Xiph.Org Foundation:
https://datatracker.ietf.org/ipr/1524/

Microsoft Corporation:
https://datatracker.ietf.org/ipr/1914/

Broadcom Corporation:
https://datatracker.ietf.org/ipr/1526/
```

libopus supplemental notice SHA-256: 7efb4989e0cd1b256229bdf2f09300c5d14e35db0e7476bfb87fac243498273d

```text
Contributions to the collaboration shall not be considered confidential.

Each contributor represents and warrants that it has the right and
authority to license copyright in its contributions to the collaboration.

Each contributor agrees to license the copyright in the contributions
under the Modified (2-clause or 3-clause) BSD License or the Clear BSD License.

Please see the IPR statements submitted to the IETF for the complete
patent licensing details:

Xiph.Org Foundation:
https://datatracker.ietf.org/ipr/1524/

Microsoft Corporation:
https://datatracker.ietf.org/ipr/1914/

Skype Limited:
https://datatracker.ietf.org/ipr/1602/

Broadcom Corporation:
https://datatracker.ietf.org/ipr/1526/
```

These notices preserve upstream patent references but do not constitute an independent patent
scope or enforceability determination.

## snappy

The bundled FFmpeg dependency graph includes snappy at pinned source revision
`9c28114a38866f6deeaa826db918293bc28ae410`. Its recipe disables tests, benchmarks,
and fuzzing, so the upstream no-testdata notice applies to the installed library.

snappy source license SHA-256: 5221a36a801b981fbdfda7b87db64cff231a3b88223a066c325411b539df796f

```text
Copyright 2011, Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
    * Neither the name of Google Inc. nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## TwoLAME

The bundled FFmpeg dependency graph includes TwoLAME at pinned source revision
`6fced852d4d5cfad58cf9dbe3ea619b08e87d398`. TwoLAME is licensed under
LGPL-2.1-or-later. The exact upstream `COPYING` file from that revision is packaged as
`ffmpeg/TWOLAME-COPYING.txt` with SHA-256
`257a842724705950b07da76ce0e22ffa80ec77b3e9dfc6702522ac342409da0f`.

Advanced audiogram rendering also includes these Python libraries in the frozen desktop package:

- NumPy, distributed under the BSD 3-Clause license: https://numpy.org/doc/stable/license.html
- Pillow, distributed under the HPND historical permission notice and disclaimer:
  https://github.com/python-pillow/Pillow/blob/main/LICENSE

Other Python and JavaScript dependency licenses remain available from their respective installed
packages and lockfiles in the SPLICR Studio source distribution. Before a public release, preserve
the license/notice files emitted by the frozen package and review this list against the resolved
`uv.lock` and `studio-web/package-lock.json` dependency graphs.
