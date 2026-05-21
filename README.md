# Duplicate-X-Folder-Python

Scan a folder (recursively) and find duplicate files by **content** (SHA-256), then optionally delete/trash/quarantine/merge duplicates safely.

## Features

- Recursive scan of all subfolders
- Detect duplicates by content (size → quick fingerprint → full SHA-256)
- Lists duplicate groups with full path + size
- Safe operations (confirmation prompts, plus `--dry-run`)
- Delete options:
  - delete selected duplicates (`--select group:index`)
  - delete all duplicates except one per group (`--keep ...`)
  - move duplicates to trash (optional dependency) or quarantine folder
- Choose which file to keep per group (`--interactive-keep` or `--keep newest|oldest|...`)
- Simple progress display for large folders
- Simple GUI (`duplicate-x gui`) using Tkinter

## Requirements

- Python 3.9+

Optional:
- `send2trash` for system trash support (`pip install ".[trash]"`)

## Install

From this repository:

```bash
pip install .
```

With trash support:

```bash
pip install ".[trash]"
```

## Usage (CLI)

Scan a folder:

```bash
duplicate-x scan /path/to/parent --json duplicate_scan.json
```

Delete duplicates (keep one per group, default keep strategy: `first`) by moving to a quarantine folder:

```bash
duplicate-x delete --input duplicate_scan.json --mode quarantine
```

Choose which file to keep per group interactively:

```bash
duplicate-x delete --input duplicate_scan.json --interactive-keep --mode quarantine
```

Delete only specific duplicates (group 1 index 2, group 3 index 0):

```bash
duplicate-x delete --input duplicate_scan.json --select 1:2 --select 3:0 --mode quarantine
```

Move duplicates to system trash (requires `send2trash`):

```bash
duplicate-x delete --input duplicate_scan.json --mode trash
```

Merge duplicates into one folder under the root (moves duplicates, keeps one per group in place):

```bash
duplicate-x merge --input duplicate_scan.json
```

Preserve structure (default) vs flatten into `group_<id>` folders:

```bash
duplicate-x merge --input duplicate_scan.json --no-preserve-structure
```

Safety flags:

- `--dry-run`: show what would happen, but don’t change files
- `--yes`: skip confirmation prompts (use with care)

## Usage (GUI)

```bash
duplicate-x gui
```

The GUI supports: selecting a folder, scanning, exporting JSON, and quarantining duplicates (keep 1 per group).

## Example output

```text
Group 1: 3 files, 1024 bytes each, sha256=...
  [0] /data/a/file.bin  (1024 bytes)
  [1] /data/b/file.bin  (1024 bytes)
  [2] /data/c/file-copy.bin  (1024 bytes)
  Potential savings (keep 1): 2048 bytes
```

## Sample folder structure

```text
parent/
  photos/
    img001.jpg
    img001-copy.jpg
  backups/
    img001.jpg
```

## Notes

- By default, hidden files/folders and common temporary files are ignored. Use `--include-hidden` to include them.
- Large files are hashed in streaming chunks to avoid high memory usage.
