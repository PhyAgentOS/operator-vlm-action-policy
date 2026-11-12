"""Check the public source tree and required project notices."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "README_zh.md",
    "docs/DESIGN.md",
    "docs/DESIGN_zh.md",
    "uv.lock",
]
PRIVATE = re.compile(
    r"gitlab\.ex-ai\.cn|/(?:Users|home)/[A-Za-z0-9_.-]+/|"
    r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{15,}|sk-[A-Za-z0-9_-]{20,})\b"
)


def main():
    missing = [str(p) for p in REQUIRED if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit("Missing publication files: " + ", ".join(missing))
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for name in filter(None, tracked):
        path = ROOT / name
        if path.is_symlink() or path.stat().st_size > 3_000_000:
            raise SystemExit("Unexpected source file: " + name)
        if path.name in {".env", ".llm_config", "config.local.yaml"}:
            raise SystemExit("Private configuration: " + name)
        if PRIVATE.search(path.read_text()):
            raise SystemExit("Private content requires review: " + name)
    print("Public source/notices check passed.")


if __name__ == "__main__":
    main()
