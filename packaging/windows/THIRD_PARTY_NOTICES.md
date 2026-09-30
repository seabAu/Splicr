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

## NVIDIA codec headers (ffnvcodec)

The bundled FFmpeg 9 build uses the primary nv-codec-headers set at pinned revision
`eddcea9e27f6b772057c9b3f87de2cc1737faffc`. Upstream provides no standalone license file; each
installed header carries an MIT notice. The package therefore preserves all five exact pinned
primary headers and their notices:

- `ffmpeg/FFNVCODEC-dynlink_cuda.h.txt` — SHA-256 `c970d5817120ea481ba29b9c603bdc9a386985d9fc98a47f6588030dcdba87c1`
- `ffmpeg/FFNVCODEC-dynlink_cuviddec.h.txt` — SHA-256 `0d9f490e8699a2e000904275d9e380e7ee9945e5717b95f920358013153c6377`
- `ffmpeg/FFNVCODEC-dynlink_loader.h.txt` — SHA-256 `144c0927b6009d5af34a3a7335b0c8c337eec287b4846dd3ac8519c06956662a`
- `ffmpeg/FFNVCODEC-dynlink_nvcuvid.h.txt` — SHA-256 `c1290075d5d881e98c8f14dc5a23953a792f56971b172cf84ee0bc7aab6d1aab`
- `ffmpeg/FFNVCODEC-nvEncodeAPI.h.txt` — SHA-256 `8776fddcb8febc6aec4d73989b1f21831eb30306bc583da55b4bf0c14a1dc228`

The recipe's sdk/13.0 and sdk/11.1 compatibility branches are selected only for older FFmpeg
versions and are not installed or compiled into this FFmpeg 9 payload.

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

## Game Music Emu

The bundled FFmpeg dependency graph statically incorporates Game Music Emu at pinned revision
`f68963b1de0633149b05732113d3c3113c6f63a1` under LGPL-2.1-or-later. Its exact upstream license is
packaged as `ffmpeg/GME-LICENSE.txt` with SHA-256
`d2efc89fbb7533572a472d34e07964951810a3a4f8d3159ecc2dcaa1452c5c26`.

The default build also compiles the bundled emu2413 implementation. Its exact MIT notice is
packaged as `ffmpeg/GME-EMU2413-LICENSE.txt` with SHA-256
`8fb093f26ed0d78c8ca033bbec7063ac5b34c5d2475e6bd121d03ccfaaf2355f`. The alternative GPLv2
MAME YM2612 implementation is not selected by the pinned recipe.

## GNU MP Library

The bundled FFmpeg dependency graph statically incorporates GMP at pinned revision
`763b40df71c0f4d5f5d7b33dc55038c8c9377ecf` under its LGPL-3.0-or-later option. The exact LGPL
supplement and incorporated GPLv3 terms are packaged as `ffmpeg/GMP-COPYING.LESSERv3.txt`
(SHA-256 `a853c2ffec17057872340eee242ae4d96cbf2b520ae27d903e1b2fef1a5f9d1c`) and
`ffmpeg/GMP-COPYINGv3.txt` (SHA-256
`e6037104443f9a7829b2aa7c5370d0789a7bda3ca65a0b904cdc0c2e285d9195`). GMP's alternative
GPL-2.0-or-later text is preserved for completeness as `ffmpeg/GMP-COPYINGv2.txt` with SHA-256
`8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643`.

## Kvazaar

The bundled FFmpeg dependency graph statically incorporates Kvazaar at pinned revision
`2b06691bb5844404c0e703f12a5d7b0fee914ec7`. Its exact BSD-3-Clause license is packaged as
`ffmpeg/KVAZAAR-LICENSE.txt` with SHA-256
`3c1dc3d7f8a3d08c14f4fbe9942f45764d8a21a3296e8d83446f33fd65f21c38`.

Preserving this notice does not constitute an independent HEVC patent scope, royalty, or
enforceability determination.

## LCEVCdec

The bundled FFmpeg dependency graph statically incorporates LCEVCdec at pinned revision
`17804ac54db8fbb42717f3275b1e73f3c0b067d3` under BSD-3-Clause-Clear. Its exact license is
packaged as `ffmpeg/LCEVCDEC-LICENSE.md` with SHA-256
`14358b0ecf6e7036c211c10f0f25563c94483dee7b8c7c954e09e10f3771d0af`.

Upstream's additional licensing information explicitly states that no patent licenses are granted
and requires the information to be maintained. That exact file is packaged as
`ffmpeg/LCEVCDEC-COPYING.txt` with SHA-256
`3afa5369b4fb44e18280b6e0e275971f78bc6eaf5f53553f41f2483fd8b1267e`. Preserving these terms is
not an independent patent scope, validity, royalty, or enforceability determination.

## libvpx

The bundled FFmpeg dependency graph statically incorporates libvpx at pinned revision
`5e680f30801d03c21078f8c4b772464752516211`. Its exact BSD-3-Clause license is packaged as
`ffmpeg/LIBVPX-LICENSE.txt` with SHA-256
`8267348d5af1262c11d1a08de2f5afc77457755f1ac658627dd9acf71011d615`.

The x86_64 build also incorporates the x86inc assembly include under ISC; its exact notice is
packaged as `ffmpeg/LIBVPX-X86INC-LICENSE.txt` with SHA-256
`719d8fa235f2068e0ae6d6a7dceb0a7720d7840f0f0ebed29957989e6ded3cd8`. The accompanying WebM
additional patent grant is packaged as `ffmpeg/LIBVPX-PATENTS.txt` with SHA-256
`cc3273e0694ea5896145e0677699b53471b03ea43021ddc50e7923fbb9f5023c`.

## libwebp

The bundled FFmpeg dependency graph statically incorporates libwebp at pinned revision
`5c168cd23b1872969c38e34b01b04dcf29849288`. Its exact BSD-3-Clause terms are packaged as
`ffmpeg/LIBWEBP-COPYING.txt` with SHA-256
`5aec868f669e384a22372a4e8a1a6cd7d44c64cd451f960ca69cc170d1e13acf`. The accompanying WebM
additional patent grant is packaged as `ffmpeg/LIBWEBP-PATENTS.txt` with SHA-256
`cc3273e0694ea5896145e0677699b53471b03ea43021ddc50e7923fbb9f5023c`.

Preserving the libvpx and libwebp patent-grant texts is not an independent patent scope,
validity, royalty, or enforceability determination.

## ZeroMQ

The bundled FFmpeg dependency graph statically incorporates libzmq at pinned revision
`46493370217ac135246617fa2f6ac819d8b61bfc` under MPL-2.0. Its exact license is packaged as
`ffmpeg/LIBZMQ-LICENSE.txt` with SHA-256
`1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5`.

The Windows recipe selects the epoll compatibility path and compiles wepoll under BSD-2-Clause.
Its exact notice is packaged as `ffmpeg/LIBZMQ-WEPOLL-LICENSE.txt` with SHA-256
`3e56262d2c0e9492f113089916ed624e98f88b31dfd6acae24ede59cdfda5a69`. Availability of the
MPL-covered source remains part of the corresponding-source publication gate.

## OpenCORE AMR

The bundled FFmpeg dependency graph statically incorporates OpenCORE AMR-NB and AMR-WB at pinned
revision `7dba8c32238418ce0b316a852b2224df586ca896` under Apache-2.0. The complete license and upstream
attribution notice are packaged as `ffmpeg/OPENCORE-AMR-LICENSE.txt` (SHA-256
`8b3f1762349248d444ab9acbafe73941254e36e1064954da56bb9ddbd5873ddb`) and
`ffmpeg/OPENCORE-AMR-NOTICE.txt` (SHA-256
`d106802b5e406073c1d10fbe9f638234c6973ebce37df71773179642085eb489`).

Upstream explicitly states that the source grant conveys no patent rights. That exact disclaimer is
packaged as `ffmpeg/OPENCORE-AMR-PATENT-DISCLAIMER.txt` with SHA-256
`f91a72705d38de34a9749c214a4cbc6ffa1da753b34b2cd11f3d6798f24ae59f`. Preserving these notices
does not constitute an independent AMR patent scope, validity, royalty, or enforceability
determination.

## libudfread

The bundled FFmpeg dependency graph statically incorporates libudfread at pinned revision
`b0bc6957e7e07d5f35391f210596d9eb71cffdd9` under LGPL-2.1-or-later. Its exact LGPL-2.1 text is
packaged as `ffmpeg/LIBUDFREAD-COPYING.txt` with SHA-256
`dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551`. Corresponding source and
relink materials remain part of the public-release gate. The manifest uses immutable mirror commit
`9e1e9865ffc261016ac164c0e00602c0f6f4fda9` because Code.Videolan's raw endpoint presents an
automated-client challenge; the packaged bytes exactly match the reviewed source revision above.

## oneVPL

The bundled FFmpeg dependency graph statically incorporates the oneVPL dispatcher at pinned
revision `674d015bcb294bc39fa276e99a652ea045423e82`. Its exact MIT license is packaged as
`ffmpeg/ONEVPL-LICENSE.txt` with SHA-256
`bf1cfac2e2792b6e1e995ce103d70796aecaf2ec7e4c5fe5474f7acec7b4a677`. The recipe disables tests
and example builds and removes staged example content, so their separate candidate files are not
part of the binary payload.

## PCRE2

The bundled dependency graph statically incorporates the 8-bit Unicode PCRE2 library at pinned
revision `09eb19dc1102b34e7557408f33318364cb97d2b0`. Its substantive BSD-3-Clause terms with the
PCRE2 binary-package exception are packaged as `ffmpeg/PCRE2-LICENCE.md` with SHA-256
`197d8a73ffee0d6b09adba2f9c677b5f5aede24edf89258a68e48248d010d811`.

Upstream's short `COPYING` pointer is preserved exactly as `ffmpeg/PCRE2-COPYING.txt` with SHA-256
`99272c55f3dcfa07a8a7e15a5c1a33096e4727de74241d65fa049fccfdd59507`. The recipe uses Autotools,
not the separately licensed CMake scripts, and does not enable JIT; therefore neither those scripts
nor SLJIT are compiled into the package.

## pixman

The bundled FFmpeg dependency graph statically incorporates pixman at pinned revision
`96c04d1b87934dc4b9396197a2dff737698ab310`. Its exact MIT notice is packaged as
`ffmpeg/PIXMAN-COPYING.txt` with SHA-256
`fac9270f0987b96ff4533fca3548c633e02083cbba4a0172a3b149b2e4019793`. The recipe disables tests,
demos, GTK, libpng, and OpenMP support. The manifest uses immutable mirror commit
`85467ec308f8621a5410c007491797b7b1847601` because GitLab's raw endpoint presents an automated-
client challenge; the packaged bytes exactly match the reviewed source revision above.

## Little CMS

The bundled FFmpeg dependency graph statically incorporates Little CMS at pinned revision
`a0b0d7a69b13b461bdbd9cff9f7f1d59ccd1858c`. Its exact MIT license is packaged as
`ffmpeg/LCMS2-LICENSE.txt` with SHA-256
`6dbd60437f8ef91d8de1f08ad75882547fd4931bfcc3566a0735f28db1484d31`.

The upstream recipe also builds GPL-3.0 fast-float and threaded plugins as separate static archives.
FFmpeg does not reference either plugin entry point, ordinary static linking does not pull their
objects into the media DLLs, and the archives themselves are not shipped. The disabled utilities
also exclude the separately licensed jpgicc source.

## OpenAL Soft

The bundled FFmpeg dependency graph statically incorporates OpenAL Soft at pinned revision
`c89b8cf7bba4822f230c69f0a6696a52e5322dca`. Compiled sources select GNU Library GPL version 2 or
later; the exact version-2 text is packaged as `ffmpeg/OPENAL-SOFT-COPYING.txt` with SHA-256
`d808ce217e5b611854da622b57ec29fe545584c48bc5352fae72a4b6e5074a15`.

OpenAL Soft also compiles several bundled components whose exact terms are packaged beside it:

- modified PFFFT/UCAR BSD-3-Clause notice: `ffmpeg/OPENAL-SOFT-PFFFT-LICENSE.txt`, SHA-256
  `64056328b3e7bc104e24ef96accc1a7abead156f0c02d1b87c97e3f3a28030de`;
- Apache-2.0 common-header terms: `ffmpeg/OPENAL-SOFT-APACHE-2.0.txt`, SHA-256
  `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`;
- BSD-3-Clause mixer/effect contributions: `ffmpeg/OPENAL-SOFT-BSD-3-CLAUSE.txt`, SHA-256
  `b5a08cf98996dd83aa906a72c163600f6cb17a65ce546a553815a1267abd43ff`;
- bundled fmt MIT terms and optional binary-object exception:
  `ffmpeg/OPENAL-SOFT-FMT-LICENSE.txt`, SHA-256
  `07580f2a3b35709ce703d523f447b242f6dfec7582a8c0df102c7fa2849375f8`; and
- bundled Microsoft GSL MIT terms: `ffmpeg/OPENAL-SOFT-GSL-LICENSE.txt`, SHA-256
  `4c21dc82a1c7186ea754fd59d504c00947953a3401fe8e24eaa44109ef8e2555`.

## SoX Resampler

The bundled FFmpeg dependency graph statically incorporates SoX Resampler at pinned revision
`945b592b70470e29f917f4de89b4281fbbd540c0` under LGPL-2.1-or-later. Its exact LGPL-2.1 text is
packaged as `ffmpeg/SOXR-COPYING.LGPL.txt` with SHA-256
`f2f118b9029ec1871b953639ecc46651b2fc7b62e295e6cf3ef2ac4c9a058b33`, and its exact licensing
declaration is packaged as `ffmpeg/SOXR-LICENCE.txt` with SHA-256
`dc98676341fdcd29d9f279c9679d6a75288785b174ded8d1b2e316c366166135`.

The enabled SIMD resampler compiles SoXR's embedded PFFFT implementation. Its source file carries
the required UCAR/PFFFT BSD-3-Clause notice and is preserved exactly as
`ffmpeg/SOXR-PFFFT-NOTICE.c` with SHA-256
`2949635f6107983832a7fcb6b7a539b43022fdd64d6cc01904ff5f7d792bb4c4`. The manifest uses the
immutable GitHub mirror at the identical upstream commit because the recipe's canonical remote is
SourceForge; the packaged bytes exactly match the collected source archive. The GPL-2.0 LSR test
suite is excluded because the recipe disables tests.

## uavs3d

The bundled FFmpeg dependency graph statically incorporates the 10-bit uavs3d decoder at pinned
revision `0e20d2c291853f196c68922a264bcd8471d75b68`. Its exact BSD-3-Clause notice is packaged as
`ffmpeg/UAVS3D-COPYING.txt` with SHA-256
`5a8dcb7da222df8a81b6e334000f859248196335e2d28e1db9f3c552827d7cdf`. This source-license record
does not assert patent clearance for AVS3; patent review remains a separate public-release gate.

Advanced audiogram rendering also includes these Python libraries in the frozen desktop package:

- NumPy, distributed under the BSD 3-Clause license: https://numpy.org/doc/stable/license.html
- Pillow, distributed under the HPND historical permission notice and disclaimer:
  https://github.com/python-pillow/Pillow/blob/main/LICENSE

Other Python and JavaScript dependency licenses remain available from their respective installed
packages and lockfiles in the SPLICR Studio source distribution. Before a public release, preserve
the license/notice files emitted by the frozen package and review this list against the resolved
`uv.lock` and `studio-web/package-lock.json` dependency graphs.
