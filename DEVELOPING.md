English | [简体中文](DEVELOPING_zh.md)

# Development

Use Python 3.11+; lock the Dora CLI to 0.4.1 for the upstream LIBERO example.
`uv sync --frozen --all-extras --group dev` installs public locked dependencies.

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run python -m compileall -q src tests scripts
uv run python scripts/check_publication.py
uv build
```

## Code map

- `contracts.py`: strict configuration, observation and model-action contracts;
  output schema and physical bounds.
- `backend.py`: existing generic service protocol and cancellation. Its terminal
  field is `execution_status`; structured data is `output.json`.
- `actions.py`: world-frame EEF scaling, quaternion feedback, joint limits.
- `runtime.py`: per-observation action credits, queue ownership, bounded executed
  history, lifecycle generations and async inference; transport independent.
- `wire.py`: original public Forge Arrow field codecs, raw RGB/BGR PNG conversion.
- `node.py`: Dora event loop and input drivers. Timer events pump asyncio;
  synchronous model requests must never be added to this loop.

Every reset/instruction change/pause/stop invalidates old generations. A late
result cannot repopulate an executable queue. Histories include actions only after
the next observation acknowledges them. Do not infer joint angles from LIBERO's
legacy EEF state labels or silently fill missing state names with zero.

`observation_v1` needs a producer extension and correlated action rejection. The
legacy fixture is useful for existing LIBERO integration but does not establish
atomic sensor synchronization. Tests must preserve that distinction.

The node emits no default motion after failure. Upstream benchmark has no abort
input; release acceptance must verify interrupted-batch accounting with actual
Dora/PAOS orchestration. No numerical checks establish collision safety.

The source Skill is a deployment template, not an accepted distribution. Preserve
Apache notices when packaging it, generate the PAOS per-file archive manifest,
and verify install/start/describe/run/result/stop in the intended PAOS version.
See [complete design](docs/DESIGN.md) for acceptance requirements.

Change protocol behavior only with semantic tests (e.g. stale reset result,
invalid joint order, one credit per observation, real generic response envelope).
Update English and Chinese README/design/developer documents together. Use a
personal-fork `feature/`, `fix/` or `docs/` branch for public-target PRs.

The example uses shell launchers: Dora 0.4.1 canonicalizes executable paths, so a direct virtualenv Python symlink can lose its virtualenv. Launching the interpreter inside a shell script preserves the intended environment.
