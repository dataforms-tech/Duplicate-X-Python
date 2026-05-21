from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .actions import build_action_plan, delete_files
from .scanner import ScanOptions, save_scan_json, scan_duplicates


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Duplicate-X Folder (Python)")
        self.geometry("980x640")

        self.root_var = tk.StringVar(value=str(Path.home()))
        self.include_hidden_var = tk.BooleanVar(value=False)
        self.min_size_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Ready.")
        self.last_result = None

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Folder:").pack(side="left")
        ttk.Entry(top, textvariable=self.root_var, width=80).pack(
            side="left", padx=8, fill="x", expand=True
        )
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left")

        opts = ttk.Frame(self, padding=(10, 0))
        opts.pack(fill="x")
        ttk.Checkbutton(
            opts, text="Include hidden", variable=self.include_hidden_var
        ).pack(side="left")
        ttk.Label(opts, text="Min size (bytes):").pack(side="left", padx=(16, 4))
        ttk.Entry(opts, textvariable=self.min_size_var, width=10).pack(side="left")
        ttk.Button(opts, text="Scan", command=self._scan).pack(side="left", padx=12)
        ttk.Button(opts, text="Export JSON…", command=self._export_json).pack(
            side="left"
        )
        ttk.Button(
            opts, text="Quarantine duplicates (keep 1)", command=self._quarantine
        ).pack(side="left", padx=12)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(8, 0))

        self.tree = ttk.Treeview(self, columns=("size", "path"), show="tree headings")
        self.tree.heading("#0", text="Group / File")
        self.tree.heading("size", text="Size (bytes)")
        self.tree.heading("path", text="Path")
        self.tree.column("#0", width=200)
        self.tree.column("size", width=120, anchor="e")
        self.tree.column("path", width=600)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", padx=10, pady=(0, 10))

    def _browse(self) -> None:
        folder = filedialog.askdirectory(
            initialdir=self.root_var.get() or str(Path.home())
        )
        if folder:
            self.root_var.set(folder)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_var.set(status)
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()

    def _scan(self) -> None:
        root = Path(self.root_var.get()).expanduser()
        try:
            min_size = int(self.min_size_var.get().strip() or "1")
        except ValueError:
            messagebox.showerror("Invalid value", "Min size must be an integer.")
            return

        self._set_busy(True, "Scanning…")

        def worker() -> None:
            try:
                opts = ScanOptions(
                    min_size_bytes=min_size,
                    include_hidden=self.include_hidden_var.get(),
                    workers=4,
                )
                result = scan_duplicates(root, options=opts, progress=None)
                self.last_result = result
                self.after(0, lambda: self._render_result(result))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("Scan failed", str(exc)))
            finally:
                self.after(0, lambda: self._set_busy(False, "Ready."))

        threading.Thread(target=worker, daemon=True).start()

    def _render_result(self, result) -> None:
        self.tree.delete(*self.tree.get_children())
        if not result.duplicate_groups:
            self.status_var.set("No duplicates found.")
            return

        for group in result.duplicate_groups:
            group_id = self.tree.insert(
                "",
                "end",
                text=f"Group {group.group_id}",
                values=(group.size, f"{len(group.files)} files"),
            )
            for i, f in enumerate(group.files):
                self.tree.insert(
                    group_id, "end", text=f"[{i}]", values=(f.size, f.path)
                )
            self.tree.item(group_id, open=True)
        self.status_var.set(f"Found {len(result.duplicate_groups)} duplicate group(s).")

    def _export_json(self) -> None:
        if not self.last_result:
            messagebox.showinfo("Nothing to export", "Run a scan first.")
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")]
        )
        if not out:
            return
        save_scan_json(self.last_result, Path(out))
        messagebox.showinfo("Exported", f"Wrote: {out}")

    def _quarantine(self) -> None:
        if not self.last_result:
            messagebox.showinfo("No scan", "Run a scan first.")
            return
        if not self.last_result.duplicate_groups:
            messagebox.showinfo("No duplicates", "No duplicates found.")
            return
        if not messagebox.askyesno(
            "Confirm", "Move duplicates to quarantine (keeping one per group)?"
        ):
            return

        quarantine_dir = Path(self.last_result.root) / "Duplicates_Quarantine"
        plan = build_action_plan(
            self.last_result, keep_strategy="first", interactive_keep=False
        )
        errs = delete_files(
            plan.to_act,
            mode="quarantine",
            quarantine_dir=quarantine_dir,
            root_for_structure=Path(self.last_result.root),
            preserve_structure=True,
            assume_yes=True,
            dry_run=False,
        )
        if errs:
            messagebox.showerror("Some operations failed", "\n".join(errs[:10]))
        else:
            messagebox.showinfo(
                "Done", f"Moved {len(plan.to_act)} file(s) into {quarantine_dir}"
            )


def run_gui() -> None:
    app = App()
    app.mainloop()
