from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    mtime: float

    @classmethod
    def from_path(cls, path: Path) -> "FileEntry":
        stat = path.stat()
        return cls(path=str(path.resolve()), size=stat.st_size, mtime=stat.st_mtime)

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DuplicateGroup:
    group_id: int
    size: int
    sha256: str
    files: List[FileEntry]

    def to_json(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "size": self.size,
            "sha256": self.sha256,
            "files": [f.to_json() for f in self.files],
        }


@dataclass(frozen=True)
class ScanResult:
    root: str
    total_files: int
    scanned_files: int
    duplicate_groups: List[DuplicateGroup]
    errors: List[str]
    created_at_utc: str
    tool_version: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "total_files": self.total_files,
            "scanned_files": self.scanned_files,
            "duplicate_groups": [g.to_json() for g in self.duplicate_groups],
            "errors": list(self.errors),
            "created_at_utc": self.created_at_utc,
            "tool_version": self.tool_version,
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "ScanResult":
        groups: List[DuplicateGroup] = []
        for group_data in data.get("duplicate_groups", []):
            files = [FileEntry(**f) for f in group_data.get("files", [])]
            groups.append(
                DuplicateGroup(
                    group_id=int(group_data["group_id"]),
                    size=int(group_data["size"]),
                    sha256=str(group_data["sha256"]),
                    files=files,
                )
            )
        return cls(
            root=str(data["root"]),
            total_files=int(data.get("total_files", 0)),
            scanned_files=int(data.get("scanned_files", 0)),
            duplicate_groups=groups,
            errors=[str(e) for e in data.get("errors", [])],
            created_at_utc=str(data.get("created_at_utc", "")),
            tool_version=str(data.get("tool_version", "")),
        )


@dataclass(frozen=True)
class KeepChoice:
    group_id: int
    keep_path: str
    reason: str = ""
    selected_index: Optional[int] = None
