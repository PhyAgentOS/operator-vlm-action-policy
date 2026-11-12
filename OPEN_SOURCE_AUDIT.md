# Publication review

Original code is Apache-2.0 with LICENSE, NOTICE and third-party notices. No model,
benchmark data, media, SDK source, executable or private deployment history is
bundled. Dependencies resolve from public PyPI and are locked in uv.lock.

The Arrow codecs implement public Forge fields without copying SDK source.
Patched Pillow 13 is used directly; unrelated full SDK dependencies are avoided.
CI runs tests, lint, compilation, publication checks, config validation and builds.
It contains no dependency-audit job and performs no real-model evaluation.

Executed local checks:

- Python 3.12 and Python 3.11: 20 tests passed on each after the reset-ordering fix.
- Ruff, compilation, CLI/config validation and actionlint passed.
- Existing generic service ASGI implementation accepted real PNG/schema requests and returned a native EEF command, using a controlled model backend.
- Exact public forge-msgs 1.2.0 JointCommand/JointState/Image interoperability passed. SDK files were isolated for verification and are not distributed.
- Real isolated Dora 0.4.1 dataflow plus the existing generic HTTP service delivered three native EEF actions to a controlled environment. The test exposed and fixed cross-port reset ordering and virtualenv path resolution.
- Source/wheel archives were checked for private content and retained licenses/notices.

Real LIBERO/PAOS acceptance and real-model success rates remain separate from these controlled integration checks.
The source Skill template is not an accepted installed Skill distribution.
