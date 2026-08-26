# Third-party notices for the Windows distribution

The LabelImg Enhanced source code remains available under the MIT license in
`LICENSE`. The bundled Windows application also contains third-party software
under other licenses. In particular:

- PyQt5 is copyright Riverbank Computing Limited and is distributed under the
  GNU General Public License version 3 in this build. The corresponding
  LabelImg Enhanced source, packaging scripts, and build instructions are
  available from the source archive attached automatically to the same GitHub
  tag. The GPLv3 text is included as `COPYING.GPL-3.0`.
- Qt is copyright The Qt Company Ltd. and other contributors. The applicable
  license files from the PyQt5-Qt5 wheel are bundled under
  `third_party_licenses/PyQt5-Qt5`.
- PyQt5-sip, lxml, NumPy, OpenCV, Pillow, comtypes, and their transitive
  components retain their respective upstream copyrights and licenses. The
  license metadata supplied by each direct runtime wheel is bundled under
  `third_party_licenses`.

The exact dependency versions used for a release are recorded by the tagged
source tree and GitHub Actions build log. No code-signing certificate is used;
the installer therefore appears in Windows as published by an unknown
publisher.
