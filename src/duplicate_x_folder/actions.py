from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import DuplicateGroup, KeepChoice, ScanResult

logger = logging.getLogger(__name__)


def _unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    for i in range(1, 10_000):
        candidate = parent / f"{stem}__{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to find unique destination for {dest}")


def choose_keep_file(
    group: DuplicateGroup,
    *,
    strategy: str = "first",
    interactive: bool = False,
) -> KeepChoice:
    files = list(group.files)
    if not files:
        raise ValueError("Duplicate group contains no files.")

    if interactive:
        print(f"\nGroup {group.group_id} ({len(files)} files, {group.size} bytes)")
        for i, f in enumerate(files):
            print(f"  [{i}] {f.path} ({f.size} bytes)")
        while True:
            raw = input("Choose index to KEEP (blank=0, 's' to skip group): ").strip().lower()
            if raw == "":
                return KeepChoice(group_id=group.group_id, keep_path=files[0].path, reason="interactive", selected_index=0)
            if raw == "s":
                return KeepChoice(group_id=group.group_id, keep_path="", reason="skipped", selected_index=None)
            try:
                idx = int(raw)
            except ValueError:
                print("Enter a number, blank, or 's'.")
                continue
            if 0 <= idx < len(files):
                return KeepChoice(group_id=group.group_id, keep_path=files[idx].path, reason="interactive", selected_index=idx)
            print("Index out of range.")

    if strategy == "first":
        chosen = min(files, key=lambda f: f.path)
        return KeepChoice(group_id=group.group_id, keep_path=chosen.path, reason="first")
    if strategy == "newest":
        chosen = max(files, key=lambda f: f.mtime)
        return KeepChoice(group_id=group.group_id, keep_path=chosen.path, reason="newest")
    if strategy == "oldest":
        chosen = min(files, key=lambda f: f.mtime)
        return KeepChoice(group_id=group.group_id, keep_path=chosen.path, reason="oldest")
    if strategy == "shortest-path":
        chosen = min(files, key=lambda f: (len(f.path), f.path))
        return KeepChoice(group_id=group.group_id, keep_path=chosen.path, reason="shortest-path")

    raise ValueError(f"Unknown keep strategy: {strategy}")


@dataclass(frozen=True)
class ActionPlan:
    keep: Dict[int, KeepChoice]
    to_act: List[Path]


def build_action_plan(
    result: ScanResult,
    *,
    keep_strategy: str = "first",
    interactive_keep: bool = False,
    select: Sequence[str] = (),
) -> ActionPlan:
    keep: Dict[int, KeepChoice] = {}
    to_act: List[Path] = []

    select_map: Dict[int, List[int]] = {}
    for item in select:
        try:
            group_str, idx_str = item.split(":", 1)
            gid = int(group_str)
            idx = int(idx_str)
        except ValueError as exc:
            raise ValueError(f"Invalid --select value (expected group:index): {item}") from exc
        select_map.setdefault(gid, []).append(idx)

    for group in result.duplicate_groups:
        keep_choice = choose_keep_file(group, strategy=keep_strategy, interactive=interactive_keep)
        keep[group.group_id] = keep_choice

        if keep_choice.reason == "skipped":
            continue

        if select_map:
            indices = select_map.get(group.group_id, [])
            for idx in indices:
                if idx < 0 or idx >= len(group.files):
                    raise ValueError(f"--select {group.group_id}:{idx} is out of range for that group")
                p = Path(group.files[idx].path)
                if p.resolve() == Path(keep_choice.keep_path).resolve():
                    continue
                to_act.append(p)
        else:
            keep_path = Path(keep_choice.keep_path).resolve()
            for f in group.files:
                p = Path(f.path).resolve()
                if p == keep_path:
                    continue
                to_act.append(p)

    # Keep stable order (good for dry-run output)
    to_act = sorted({p for p in to_act}, key=lambda p: str(p))
    return ActionPlan(keep=keep, to_act=to_act)


def confirm_or_raise(prompt: str, *, assume_yes: bool) -> None:
    if assume_yes:
        return
    ans = input(f"{prompt} [y/N]: ").strip().lower()
    if ans not in {"y", "yes"}:
        raise RuntimeError("Aborted by user.")


def delete_files(
    paths: Iterable[Path],
    *,
    mode: str = "delete",
    quarantine_dir: Optional[Path] = None,
    root_for_structure: Optional[Path] = None,
    preserve_structure: bool = True,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> List[str]:
    paths = list(paths)
    if not paths:
        return []

    action_desc = {
        "delete": "PERMANENTLY delete",
        "trash": "move to system trash",
        "quarantine": "move to quarantine",
    }.get(mode, mode)

    confirm_or_raise(f"{action_desc} {len(paths)} file(s)?", assume_yes=assume_yes)

    errors: List[str] = []
    for path in paths:
        try:
            if dry_run:
                print(f"[dry-run] {mode}: {path}")
                continue

            if mode == "delete":
                path.unlink()
                continue

            if mode == "trash":
                try:
                    from send2trash import send2trash  # type: ignore
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError("Trash mode requires 'send2trash'. Install with: pip install '.[trash]'") from exc
                send2trash(str(path))
                continue

            if mode == "quarantine":
                if quarantine_dir is None:
                    raise ValueError("quarantine_dir is required for quarantine mode")
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / path.name
                if preserve_structure and root_for_structure is not None:
                    try:
                        dest = quarantine_dir / path.resolve().relative_to(root_for_structure.resolve())
                    except Exception:  # noqa: BLE001
                        dest = quarantine_dir / path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest = _unique_destination(dest)
                shutil.move(str(path), str(dest))
                continue

            raise ValueError(f"Unknown delete mode: {mode}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{mode} failed for {path}: {exc}")
    return errors


def merge_duplicates(
    result: ScanResult,
    *,
    merge_dir: Path,
    preserve_structure: bool = True,
    keep_strategy: str = "first",
    interactive_keep: bool = False,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> List[str]:
    root = Path(result.root).resolve()
    merge_dir = merge_dir.resolve()
    merge_dir.mkdir(parents=True, exist_ok=True)

    plan = build_action_plan(result, keep_strategy=keep_strategy, interactive_keep=interactive_keep)
    if not plan.to_act:
        return []

    confirm_or_raise(f"Move {len(plan.to_act)} duplicate file(s) into {merge_dir}?", assume_yes=assume_yes)

    errors: List[str] = []
    for path in plan.to_act:
        try:
            rel = None
            if preserve_structure:
                try:
                    rel = path.resolve().relative_to(root)
                except Exception:  # noqa: BLE001
                    rel = Path(path.name)
            if preserve_structure:
                dest = merge_dir / rel  # type: ignore[arg-type]
            else:
                dest = merge_dir / f"group_{_group_id_for_path(result, path)}" / path.name

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest = _unique_destination(dest)
            if dry_run:
                print(f"[dry-run] move: {path} -> {dest}")
            else:
                shutil.move(str(path), str(dest))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"merge failed for {path}: {exc}")
    return errors


def _group_id_for_path(result: ScanResult, path: Path) -> int:
    target = str(path.resolve())
    for group in result.duplicate_groups:
        for f in group.files:
            if str(Path(f.path).resolve()) == target:
                return group.group_id
    return 0
