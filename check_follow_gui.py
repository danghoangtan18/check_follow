#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from check_follow import (
    build_unique_usernames,
    collect_stats_with_callback,
    format_number,
    read_users_from_file,
)


APP_NAME = "TikTokFollowChecker"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()
LEGACY_MAC_DATA_DIR = (
    Path.home() / "Library" / "Application Support" / APP_NAME
).resolve()


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        return (Path.home() / "Documents" / APP_NAME).resolve()

    executable_path = Path(
        sys.executable if getattr(sys, "frozen", False) else __file__
    ).resolve()
    return executable_path.parent


DATA_DIR = get_data_dir()
COLUMNS = (
    "username",
    "followers",
    "following",
    "likes",
    "private",
    "verified",
    "status",
)

SAMPLE_FILE = DATA_DIR / "users.example.txt"
if not SAMPLE_FILE.exists():
    SAMPLE_FILE = RESOURCE_DIR / "users.example.txt"
PROJECTS_DIR = DATA_DIR / "projects"
AUTOSAVE_DELAY_MS = 900


def slugify_project_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-_").lower()
    return slug or "project"


def current_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def migrate_legacy_mac_projects() -> None:
    if sys.platform != "darwin":
        return

    legacy_projects_dir = LEGACY_MAC_DATA_DIR / "projects"
    target_projects_dir = PROJECTS_DIR

    if not legacy_projects_dir.exists():
        return

    target_projects_dir.mkdir(parents=True, exist_ok=True)

    legacy_files = list(legacy_projects_dir.glob("*.json"))
    if not legacy_files:
        return

    for legacy_file in legacy_files:
        target_file = target_projects_dir / legacy_file.name
        if not target_file.exists():
            shutil.copy2(legacy_file, target_file)


class MultiLineInputDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, title: str, prompt: str) -> None:
        self.prompt = prompt
        self.value = ""
        super().__init__(parent, title)

    def body(self, master: tk.Misc) -> tk.Widget:
        master.columnconfigure(0, weight=1)
        master.rowconfigure(1, weight=1)

        ttk.Label(master, text=self.prompt).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.text = tk.Text(master, width=56, height=14, font=("Consolas", 10))
        self.text.grid(row=1, column=0, sticky="nsew")
        return self.text

    def apply(self) -> None:
        self.value = self.text.get("1.0", "end").strip()


class ProjectStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []

        for path in self.base_dir.glob("*.json"):
            payload = self._read_project_file(path)
            if payload is None:
                continue
            projects.append(payload)

        return sorted(projects, key=lambda item: item["name"].lower())

    def load_project(self, name: str) -> dict[str, Any]:
        path = self._find_project_path(name)
        if path is None:
            raise FileNotFoundError(f"Khong tim thay project: {name}")

        payload = self._read_project_file(path)
        if payload is None:
            raise RuntimeError(f"Project bi loi du lieu: {name}")

        return payload

    def project_exists(self, name: str) -> bool:
        return self._find_project_path(name) is not None

    def create_project(
        self,
        name: str,
        users: list[str] | None = None,
        results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Ten project khong duoc de trong.")

        if self.project_exists(normalized_name):
            raise ValueError("Project nay da ton tai.")

        path = self._next_available_path(normalized_name)
        payload = self._build_payload(normalized_name, users or [], results or [])
        self._write_project_file(path, payload)
        return payload

    def save_project(
        self,
        name: str,
        users: list[str],
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Ten project khong duoc de trong.")

        path = self._find_project_path(normalized_name)
        if path is None:
            path = self._next_available_path(normalized_name)

        payload = self._build_payload(normalized_name, users, results)
        self._write_project_file(path, payload)
        return payload

    def delete_project(self, name: str) -> None:
        path = self._find_project_path(name)
        if path is None:
            raise FileNotFoundError(f"Khong tim thay project: {name}")
        path.unlink()

    def _build_payload(
        self,
        name: str,
        users: list[str],
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clean_users = [
            str(user).strip()
            for user in users
            if str(user).strip() and not str(user).strip().startswith("#")
        ]

        return {
            "name": name,
            "users": clean_users,
            "results": results,
            "updatedAt": current_timestamp(),
        }

    def _find_project_path(self, name: str) -> Path | None:
        expected_name = name.strip().casefold()
        for path in self.base_dir.glob("*.json"):
            payload = self._read_project_file(path)
            if payload is None:
                continue
            if payload["name"].casefold() == expected_name:
                return path
        return None

    def _next_available_path(self, name: str) -> Path:
        base_slug = slugify_project_name(name)
        candidate = base_slug
        counter = 2

        while (self.base_dir / f"{candidate}.json").exists():
            candidate = f"{base_slug}-{counter}"
            counter += 1

        return self.base_dir / f"{candidate}.json"

    def _read_project_file(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

        name = str(payload.get("name") or path.stem).strip()
        if not name:
            name = path.stem

        users = payload.get("users") or []
        if not isinstance(users, list):
            users = []

        results = payload.get("results") or []
        if not isinstance(results, list):
            results = []

        return {
            "name": name,
            "users": [
                str(user).strip()
                for user in users
                if str(user).strip() and not str(user).strip().startswith("#")
            ],
            "results": results,
            "updatedAt": str(payload.get("updatedAt") or ""),
            "path": path,
        }

    def _write_project_file(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class CheckFollowApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TikTok Follow Checker")
        self.root.geometry("1240x780")
        self.root.minsize(1040, 660)

        migrate_legacy_mac_projects()
        self.store = ProjectStore(PROJECTS_DIR)
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.current_results: list[dict[str, Any]] = []
        self.current_project_name: str | None = None
        self.worker_thread: threading.Thread | None = None
        self.project_switch_locked = False
        self.ignore_text_changes = False
        self.project_dirty = False
        self.autosave_job: str | None = None

        self.project_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Tao project moi hoac chon project da co de quan ly danh sach user."
        )
        self.summary_var = tk.StringVar(value="Chua co du lieu.")

        self._configure_style()
        self._build_layout()
        self._load_initial_project()
        self.root.after(150, self._process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Info.TLabel", font=("Segoe UI", 10))
        style.configure("Action.TButton", padding=(12, 8))

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(16, 16, 16, 10))
        header.grid(row=0, column=0, sticky="nsew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="TikTok Follow Checker",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            header,
            text=(
                "Moi project luu rieng danh sach user va ket qua check gan nhat. "
                "Ban co the tao nhieu project khac nhau."
            ),
            style="Info.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        content = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        content.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))

        top = ttk.Frame(content, padding=12)
        top.columnconfigure(0, weight=1)
        top.rowconfigure(2, weight=1)
        content.add(top, weight=2)

        project_bar = ttk.Frame(top)
        project_bar.grid(row=0, column=0, sticky="ew")
        project_bar.columnconfigure(1, weight=1)

        ttk.Label(project_bar, text="Project").grid(row=0, column=0, sticky="w")

        self.project_combo = ttk.Combobox(
            project_bar,
            textvariable=self.project_var,
            state="readonly",
        )
        self.project_combo.grid(row=0, column=1, sticky="ew", padx=(10, 8))
        self.project_combo.bind("<<ComboboxSelected>>", self._on_project_selected)

        self.quick_check_button = ttk.Button(
            project_bar,
            text="Check",
            style="Action.TButton",
            command=self.start_check,
        )
        self.quick_check_button.grid(row=0, column=2, padx=(0, 8))

        self.new_project_button = ttk.Button(
            project_bar,
            text="New Project",
            command=self.create_project,
        )
        self.new_project_button.grid(row=0, column=3, padx=(0, 8))

        self.save_project_button = ttk.Button(
            project_bar,
            text="Save Project",
            command=self.save_current_project,
            state="disabled",
        )
        self.save_project_button.grid(row=0, column=4, padx=(0, 8))

        self.delete_project_button = ttk.Button(
            project_bar,
            text="Delete Project",
            command=self.delete_current_project,
            state="disabled",
        )
        self.delete_project_button.grid(row=0, column=5)

        self.open_data_button = ttk.Button(
            project_bar,
            text="Open Data Folder",
            command=self.open_data_folder,
        )
        self.open_data_button.grid(row=0, column=6, padx=(8, 0))

        ttk.Label(top, text="Danh sach user cua project").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(12, 0),
        )

        input_frame = ttk.Frame(top)
        input_frame.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        self.input_text = tk.Text(
            input_frame,
            wrap="word",
            font=("Consolas", 10),
            padx=10,
            pady=10,
            undo=True,
            height=12,
        )
        self.input_text.grid(row=0, column=0, sticky="nsew")
        self.input_text.bind("<<Modified>>", self._on_input_modified)

        input_scroll = ttk.Scrollbar(
            input_frame,
            orient="vertical",
            command=self.input_text.yview,
        )
        input_scroll.grid(row=0, column=1, sticky="ns")
        self.input_text.configure(yscrollcommand=input_scroll.set)

        action_bar = ttk.Frame(top)
        action_bar.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        action_bar.columnconfigure(6, weight=1)

        self.check_button = ttk.Button(
            action_bar,
            text="Check",
            style="Action.TButton",
            command=self.start_check,
        )
        self.check_button.grid(row=0, column=0, padx=(0, 8))

        self.add_users_button = ttk.Button(
            action_bar,
            text="Add Users",
            command=self.add_users,
        )
        self.add_users_button.grid(row=0, column=1, padx=(0, 8))

        self.clear_button = ttk.Button(
            action_bar,
            text="Clear Input",
            command=self.clear_input,
        )
        self.clear_button.grid(row=0, column=2, padx=(0, 8))

        self.load_button = ttk.Button(
            action_bar,
            text="Load File",
            command=self.load_file,
        )
        self.load_button.grid(row=0, column=3, padx=(0, 8))

        self.sample_button = ttk.Button(
            action_bar,
            text="Load Sample",
            command=self.load_sample,
        )
        self.sample_button.grid(row=0, column=4, padx=(0, 8))

        self.export_button = ttk.Button(
            action_bar,
            text="Export CSV",
            command=self.export_csv,
            state="disabled",
        )
        self.export_button.grid(row=0, column=5, padx=(0, 8))

        self.progress = ttk.Progressbar(
            action_bar,
            orient="horizontal",
            mode="indeterminate",
            length=240,
        )
        self.progress.grid(row=0, column=6, sticky="e")

        bottom = ttk.Frame(content, padding=12)
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(1, weight=1)
        content.add(bottom, weight=3)

        ttk.Label(bottom, text="Ket qua").grid(row=0, column=0, sticky="w")

        table_frame = ttk.Frame(bottom)
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table_frame,
            columns=COLUMNS,
            show="headings",
            height=16,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")

        headings = {
            "username": "Username",
            "followers": "Followers",
            "following": "Following",
            "likes": "Likes",
            "private": "Private",
            "verified": "Verified",
            "status": "Status",
        }
        widths = {
            "username": 170,
            "followers": 110,
            "following": 100,
            "likes": 120,
            "private": 80,
            "verified": 80,
            "status": 250,
        }

        for column in COLUMNS:
            self.tree.heading(column, text=headings[column])
            anchor = "w" if column in {"username", "nickname", "status"} else "center"
            self.tree.column(column, width=widths[column], anchor=anchor, stretch=True)

        y_scroll = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
        )
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=y_scroll.set)

        x_scroll = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
        )
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=x_scroll.set)

        footer = ttk.Frame(self.root, padding=(16, 6, 16, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.summary_var).grid(row=0, column=1, sticky="e")

    def _load_initial_project(self) -> None:
        projects = self.store.list_projects()
        self.project_combo.configure(values=[project["name"] for project in projects])

        if projects:
            self._select_project(projects[0]["name"], autosave_previous=False)
            return

        self.status_var.set("Chua co project nao. Bam New Project de tao project dau tien.")
        self._update_summary()

    def _on_project_selected(self, _event: Any) -> None:
        if self.project_switch_locked:
            return

        selected_name = self.project_var.get().strip()
        if not selected_name or selected_name == self.current_project_name:
            return

        self._select_project(selected_name, autosave_previous=True)

    def _select_project(self, project_name: str, autosave_previous: bool) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        if (
            autosave_previous
            and self.current_project_name
            and self.current_project_name != project_name
            and not self._save_project_data(show_message=False)
        ):
            self.project_switch_locked = True
            self.project_var.set(self.current_project_name)
            self.project_switch_locked = False
            return

        try:
            project = self.store.load_project(project_name)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Khong mo duoc project", str(exc))
            return

        self.project_switch_locked = True
        self.project_var.set(project["name"])
        self.project_switch_locked = False
        self.current_project_name = project["name"]

        self._set_input_lines(project["users"])
        self._set_results(project["results"])
        self._refresh_project_controls()
        self.status_var.set(f"Da mo project: {project['name']}")
        self.project_dirty = False
        self._update_summary()

    def _refresh_project_controls(self) -> None:
        has_project = self.current_project_name is not None
        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.save_project_button.configure(state="normal" if has_project else "disabled")
        self.delete_project_button.configure(state="normal" if has_project else "disabled")
        self.export_button.configure(
            state="normal" if has_project and self.current_results else "disabled"
        )

    def _refresh_project_list(self, selected_name: str | None = None) -> None:
        projects = self.store.list_projects()
        values = [project["name"] for project in projects]
        self.project_combo.configure(values=values)

        if not values:
            self.project_switch_locked = True
            self.project_var.set("")
            self.project_switch_locked = False
            self.current_project_name = None
            self.project_dirty = False
            self.save_project_button.configure(state="disabled")
            self.delete_project_button.configure(state="disabled")
            self.export_button.configure(state="disabled")
            self._update_summary()
            return

        if selected_name and selected_name in values:
            self.project_switch_locked = True
            self.project_var.set(selected_name)
            self.project_switch_locked = False

    def create_project(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        if self.current_project_name and not self._save_project_data(show_message=False):
            return

        project_name = simpledialog.askstring(
            "New Project",
            "Nhap ten project:",
            parent=self.root,
        )
        if project_name is None:
            return

        project_name = project_name.strip()
        if not project_name:
            messagebox.showinfo("Thieu ten", "Ten project khong duoc de trong.")
            return

        try:
            self.store.create_project(
                project_name,
                users=self.get_input_lines(),
                results=[],
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Khong tao duoc project", str(exc))
            return

        self._refresh_project_list(selected_name=project_name)
        self._select_project(project_name, autosave_previous=False)
        self.status_var.set(f"Da tao project: {project_name}")

    def delete_current_project(self) -> None:
        if not self.current_project_name:
            return

        if self.worker_thread and self.worker_thread.is_alive():
            return

        project_name = self.current_project_name
        confirmed = messagebox.askyesno(
            "Xoa project",
            f"Ban co chac muon xoa project '{project_name}' khong?",
            parent=self.root,
        )
        if not confirmed:
            return

        try:
            self.store.delete_project(project_name)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Khong xoa duoc project", str(exc))
            return

        self.current_project_name = None
        self.current_results = []
        self._set_input_lines([])
        self._clear_table()
        self._refresh_project_list()

        projects = self.store.list_projects()
        if projects:
            self._select_project(projects[0]["name"], autosave_previous=False)
        else:
            self.status_var.set("Da xoa project. Chua con project nao.")
            self._update_summary()

    def get_input_lines(self) -> list[str]:
        content = self.input_text.get("1.0", "end").strip()
        if not content:
            return []

        return [
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def _set_input_lines(self, users: list[str]) -> None:
        self.ignore_text_changes = True
        self.input_text.delete("1.0", "end")
        if users:
            self.input_text.insert("1.0", "\n".join(users))
        self.input_text.edit_modified(False)
        self.ignore_text_changes = False
        self._update_summary()

    def _on_input_modified(self, _event: Any) -> None:
        if self.ignore_text_changes:
            self.input_text.edit_modified(False)
            return

        if not self.input_text.edit_modified():
            return

        self.input_text.edit_modified(False)
        self.project_dirty = True
        self._update_summary()
        self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if not self.current_project_name:
            return

        if self.worker_thread and self.worker_thread.is_alive():
            return

        if self.autosave_job is not None:
            self.root.after_cancel(self.autosave_job)

        self.autosave_job = self.root.after(AUTOSAVE_DELAY_MS, self._run_autosave)

    def _run_autosave(self) -> None:
        self.autosave_job = None
        if not self.current_project_name or not self.project_dirty:
            return

        if self.worker_thread and self.worker_thread.is_alive():
            return

        if self._save_project_data(show_message=False):
            self.status_var.set(f"Da tu dong luu project: {self.current_project_name}")
            self._update_summary()

    def add_users(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        dialog = MultiLineInputDialog(
            self.root,
            "Add Users",
            "Paste username TikTok, moi dong 1 user.",
        )
        raw_value = dialog.value.strip()
        if not raw_value:
            return

        new_inputs = [
            line.strip()
            for line in raw_value.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not new_inputs:
            return

        try:
            existing_users = build_unique_usernames(self.get_input_lines())
            combined_users = build_unique_usernames(existing_users + new_inputs)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Input khong hop le", str(exc))
            return

        added_count = len(combined_users) - len(existing_users)
        self._set_input_lines(combined_users)
        self.project_dirty = True
        self._schedule_autosave()

        if added_count > 0:
            self.status_var.set(f"Da them {added_count} user vao project hien tai.")
        else:
            self.status_var.set("Khong co user moi duoc them vi danh sach da ton tai.")
        self._update_summary()

    def clear_input(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.input_text.delete("1.0", "end")
        self.project_dirty = True
        self._schedule_autosave()
        if self.current_project_name:
            self.status_var.set("Da xoa input. Bam Save Project hoac Check de cap nhat project.")
        else:
            self.status_var.set("Da xoa input.")
        self._update_summary()

    def load_sample(self) -> None:
        if not SAMPLE_FILE.exists():
            messagebox.showwarning(
                "Khong tim thay file",
                "Khong co users.example.txt trong thu muc hien tai.",
            )
            return

        self._set_input_lines(read_users_from_file(str(SAMPLE_FILE)))
        self.project_dirty = True
        self._schedule_autosave()
        self.status_var.set("Da nap users.example.txt vao o input. Bam Save Project neu muon luu.")

    def open_data_folder(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(DATA_DIR)], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(DATA_DIR)], check=False)
            else:
                subprocess.run(["xdg-open", str(DATA_DIR)], check=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Khong mo duoc thu muc", str(exc))
            return

        self.status_var.set(f"Da mo thu muc luu du lieu: {DATA_DIR}")

    def load_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Chon file user",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            users = read_users_from_file(file_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Khong doc duoc file", str(exc))
            return

        self._set_input_lines(users)
        self.project_dirty = True
        self._schedule_autosave()
        self.status_var.set(
            "Da nap danh sach tu file. Bam Save Project hoac Check de luu vao project."
        )

    def export_csv(self) -> None:
        if not self.current_results:
            messagebox.showinfo("Chua co du lieu", "Ban can check xong truoc khi export CSV.")
            return

        suggested_name = "ket-qua.csv"
        if self.current_project_name:
            suggested_name = f"{slugify_project_name(self.current_project_name)}.csv"

        file_path = filedialog.asksaveasfilename(
            title="Luu ket qua CSV",
            defaultextension=".csv",
            initialfile=suggested_name,
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(COLUMNS)
                for result in self.current_results:
                    writer.writerow(
                        [
                            result["uniqueId"],
                            result["followers"],
                            result["following"],
                            result["likes"],
                            "yes" if result["privateAccount"] else "no",
                            "yes" if result["verified"] else "no",
                            "ok" if result["ok"] else result["statusMsg"],
                        ]
                    )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Khong luu duoc file", str(exc))
            return

        self.status_var.set(f"Da export CSV: {file_path}")

    def save_current_project(self) -> None:
        if not self.current_project_name:
            self.create_project()
            return

        self._save_project_data(show_message=True)

    def _save_project_data(
        self,
        show_message: bool,
        results_override: list[dict[str, Any]] | None = None,
    ) -> bool:
        if not self.current_project_name:
            return False

        if self.autosave_job is not None:
            self.root.after_cancel(self.autosave_job)
            self.autosave_job = None

        try:
            self.store.save_project(
                self.current_project_name,
                users=self.get_input_lines(),
                results=self.current_results if results_override is None else results_override,
            )
        except Exception as exc:  # noqa: BLE001
            if show_message:
                messagebox.showerror("Khong luu duoc project", str(exc))
            return False

        self.project_dirty = False
        if show_message:
            self.status_var.set(f"Da luu project: {self.current_project_name}")

        self._refresh_project_list(selected_name=self.current_project_name)
        self._refresh_project_controls()
        self._update_summary()
        return True

    def start_check(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        raw_inputs = self.get_input_lines()
        if not raw_inputs:
            messagebox.showinfo("Chua co user", "Hay nhap hoac paste danh sach user truoc khi check.")
            return

        if not self.current_project_name:
            project_name = simpledialog.askstring(
                "Tao project",
                "Nhap ten project de luu danh sach user nay:",
                parent=self.root,
            )
            if project_name is None:
                return

            project_name = project_name.strip()
            if not project_name:
                messagebox.showinfo("Thieu ten", "Ten project khong duoc de trong.")
                return

            try:
                self.store.create_project(project_name, users=raw_inputs, results=[])
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Khong tao duoc project", str(exc))
                return

            self._refresh_project_list(selected_name=project_name)
            self._select_project(project_name, autosave_previous=False)
            raw_inputs = self.get_input_lines()

        try:
            usernames = build_unique_usernames(raw_inputs)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Input khong hop le", str(exc))
            return

        self.current_results = []
        self._clear_table()
        self.project_dirty = True
        self._save_project_data(show_message=False, results_override=[])
        self._set_running_state(True)
        self.status_var.set(
            f"Bat dau check {len(usernames)} user trong project {self.current_project_name}..."
        )
        self._update_summary(extra_note=f"Dang check 0/{len(usernames)}")

        self.worker_thread = threading.Thread(
            target=self._run_check_worker,
            args=(usernames,),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_check_worker(self, usernames: list[str]) -> None:
        def progress_callback(index: int, total: int, result: dict[str, Any]) -> None:
            self.queue.put(("progress", (index, total, result)))

        try:
            results = collect_stats_with_callback(usernames, progress_callback=progress_callback)
            self.queue.put(("done", results))
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("error", str(exc)))

    def _process_queue(self) -> None:
        try:
            while True:
                message_type, payload = self.queue.get_nowait()

                if message_type == "progress":
                    index, total, result = payload
                    self.current_results.append(result)
                    self._insert_result_row(result)
                    self.status_var.set(f"Dang check {index}/{total}: {result['uniqueId']}")
                    self._update_summary(extra_note=f"Dang check {index}/{total}")

                elif message_type == "done":
                    results = payload
                    self.current_results = results
                    success_count = sum(1 for result in results if result["ok"])
                    self._save_project_data(show_message=False, results_override=results)
                    self.status_var.set("Check hoan tat va da luu vao project.")
                    self._update_summary(extra_note=f"Thanh cong {success_count}/{len(results)}")
                    self._set_running_state(False)

                elif message_type == "error":
                    self._set_running_state(False)
                    self.status_var.set("Co loi khi check.")
                    self._update_summary(extra_note="Khong hoan tat")
                    messagebox.showerror("Loi", str(payload))
        except queue.Empty:
            pass

        self.root.after(150, self._process_queue)

    def _set_running_state(self, is_running: bool) -> None:
        state = "disabled" if is_running else "normal"
        self.check_button.configure(state=state)
        self.quick_check_button.configure(state=state)
        self.add_users_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.load_button.configure(state=state)
        self.sample_button.configure(state=state)
        self.new_project_button.configure(state=state)
        self.project_combo.configure(state="disabled" if is_running else "readonly")

        if self.current_project_name:
            project_state = "disabled" if is_running else "normal"
            self.save_project_button.configure(state=project_state)
            self.delete_project_button.configure(state=project_state)
        else:
            self.save_project_button.configure(state="disabled")
            self.delete_project_button.configure(state="disabled")

        self.export_button.configure(
            state="disabled" if is_running or not self.current_results else "normal"
        )

        if is_running:
            self.progress.start(10)
        else:
            self.progress.stop()
            self._refresh_project_controls()

    def _clear_table(self) -> None:
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

    def _set_results(self, results: list[dict[str, Any]]) -> None:
        self.current_results = results
        self._clear_table()
        for result in results:
            self._insert_result_row(result)
        self._refresh_project_controls()
        self._update_summary()

    def _insert_result_row(self, result: dict[str, Any]) -> None:
        values = (
            result.get("uniqueId", ""),
            format_number(result.get("followers")),
            format_number(result.get("following")),
            format_number(result.get("likes")),
            "yes" if result.get("privateAccount") else "no",
            "yes" if result.get("verified") else "no",
            "ok" if result.get("ok") else result.get("statusMsg", ""),
        )
        self.tree.insert("", "end", values=values)

    def on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Dang chay", "Hay doi check xong truoc khi dong cua so.")
            return

        self._save_project_data(show_message=False)
        self.root.destroy()

    def _update_summary(self, extra_note: str | None = None) -> None:
        project_label = self.current_project_name or "Chua co"
        users_count = len(self.get_input_lines())
        results_count = len(self.current_results)

        parts = [
            f"Project: {project_label}",
            f"Users: {users_count}",
            f"Ket qua: {results_count}",
        ]

        if self.current_project_name and self.project_dirty:
            parts.append("Chua luu")

        if extra_note:
            parts.append(extra_note)

        self.summary_var.set(" | ".join(parts))


def main() -> None:
    root = tk.Tk()
    CheckFollowApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
