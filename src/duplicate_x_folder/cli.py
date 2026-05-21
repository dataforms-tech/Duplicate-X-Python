from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .actions import build_action_plan, delete_files, merge_duplicates
from .progress import Progress
from .scanner import ScanOptions, load_scan_json, save_scan_json, scan_duplicates


def _configure_logging(level: str, log_file: Optional[str]) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="duplicate-x", description="Find and manage duplicate files by content.")
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR).")
    p.add_argument("--log-file", default=None, help="Optional log file path.")

    sub = p.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="Scan a folder and list duplicates.")
    scan.add_argument("root", type=str, help="Parent folder to scan.")
    scan.add_argument("--min-size", type=int, default=1, help="Ignore files smaller than this many bytes.")
    scan.add_argument("--include-hidden", action="store_true", help="Include hidden files and folders.")
    scan.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks (off by default).")
    scan.add_argument("--exclude", action="append", default=[], help="Exclude glob pattern (repeatable).")
    scan.add_argument("--workers", type=int, default=4, help="Hashing worker threads.")
    scan.add_argument("--no-progress", action="store_true", help="Disable progress output.")
    scan.add_argument("--json", type=str, default=None, help="Write scan result to JSON file.")

    delete = sub.add_parser("delete", help="Delete/move duplicate files (keeps one per group by default).")
    delete.add_argument("root", type=str, nargs="?", help="Root folder (used if rescanning).")
    delete.add_argument("--input", type=str, default=None, help="Use a previous scan JSON instead of rescanning.")
    delete.add_argument("--keep", default="first", choices=["first", "newest", "oldest", "shortest-path"], help="Which file to keep per group.")
    delete.add_argument("--interactive-keep", action="store_true", help="Choose the file to keep per group interactively.")
    delete.add_argument("--select", action="append", default=[], help="Only act on selected group:index (repeatable).")
    delete.add_argument("--mode", default="quarantine", choices=["delete", "trash", "quarantine"], help="What to do with duplicates.")
    delete.add_argument("--quarantine-dir", default=None, help="Quarantine folder (default: <root>/Duplicates_Quarantine).")
    delete.add_argument("--yes", action="store_true", help="Assume yes for confirmations.")
    delete.add_argument("--dry-run", action="store_true", help="Print actions without modifying files.")
    delete.add_argument("--no-progress", action="store_true", help="Disable progress output.")

    merge = sub.add_parser("merge", help="Move duplicates into a single folder under the root.")
    merge.add_argument("root", type=str, nargs="?", help="Root folder (used if rescanning).")
    merge.add_argument("--input", type=str, default=None, help="Use a previous scan JSON instead of rescanning.")
    merge.add_argument("--merge-dir", default=None, help="Destination folder (default: <root>/Duplicates_Merged).")
    merge.add_argument("--no-preserve-structure", action="store_true", help="Do not preserve folder structure.")
    merge.add_argument("--keep", default="first", choices=["first", "newest", "oldest", "shortest-path"], help="Which file to keep per group.")
    merge.add_argument("--interactive-keep", action="store_true", help="Choose the file to keep per group interactively.")
    merge.add_argument("--yes", action="store_true", help="Assume yes for confirmations.")
    merge.add_argument("--dry-run", action="store_true", help="Print actions without modifying files.")
    merge.add_argument("--no-progress", action="store_true", help="Disable progress output.")

    gui = sub.add_parser("gui", help="Launch a simple Tkinter GUI.")
    gui.add_argument("--log-level", default=None, help="Override global log level for GUI.")
    return p


def _print_scan(result) -> None:
    if result.errors:
        print(f"Warnings/errors: {len(result.errors)}", file=sys.stderr)
        for e in result.errors[:10]:
            print(f"  - {e}", file=sys.stderr)
        if len(result.errors) > 10:
            print("  - ...", file=sys.stderr)

    if not result.duplicate_groups:
        print("No duplicates found.")
        return

    for group in result.duplicate_groups:
        total = len(group.files)
        print(f"\nGroup {group.group_id}: {total} files, {group.size} bytes each, sha256={group.sha256}")
        for i, f in enumerate(group.files):
            print(f"  [{i}] {f.path}  ({f.size} bytes)")
        print(f"  Potential savings (keep 1): {(total - 1) * group.size} bytes")


def _load_or_scan(args) -> object:
    if args.input:
        return load_scan_json(Path(args.input))
    if not args.root:
        raise SystemExit("Provide ROOT folder or --input scan.json")

    progress = Progress(enabled=not args.no_progress)
    opts = ScanOptions(
        min_size_bytes=getattr(args, "min_size", 1),
        include_hidden=getattr(args, "include_hidden", False),
        follow_symlinks=getattr(args, "follow_symlinks", False),
        exclude_globs=tuple(getattr(args, "exclude", []) or ()),
        workers=getattr(args, "workers", 4),
    )
    return scan_duplicates(Path(args.root), options=opts, progress=progress)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "gui" and args.log_level:
        _configure_logging(args.log_level, None)
    else:
        _configure_logging(args.log_level, args.log_file)

    if args.cmd == "scan":
        progress = Progress(enabled=not args.no_progress)
        opts = ScanOptions(
            min_size_bytes=args.min_size,
            include_hidden=args.include_hidden,
            follow_symlinks=args.follow_symlinks,
            exclude_globs=tuple(args.exclude or ()),
            workers=args.workers,
        )
        result = scan_duplicates(Path(args.root), options=opts, progress=progress)
        _print_scan(result)
        if args.json:
            save_scan_json(result, Path(args.json))
            print(f"\nWrote JSON: {Path(args.json).resolve()}", file=sys.stderr)
        return 0

    if args.cmd == "delete":
        result = _load_or_scan(args)
        plan = build_action_plan(result, keep_strategy=args.keep, interactive_keep=args.interactive_keep, select=args.select)
        quarantine = None
        if args.mode == "quarantine":
            quarantine = Path(args.quarantine_dir) if args.quarantine_dir else Path(result.root) / "Duplicates_Quarantine"
        errs = delete_files(
            plan.to_act,
            mode=args.mode,
            quarantine_dir=quarantine,
            root_for_structure=Path(result.root) if args.mode == "quarantine" else None,
            preserve_structure=True,
            assume_yes=args.yes,
            dry_run=args.dry_run,
        )
        if errs:
            print("\nErrors:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 2
        return 0

    if args.cmd == "merge":
        result = _load_or_scan(args)
        merge_dir = Path(args.merge_dir) if args.merge_dir else Path(result.root) / "Duplicates_Merged"
        errs = merge_duplicates(
            result,
            merge_dir=merge_dir,
            preserve_structure=not args.no_preserve_structure,
            keep_strategy=args.keep,
            interactive_keep=args.interactive_keep,
            assume_yes=args.yes,
            dry_run=args.dry_run,
        )
        if errs:
            print("\nErrors:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 2
        return 0

    if args.cmd == "gui":
        from .gui import run_gui

        run_gui()
        return 0

    parser.print_help()
    return 1
