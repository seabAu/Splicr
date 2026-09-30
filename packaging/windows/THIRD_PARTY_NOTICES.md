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

## AMD Advanced Media Framework headers

The bundled FFmpeg dependency graph includes AMD Advanced Media Framework headers at pinned source
revision `6277e353fd625121a8f627b1d0540323ef372a49`. The exact upstream `LICENSE.txt`, including its
standards and patent-rights notice plus MIT terms, is packaged as `ffmpeg/AMF-LICENSE.txt` with
SHA-256 `eb297397aaa455b5668ab67d216b83828466152dab123fa92384c6ec16b74170`.

This preserves AMD's upstream notice but does not constitute an independent patent scope,
royalty, or enforceability determination.

## libffi

The bundled FFmpeg dependency graph includes libffi at pinned source revision
`bc553867367246d140cd156f060bd0409f57f157`.

libffi source license SHA-256: 17b64dc60f3b6897a60f971e288b973f655c2edcdf08b25f3c3dd5549857881c

```text
libffi - Copyright (c) 1996-2026  Anthony Green, Red Hat, Inc and others.
See source files for details.

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
``Software''), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED ``AS IS'', WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## libpng

The bundled FFmpeg dependency graph includes libpng at pinned source revision
`964b4135949703b705fc760fc3fb546b86e5ab47` under `libpng-2.0`. The upstream license appreciates
product acknowledgment but does not require a binary notice; its complete source notice remains in
the corresponding-source archive at SHA-256
`bdb0a645ea18c60507d0368379b1ac5474b92255fcc2d115e07486a7672ba526`.

## OpenJPEG

The bundled FFmpeg dependency graph includes OpenJPEG at pinned source revision
`8314119b067c0fc77834731168daaebd379fdb12`. Its exact BSD-2-Clause license and patent-rights caveat
are packaged as `ffmpeg/OPENJPEG-LICENSE.txt` with SHA-256
`a6af136f3e15038a666b61f376612a07d9a4e48cb7c01adbf3e33b3f14ab49b6`.

This preserves the upstream patent-rights caveat but does not constitute an independent patent
scope or enforceability determination.

## dav1d

The bundled FFmpeg dependency graph statically incorporates dav1d at pinned source revision
`9711965b60bb692ae24004659acf61f5c7d9ed61`. Its exact BSD-2-Clause terms are packaged as
`ffmpeg/DAV1D-COPYING.txt` with SHA-256
`dd92c3c2247c5651606fc23a5e2d6a1ebc5ace9a3e49cbde0e12f05ad1cb1ee5`.

The accompanying Alliance for Open Media Patent License 1.0 requires reproduction with binary
implementations. Its exact pinned text is packaged as `ffmpeg/DAV1D-PATENTS.txt` with SHA-256
`335eca574598bf4ca181b12f708d6669e5a5e78c8e1513e5b35fa1f03901484b`.
Preserving that upstream patent license is not an independent patent scope, validity, or
enforceability determination.

## FriBidi

The bundled FFmpeg dependency graph statically incorporates FriBidi at pinned source revision
`4c914a92e94a9fe4f30ae83a1130099841566448` under LGPL-2.1-or-later. Its exact upstream `COPYING`
file is packaged as `ffmpeg/FRIBIDI-COPYING.txt` with SHA-256
`20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95`.

Advanced audiogram rendering also includes these Python libraries in the frozen desktop package:

- NumPy, distributed under the BSD 3-Clause license: https://numpy.org/doc/stable/license.html
- Pillow, distributed under the HPND historical permission notice and disclaimer:
  https://github.com/python-pillow/Pillow/blob/main/LICENSE

Other Python and JavaScript dependency licenses remain available from their respective installed
packages and lockfiles in the SPLICR Studio source distribution. Before a public release, preserve
the license/notice files emitted by the frozen package and review this list against the resolved
`uv.lock` and `studio-web/package-lock.json` dependency graphs.
