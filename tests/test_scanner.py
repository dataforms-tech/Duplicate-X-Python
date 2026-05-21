import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from duplicate_x_folder.actions import delete_files
from duplicate_x_folder.scanner import ScanOptions, scan_duplicates


class TestScanner(unittest.TestCase):
    def test_finds_duplicates_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "one.txt").write_text("same", encoding="utf-8")
            (root / "b" / "two.txt").write_text("same", encoding="utf-8")
            (root / "b" / "unique.txt").write_text("different", encoding="utf-8")

            result = scan_duplicates(root, options=ScanOptions(workers=1), progress=None)
            self.assertEqual(len(result.duplicate_groups), 1)
            group = result.duplicate_groups[0]
            self.assertEqual(len(group.files), 2)
            paths = sorted(f.path for f in group.files)
            self.assertTrue(str(root / "a" / "one.txt") in paths)
            self.assertTrue(str(root / "b" / "two.txt") in paths)

    def test_hidden_files_ignored_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "visible").mkdir()
            (root / ".hidden").mkdir()
            (root / "visible" / "dup.bin").write_bytes(b"abc")
            (root / ".hidden" / "dup.bin").write_bytes(b"abc")

            result_default = scan_duplicates(root, options=ScanOptions(workers=1), progress=None)
            self.assertEqual(len(result_default.duplicate_groups), 0)

            result_all = scan_duplicates(root, options=ScanOptions(include_hidden=True, workers=1), progress=None)
            self.assertEqual(len(result_all.duplicate_groups), 1)

    def test_quarantine_preserves_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "x" / "y").mkdir(parents=True)
            src = root / "x" / "y" / "dup.txt"
            src.write_text("payload", encoding="utf-8")

            quarantine = root / "Duplicates_Quarantine"
            errs = delete_files(
                [src],
                mode="quarantine",
                quarantine_dir=quarantine,
                root_for_structure=root,
                preserve_structure=True,
                assume_yes=True,
                dry_run=False,
            )
            self.assertEqual(errs, [])
            self.assertFalse(src.exists())
            self.assertTrue((quarantine / "x" / "y" / "dup.txt").exists())


if __name__ == "__main__":
    unittest.main()
