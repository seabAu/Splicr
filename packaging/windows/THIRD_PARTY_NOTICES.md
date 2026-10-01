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

The current Windows package uses the checksum-pinned BtbN
`ffmpeg-n9.0.2-3-ga5923073bf-win64-lgpl-shared-9.0.zip` asset. That filename is the upstream asset
variant, not an effective-license determination. Recipe and binary inspection found that enabled
Chromaprint is built with static FFTW3: Chromaprint publishes `-lfftw3` in `Libs.private`, FFmpeg
uses static pkg-config dependency resolution, `avformat-63.dll` contains FFTW 3.3.11 markers, and
no separate FFTW DLL is shipped. FFTW is GPL-2.0-or-later, so the bundled media DLLs must be treated
as GPL-covered despite the upstream `lgpl-shared` asset label. The package preserves FFmpeg's
`LICENSE.txt`, a `SOURCE_INFO.txt` record containing the exact download URL, SHA-256, upstream
variant, and effective-license warning, plus the generated `BUILD_INFO.txt`. Public distribution
remains blocked until the publisher deliberately satisfies the applicable GPL corresponding-source
and notice obligations or replaces this asset with a verified non-GPL build. This notice is an
engineering record, not legal advice.

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

## Brotli

The bundled FFmpeg dependency graph statically incorporates Brotli at pinned revision
`a3abcbee0d945e51dddeec81e647ffe0cde182c2` through JPEG XL. Its exact MIT notice is packaged as
`ffmpeg/BROTLI-LICENSE.txt` with SHA-256
`3d180008e36922a4e8daec11c34c7af264fed5962d07924aea928c38e8663c94`.

## JPEG XL and Highway

The bundled FFmpeg dependency graph statically incorporates JPEG XL at pinned revision
`b87738951c1254cd8cccaa6d47712ba735da56d8`. Its exact BSD-3-Clause notice is packaged as
`ffmpeg/LIBJXL-LICENSE.txt` with SHA-256
`8405932022a556380c2d8c272eff154a923feb197233f348ce5f7334fb0a5ede`. The implementation's exact
additional Google patent grant is packaged as `ffmpeg/LIBJXL-PATENTS.txt` with SHA-256
`91915f8ae056a68a3c5bdf05d9f6f78bb6903e27a8ca3a8434c9e4ac87300575`; preserving it does not
assert independent JPEG XL patent clearance.

The recipe fetches and compiles Highway submodule
`457c891775a7397bdb0376bb1031e6e027af1c48`. Exact Apache-2.0 and BSD-3-Clause texts are packaged as
`ffmpeg/HIGHWAY-APACHE-2.0.txt` (SHA-256
`43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1`) and
`ffmpeg/HIGHWAY-BSD-3-CLAUSE.txt` (SHA-256
`d25e82e26acd42ca3ccc9993622631163425b869b9e16284226d534cff6470f2`). JPEG XL's disabled tools,
tests, examples, and benchmarks exclude the APNG extras, HEVC reference configuration, and Debian
packaging candidates.

## Mbed TLS and TF-PSA-Crypto

The bundled FFmpeg dependency graph statically incorporates Mbed TLS at pinned release tag
`v4.2.0` under its offered Apache-2.0 or GPL-2.0-or-later terms. The exact dual-license file is
packaged as `ffmpeg/MBEDTLS-LICENSE.txt` with SHA-256
`9b405ef4c89342f5eae1dd828882f931747f71001cfba7d114801039b52ad09b`.

Mbed TLS compiles TF-PSA-Crypto submodule `73c5da561c8e5253db7b1fb440eda86fde8d8024`; its exact
dual-license file is packaged as `ffmpeg/TF-PSA-CRYPTO-LICENSE.txt` with SHA-256
`da8c58f05f135a9d15e9ffad4ecf854cfcc1f014c8abfd75ba05f62630ccc118`. The two framework
submodules supply build-time generators only and are not installed or linked. Experimental
mldsa-native support is disabled in the shipped configuration, including its custom-backend example.

## librist

The bundled FFmpeg dependency graph statically incorporates librist at pinned revision
`4f45ef8f78983892d52ccd52d9f675435b23738f`. Its exact BSD-2-Clause notice is packaged as
`ffmpeg/LIBRIST-COPYING.txt` with SHA-256
`b9841591a3452ee30033d8e3586c7b1244a0b2fc1dc6cb04576957c313cb2792`. The recipe links the
separately reviewed external Mbed TLS build and explicitly disables librist's vendored copy.

## LV2 and Lilv stack

FFmpeg's enabled LV2 support statically links the pinned Lilv dependency chain. Exact ISC notices
are packaged for LV2 (`ffmpeg/LV2-COPYING.txt`, SHA-256
`1e6bb175e193608b767ff25a4ed68b82c4db599491cf0d2694435cf60e9a4841`), Serd
(`ffmpeg/SERD-COPYING.txt`, `ae223adebe7cc1ee0716e0f926d1ecc8e42c6e4da7e1d7418c9c07fae244bbde`),
Zix (`ffmpeg/ZIX-COPYING.txt`, `1314cc14fb947491491c517c533ac7de4f6798585f922a472358082c25ac1881`),
Sord (`ffmpeg/SORD-COPYING.txt`, `ae223adebe7cc1ee0716e0f926d1ecc8e42c6e4da7e1d7418c9c07fae244bbde`),
Sratom (`ffmpeg/SRATOM-COPYING.txt`, `1d968c655ecad113e128dbf4d4deabd9e30b931b42943b6a681c9cf11d7da5d4`),
and Lilv (`ffmpeg/LILV-COPYING.txt`,
`ae223adebe7cc1ee0716e0f926d1ecc8e42c6e4da7e1d7418c9c07fae244bbde`).
Zix's current REUSE notice contains a newer copyright range than its top-level notice, so
`ffmpeg/ZIX-ISC.txt` is also packaged with SHA-256
`010c7513fdccf856edda08d42d2c46ae393e67b3acf97f9e428980cca2f94b7d`.

The recipes disable documentation, tools, tests, benchmarks, and Python bindings as applicable.
LV2 schema and manifest assets plus Meson/configuration metadata exist only in the intermediate
build prefix and are not linked or copied into the Windows package. The source inventory resolves
only safe in-archive license symlinks and rejects absolute, escaping, cyclic, ambiguous, or
over-deep links.

## Chromaprint and FFTW3

The bundled FFmpeg dependency graph statically incorporates Chromaprint at pinned revision
`aed8eba2202dd9d7b3b0a56c77904cc805490d72`. Its exact combined LGPL-2.1-or-later and MIT license,
including the external-FFT warning, is packaged as `ffmpeg/CHROMAPRINT-LICENSE.md` with SHA-256
`562cfe59627e0c4e8e3b066f3ff2e9736f83811ffe4c6c2c7796595aa7595ebd`.

The recipe selects `FFT_LIB=fftw3`; static dependency resolution incorporates FFTW3 at pinned
revision `93ed4c786934aec9946f8dda4b4e3eb08f8be41c` into the media DLLs. FFTW's exact
GPL-2.0-or-later text is packaged as `ffmpeg/FFTW-COPYING.txt` with SHA-256
`231f7edcc7352d7734a96eef0b8030f77982678c516876fcb81e25b32d68564c`, and its exact source
copyright/licensing notice is packaged as `ffmpeg/FFTW-COPYRIGHT.txt` with SHA-256
`8a74b35d541d93fdf58a22a3d3baa48ae3edbf6d715edfeb6457c21968ae43ac`. Chromaprint tests are
disabled, and the selected FFTW backend excludes vendored KissFFT.

## LAME

The bundled FFmpeg dependency graph statically incorporates LAME at pinned SVN revision `6835`
under LGPL-2.0-or-later. Its exact GNU Library GPL version 2 text is packaged as
`ffmpeg/LAME-COPYING.txt` with SHA-256
`e64f9c5a18f56828c10a575df13ade641aa3af4512a7afe6c411256943b57aaf`. LAME's accompanying
binary-distribution guidance and acknowledgement request is packaged as
`ffmpeg/LAME-LICENSE.txt` with SHA-256
`5c1f8d44f1eacbea3e1c31ff6ee11a4e1690ccbed4ee4af16de3b6eb61dc69a8`.

## Theora

The bundled FFmpeg dependency graph statically incorporates Theora at pinned revision
`28fd5ec77f0ad0e07a371cef1047828116f6bd8a`. Its exact BSD-3-Clause notice is packaged as
`ffmpeg/THEORA-COPYING.txt` with SHA-256
`8417fad7da775735564e209484a2e011e0fa201e94f01fdbee6e4977e478e6fc`. The accompanying On2 VP3
patent non-assertion statement is preserved as `ffmpeg/THEORA-LICENSE.txt` with SHA-256
`2c902950c73a63cd285dc0c36573de9c5fefe66d49312949c51d941f33e92932`; preserving it does not
assert independent patent clearance.

## Vorbis

The bundled FFmpeg dependency graph statically incorporates Vorbis at pinned revision
`1b75110b5a2754ba1931d82dd83cb822b266a21d`. Its exact BSD-3-Clause notice is packaged as
`ffmpeg/VORBIS-COPYING.txt` with SHA-256
`ec1815db59fcd302846df949d7424876cb2e2dc5ed1606c5fb0b36787b1cf43a`.

## libxml2

The bundled FFmpeg dependency graph statically incorporates libxml2 at pinned revision
`91586dc6742ab335682235120363f6e126eea5e2`. Its exact MIT notice is packaged as
`ffmpeg/LIBXML2-Copyright.txt` with SHA-256
`5d4873884a890122a4b9b20ad56ac6f7da1d796a5bfcf04a427970ac96217626`. HTML-tokenizer notices
found by the source inventory belong only to disabled test fixtures.

## XZ Utils / liblzma

FFmpeg statically incorporates liblzma from pinned XZ revision
`3b1efb04d17c3a9ef7f473d73af13f1531428ffe` under 0BSD. The exact source review records both the
upstream license map and operative `COPYING.0BSD`; 0BSD imposes no binary-notice requirement. GPL
and LGPL files in the archive apply to build-system material, fallbacks, and command-line utilities
that are not incorporated into the SPLICR package.

## ZVBI

The bundled FFmpeg dependency graph statically incorporates libzvbi at pinned revision
`d3a5ee9f2b047bf16cd1ee5ccf6ec05ee75409d0`. Enabled library objects include GPL-2.0-only
`packet-830.c` and `pdc.c` alongside LGPL- and MIT-covered source. The comprehensive exact upstream
terms are packaged as `ffmpeg/ZVBI-COPYING.md` with SHA-256
`6d679539253897582d38fcd1eabfa670c01c0ece73d8cd3dc97869fcf723f106`. This independently makes the
distributed media-library combination GPL-covered; the upstream asset's `lgpl-shared` label is not
a license determination.

## SDL2 exclusion

The upstream recipe builds SDL2 only for `ffplay.exe`. SPLICR copies `ffmpeg.exe`, `ffprobe.exe`,
and the shared FFmpeg libraries, none of which contains SDL markers, so SDL2 and its embedded HIDAPI
and yuv2rgb code are recorded as build-only/not-shipped rather than as distributed components.

## GNU libiconv

The bundled FFmpeg dependency graph statically incorporates GNU libiconv at pinned revision
`1df3087ba8110c7f3ed3eb5f8869b814dbbe00b0` under LGPL-2.1-or-later. The exact LGPL-2.1 text is
packaged as `ffmpeg/LIBICONV-COPYING.LIB.txt` with SHA-256
`20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95`. Exact compiled-source
notices are also preserved as `ffmpeg/LIBICONV-iconv.c`, `ffmpeg/LIBICONV-compat.c`, and
`ffmpeg/LIBICONV-localcharset.c`, with SHA-256 values
`7c563fb5e731f7ba9fcd794d1e953cbb989030da8c769c214d8af8554a725fa1`,
`1798743831f704fdae30190d8700c43d2849798be2cb30b4b8fc5587f306cd52`, and
`c76245773a28b361208591a5d0fdeb0d8e408a230feea647bf960ab702a8035b`. The gnulib runtime is linked
only into the unshipped `iconv` command-line program; its GPL and documentation candidates are
recorded as build-only rather than part of the SPLICR runtime.

## Fontconfig and Unicode data

The bundled font stack statically incorporates Fontconfig at pinned revision
`bd8f7b597de96761750d0365abb49b19d2f8d5c3`. Its exact HPND-sell-variant project notice and embedded
attributions are packaged as `ffmpeg/FONTCONFIG-COPYING.txt` with SHA-256
`51a51aa9823704fd90bccc616cdd17ebabb5b2b3e9cbde886ca02c7002288067`. Fontconfig's generated
case-folding tables copy Unicode data whose source notice points to the separate Unicode License v3.
That exact companion license is packaged as `ffmpeg/UNICODE-3.0.txt` with SHA-256
`e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96` and is fail-closed bound to
the reviewed Fontconfig candidate through `ffmpeg-packaged-license-companions.tsv`.

## HarfBuzz

HarfBuzz at pinned revision `b3bab62307017934dd7f532c52a696fefb12b3ad` is statically
incorporated into the shaping stack. Its exact MIT-Modern-Variant terms are packaged as
`ffmpeg/HARFBUZZ-COPYING.txt` with SHA-256
`ba8f810f2455c2f08e2d56bb49b72f37fcf68f1f4fade38977cfd7372050ad64`. The exact MIT notice for
Microsoft USE data that feeds generated runtime shaping tables is packaged as
`ffmpeg/HARFBUZZ-MS-USE-COPYING.txt` with SHA-256
`c2cfccb812fe482101a8f04597dfc5a9991a6b2748266c47ac91b6a5aae15383`. Test, benchmark, and
performance-text notices apply only to disabled targets.

## FreeType

The final HarfBuzz-enabled FreeType build at pinned revision
`d333439633039de426f943f28a2926c7f97b5ae5` overwrites the earlier bootstrap archive before FFmpeg
links. The exact license router and selected FreeType License are packaged as
`ffmpeg/FREETYPE-LICENSE.TXT` and `ffmpeg/FREETYPE-FTL.TXT`, with SHA-256 values
`bd36c8b474855fa294c2ec5c184544478ef3720aad37d65a6296a4f264fd2d3b` and
`5a5ee54c5001bbad1cdc1a57cc3dd4c42199b2da09d39c7ee41fab002d02967f`. This product uses software
based in part on the work of the FreeType Team. Exact notices for the enabled BDF and PCF modules
are packaged as `ffmpeg/FREETYPE-BDF-README.txt`, `ffmpeg/FREETYPE-PCF-README.txt`, and
`ffmpeg/FREETYPE-PCFUTIL.c`, with SHA-256 values
`7984455e7e5a9faba3797c8bf095fbe10cc846316b7320aff8c58402e22b82fe`,
`18d9782898d9eac04476e2f744678137b2a889689ed3e923e052fc396a86f86b`, and
`85f96e9fd54d9ef69eb39e9dc1d085b6e071921cc012da0f503c75d4b8bf336b`. The build selects the
earlier external static zlib through `zlib.pc`, so FreeType's bundled zlib fallback is not compiled.

## ARIB B24 caption decoding

The bundled FFmpeg dependency graph statically incorporates aribb24 at pinned revision
`5e9be272f96e00f15a2f3c5f8ba7e124862aec38`. Compiled source headers grant
LGPL-2.1-or-later; the upstream later-version license text is packaged as
`ffmpeg/ARIBB24-COPYING.txt` with SHA-256
`da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768`. The exact notice from the
main compiled translation unit is preserved as `ffmpeg/ARIBB24-aribb24.c` with SHA-256
`c86328d3b911524c059cdff3419c37a3427000b66ffd873d14d763ae613003ba`.

## ARIB caption rendering

libaribcaption at pinned revision `c64c23b8905ba514b87c9789269e9f66f949ffe0` is statically
incorporated with FreeType rendering enabled. Its exact MIT notice is packaged as
`ffmpeg/LIBARIBCAPTION-LICENSE.txt` with SHA-256
`5149f1ce4fe89190d86bfb440456701a3a7406fc2b19ef0d8b57661f62b32c04`. Exact ISC-style notices
from the compiled aligned-allocation and OpenType GSUB implementations are packaged as
`ffmpeg/LIBARIBCAPTION-aligned_alloc.cpp` and `ffmpeg/LIBARIBCAPTION-open_type_gsub.cpp`, with
SHA-256 values `391e76fb12525170fa6b4c097162825d3dc563d36587b5eb543d98e8c4a0f697` and
`54ef69e6a795b15b6dccf41f1d33cfc7bc699ba6880abf80053c2e280060df95`. The bundled MD5 fallback
is excluded because the recipe forces OpenSSL support.

## libass subtitle rendering

libass at pinned revision `f61db567e6593df3470e91594bcd4ad2d0473aff` is statically incorporated
with DirectWrite and x86 NASM enabled. Its exact ISC project notice is packaged as
`ffmpeg/LIBASS-COPYING.txt` with SHA-256
`f7e30699d02798351e7f839e3d3bfeb29ce65e44efa7735c225464c4fd7dfe9c`. Exact notices from the
compiled string-to-double and x86 assembly support are packaged as `ffmpeg/LIBASS-ass_strtod.c`
and `ffmpeg/LIBASS-x86inc.asm`, with SHA-256 values
`9b411d6e55b4595d4ef414bebef188a97b41358967b12c3692ee5caccb484991` and
`14d75eaebe68c92890f5f03ce6ebdf4b8b15f2ccf0a8061c2f8459715d960b26`. The included DirectWrite
compatibility header is public domain and wyhash is Unlicense; neither requires a binary notice.
The AArch64 assembly candidate is not part of this Windows x64 build.

## libbluray

libbluray at pinned revision `a24f4fad4d62893de647abc8671397747b2359dd` is statically incorporated
under LGPL-2.1-or-later. Its exact LGPL-2.1 text is packaged as
`ffmpeg/LIBBLURAY-COPYING.txt` with SHA-256
`b3aa400aca6d2ba1f0bd03bd98d03d1fe7489a3bbb26969d72016360af8a5c9d`. BD-J, tools,
devtools, examples, and documentation are disabled, so the Java ASM and getopt fallback notices
identified by the source inventory do not describe code in the packaged runtime.

## OpenSSL

OpenSSL `3.6.4` is statically incorporated into the bundled media libraries under Apache-2.0. The
exact upstream license is packaged as `ffmpeg/OPENSSL-LICENSE.txt` with SHA-256
`7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a`. The pinned
`avformat-63.dll` contains the exact OpenSSL 3.6.4 marker and the pinned media-tool directory carries
no separate SSL or crypto DLL. The source collector recursively archives OpenSSL's
cloudflare-quiche submodule, but the recipe builds only OpenSSL's `build_sw` target; quiche and its
nested BoringSSL dependency are not compiled into the SPLICR runtime.

Advanced audiogram rendering also includes these Python libraries in the frozen desktop package:

- NumPy, distributed under the BSD 3-Clause license: https://numpy.org/doc/stable/license.html
- Pillow, distributed under the HPND historical permission notice and disclaimer:
  https://github.com/python-pillow/Pillow/blob/main/LICENSE

Other Python and JavaScript dependency licenses remain available from their respective installed
packages and lockfiles in the SPLICR Studio source distribution. Before a public release, preserve
the license/notice files emitted by the frozen package and review this list against the resolved
`uv.lock` and `studio-web/package-lock.json` dependency graphs.
