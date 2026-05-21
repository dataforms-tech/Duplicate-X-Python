from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .models import DuplicateGroup, FileEntry, ScanResult
from .progress import Progress

logger = logging.getLogger(__name__)


DEFAULT_IGNORED_FILENAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

DEFAULT_IGNORED_GLOBS = [
    "*.tmp",
    "*.temp",
    "*.swp",
    "*.swo",
    "*.part",
    "*.crdownload",
    "*.download",
    "~$*",
]


def _is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def iter_files(
    root: Path,
    *,
    include_hidden: bool = False,
    follow_symlinks: bool = False,
    exclude_globs: Sequence[str] = (),
    progress: Optional[Progress] = None,
    errors: Optional[List[str]] = None,
) -> Iterator[Path]:
    root = root.resolve()
    if progress:
        progress.update(f"Walking: {root}")

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=follow_symlinks):
        dir_path = Path(dirpath)
        if not include_hidden:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        if progress:
            progress.update(f"Walking: {dir_path}")

        for name in filenames:
            if name in DEFAULT_IGNORED_FILENAMES:
                continue
            if not include_hidden and name.startswith("."):
                continue
            if any(fnmatch(name, pattern) for pattern in DEFAULT_IGNORED_GLOBS):
                continue

            path = dir_path / name
            if not include_hidden and _is_hidden_path(path.relative_to(root)):
                continue
            if exclude_globs and any(fnmatch(str(path), pattern) for pattern in exclude_globs):
                continue

            try:
                if not path.is_file():
                    continue
                if path.is_symlink() and not follow_symlinks:
                    continue
            except OSError as exc:
                if errors is not None:
                    errors.append(f"stat failed for {path}: {exc}")
                continue

            yield path


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def quick_fingerprint(path: Path, *, sample_size: int = 64 * 1024) -> str:
    stat = path.stat()
    file_size = stat.st_size
    digest = hashlib.sha256()
    digest.update(str(file_size).encode("utf-8"))
    with path.open("rb") as f:
        head = f.read(sample_size)
        digest.update(head)
        if file_size > sample_size:
            try:
                f.seek(max(0, file_size - sample_size))
            except OSError:
                return digest.hexdigest()
            tail = f.read(sample_size)
            digest.update(tail)
    return digest.hexdigest()


@dataclass(frozen=True)
class ScanOptions:
    min_size_bytes: int = 1
    include_hidden: bool = False
    follow_symlinks: bool = False
    exclude_globs: Tuple[str, ...] = ()
    workers: int = 4


def scan_duplicates(
    root: Path,
    *,
    options: Optional[ScanOptions] = None,
    progress: Optional[Progress] = None,
) -> ScanResult:
    options = options or ScanOptions()
    errors: List[str] = []
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Root folder does not exist or is not a directory: {root}")

    files: List[Path] = []
    total_files = 0
    for path in iter_files(
        root,
        include_hidden=options.include_hidden,
        follow_symlinks=options.follow_symlinks,
        exclude_globs=options.exclude_globs,
        progress=progress,
        errors=errors,
    ):
        total_files += 1
        try:
            if path.stat().st_size < options.min_size_bytes:
                continue
        except OSError as exc:
            errors.append(f"stat failed for {path}: {exc}")
            continue
        files.append(path)

    if progress:
        progress.update(f"Collected {len(files)} candidate files (out of {total_files})", force=True)

    by_size: Dict[int, List[Path]] = {}
    for path in files:
        try:
            by_size.setdefault(path.stat().st_size, []).append(path)
        except OSError as exc:
            errors.append(f"stat failed for {path}: {exc}")

    size_candidates = {size: paths for size, paths in by_size.items() if len(paths) > 1}
    if progress:
        progress.update(f"Size groups: {len(size_candidates)}", force=True)

    def _safe_quick(path: Path) -> Tuple[Path, Optional[str], Optional[str]]:
        try:
            return path, quick_fingerprint(path), None
        except OSError as exc:
            return path, None, f"quick hash failed for {path}: {exc}"

    quick_groups: Dict[Tuple[int, str], List[Path]] = {}
    with ThreadPoolExecutor(max_workers=max(1, options.workers)) as ex:
        fut_to_size: Dict[object, int] = {}
        for size, paths in size_candidates.items():
            for path in paths:
                fut_to_size[ex.submit(_safe_quick, path)] = size

        done = 0
        for fut in as_completed(list(fut_to_size.keys())):
            size = fut_to_size[fut]
            path, fp, err = fut.result()
            done += 1
            if progress and done % 50 == 0:
                progress.update(f"Fingerprinting: {done}/{len(fut_to_size)}")
            if err:
                errors.append(err)
                continue
            if fp is None:
                continue
            quick_groups.setdefault((size, fp), []).append(path)

    quick_candidates = {k: v for k, v in quick_groups.items() if len(v) > 1}
    if progress:
        progress.update(f"Fingerprint groups: {len(quick_candidates)}", force=True)

    def _safe_full(path: Path) -> Tuple[Path, Optional[str], Optional[str]]:
        try:
            return path, sha256_file(path), None
        except OSError as exc:
            return path, None, f"sha256 failed for {path}: {exc}"

    full_groups: Dict[str, List[Path]] = {}
    full_size: Dict[str, int] = {}

    candidates_list: List[Path] = [p for paths in quick_candidates.values() for p in paths]
    with ThreadPoolExecutor(max_workers=max(1, options.workers)) as ex:
        futs = {ex.submit(_safe_full, p): p for p in candidates_list}
        done = 0
        for fut in as_completed(futs):
            done += 1
            if progress and done % 20 == 0:
                progress.update(f"Hashing: {done}/{len(candidates_list)}")
            path, digest, err = fut.result()
            if err:
                errors.append(err)
                continue
            if digest is None:
                continue
            full_groups.setdefault(digest, []).append(path)
            if digest not in full_size:
                try:
                    full_size[digest] = path.stat().st_size
                except OSError:
                    full_size[digest] = 0

    duplicates = [(digest, paths) for digest, paths in full_groups.items() if len(paths) > 1]
    duplicates.sort(key=lambda item: (-len(item[1]), -full_size.get(item[0], 0), item[0]))

    groups: List[DuplicateGroup] = []
    for idx, (digest, paths) in enumerate(duplicates, start=1):
        entries: List[FileEntry] = []
        for p in sorted(paths, key=lambda x: str(x)):
            try:
                entries.append(FileEntry.from_path(p))
            except OSError as exc:
                errors.append(f"stat failed for {p}: {exc}")
        size = full_size.get(digest, entries[0].size if entries else 0)
        groups.append(DuplicateGroup(group_id=idx, size=size, sha256=digest, files=entries))

    if progress:
        progress.done(f"Found {len(groups)} duplicate groups.")

    created = datetime.now(timezone.utc).isoformat()
    from . import __version__

    return ScanResult(
        root=str(root),
        total_files=total_files,
        scanned_files=len(files),
        duplicate_groups=groups,
        errors=errors,
        created_at_utc=created,
        tool_version=__version__,
    )


def save_scan_json(result: ScanResult, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_json(), indent=2, sort_keys=True), encoding="utf-8")


def load_scan_json(path: Path) -> ScanResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ScanResult.from_json(data)
