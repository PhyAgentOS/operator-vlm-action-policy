"""Validate the PRM directory_tar_gz layout without extracting the archive."""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath


def verify(path: str) -> dict:
    archive = Path(path)
    name = "operator-vlm-action-policy"
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) > 50000:
            raise ValueError("PRM archive entry limit exceeded")
        seen = set()
        links = {}
        total_size = 0
        entry = None
        for item in members:
            relative = PurePosixPath(item.name)
            if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                    or relative.parts[0] != name or item.name in seen):
                raise ValueError(f"unsafe or duplicate bundle path: {item.name}")
            seen.add(item.name)
            if item.issym():
                target = item.linkname
                if not target or target.startswith("/") or "\\" in target or "\0" in target:
                    raise ValueError("symlink must use a relative package-local path")
                resolved = list(relative.parts[:-1])
                for part in target.split("/"):
                    if part in ("", "."):
                        continue
                    if part == "..":
                        if len(resolved) <= 1:
                            raise ValueError("symlink escapes package root")
                        resolved.pop()
                    elif part.endswith(":"):
                        raise ValueError("invalid symlink target")
                    else:
                        resolved.append(part)
                links[item.name] = "/".join(resolved)
            elif not (item.isdir() or item.isfile()):
                raise ValueError(f"hard links and special files are forbidden: {item.name}")
            if item.isfile():
                total_size += item.size
                if item.size > 10 * 1024**3 or total_size > min(10 * 1024**3, archive.stat().st_size * 200):
                    raise ValueError("archive expansion limit exceeded")
            if relative.as_posix() == f"{name}/{name}":
                entry = item
        for member in seen:
            parts = PurePosixPath(member).parts
            if any("/".join(parts[:n]) in links for n in range(1, len(parts))):
                raise ValueError("archive member has a symlink parent")
        for link_target in links.values():
            visited = set()
            while link_target in links:
                if link_target in visited:
                    raise ValueError("cyclic symlink")
                visited.add(link_target)
                link_target = links[link_target]
            if link_target not in seen:
                raise ValueError("dangling symlink")
        if entry is None or not entry.isfile() or entry.mode & 0o111 != 0o111:
            raise ValueError("missing executable PRM entrypoint")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    result = {"artifact_type": "directory_tar_gz", "entrypoint": name,
              "size": archive.stat().st_size, "sha256": digest.hexdigest(),
              "entries": len(members)}
    return result


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), indent=2))
