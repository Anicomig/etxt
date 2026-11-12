"""保存位置选择弹窗。

需求（用户确认）
---------------
- 双击 exe / 菜单新建 → 先选保存位置
- 弹窗包含**默认位置**和**自定义位置**两种选择
- 默认位置用 API 取 Documents，不能硬编码（本机 Documents 重定向到 F 盘）

设计要点
--------
- 文件名与目录分开呈现，文件名预填并选中主名部分（方便直接改）
- 两个单选：使用默认位置 / 自定义位置
- 「浏览…」只在选自定义时可用
- 实时校验：目录存在、可写、无同名冲突 → 决定「下一步」是否可用
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from . import ui


def default_documents_dir() -> Path:
    """取系统「文档」目录。

    不能硬编码 `%USERPROFILE%\\Documents`：本机 Documents 被重定向到
    F 盘，实测 `SHGetKnownFolderPath(FOLDERID_Documents)` 返回
    `<用户的文档目录>`。
    """
    # 首选 SHGetKnownFolderPath（正确处理重定向）
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Documents
        u = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
        g = GUID()
        g.Data1 = u.time_low
        g.Data2 = u.time_mid
        g.Data3 = u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b

        p = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(g), 0, None, ctypes.byref(p))
        if hr == 0 and p.value:
            path = Path(p.value)
            ctypes.windll.ole32.CoTaskMemFree(p)
            if path.is_dir():
                return path
    except Exception:
        pass

    # 退回 .NET API
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetFolderPath('MyDocuments')"],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000)
        s = (out.stdout or "").strip()
        if s and Path(s).is_dir():
            return Path(s)
    except Exception:
        pass

    return Path.home() / "Documents"


def _is_writable_dir(path: Path) -> bool:
    """目录存在且可写。"""
    try:
        if not path.is_dir():
            return False
        probe = path / f".etxt-write-test-{os.getpid()}"
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("x")
        probe.unlink()
        return True
    except OSError:
        return False


class SaveLocationDialog(ui.SafeToplevel):
    """选择新文件的保存位置。

    结果：
        self.result = Path 或 None
    """

    WIDTH = 560

    def __init__(self, parent: tk.Misc, *,
                 title: str = "新建加密文件",
                 initial_name: str = "新建加密文本.etxt",
                 initial_dir: Path | None = None,
                 filetypes: list[tuple[str, str]] | None = None):
        super().__init__(parent)
        self.resizable(False, False)
        self.configure(bg=ui.BG_APP)
        self.title(title)

        try:
            if parent.winfo_viewable():
                self.transient(parent)
        except tk.TclError:
            pass

        self.result: Path | None = None
        self._default_dir = (initial_dir or default_documents_dir()).resolve()
        self._filetypes = filetypes or [("加密文本", "*.etxt")]
        self._status_var = tk.StringVar()
        # 状态文字变长时自动撑高窗口
        self._status_var.trace_add(
            "write", lambda *_: self._grow_to_fit())

        self._mode = tk.StringVar(value="default")   # default | custom
        self._dir_var = tk.StringVar(value=str(self._default_dir))

        body = tk.Frame(self, bg=ui.BG_APP, padx=30, pady=26)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=title, bg=ui.BG_APP, fg=ui.FG_TEXT,
                 font=ui._ui_font(ui.FS_FIELD), anchor="w").pack(fill="x")

        # ---------------- 文件名
        tk.Label(body, text="文件名", bg=ui.BG_APP, fg=ui.FG_MUTED,
                 font=ui._ui_font(ui.FS_STATUS), anchor="w").pack(
            fill="x", pady=(18, 5))

        name_field = ui.SearchField(body, icon="\uE8A5",
                                    font_size=ui.FS_FIELD, height=40)
        name_field.pack(fill="x")
        name_field.var.set(initial_name)
        name_field.var.trace_add("write", lambda *_: self._validate())
        self._name_field = name_field
        self._name_entry = name_field.entry
        # 关键：让 `_name_var` 指向输入框真正使用的变量。
        # 曾经这里另建了一个 StringVar，导致用户改文件名时校验读到的
        # 永远是初始值，同名冲突无法消除、「下一步」一直灰着。
        self._name_var = name_field.var
        # 只选中主名部分，方便直接改名而不破坏扩展名
        self.after(50, self._select_stem)

        # ---------------- 保存位置
        tk.Label(body, text="保存到", bg=ui.BG_APP, fg=ui.FG_MUTED,
                 font=ui._ui_font(ui.FS_STATUS), anchor="w").pack(
            fill="x", pady=(16, 5))

        dir_row = tk.Frame(body, bg=ui.BG_APP)
        dir_row.pack(fill="x")

        self._dir_field = ui.SearchField(dir_row, icon="\uE8B7",
                                          font_size=ui.FS_HINT, height=38)
        self._dir_field.pack(side="left", fill="x", expand=True)
        self._dir_field.var.set(str(self._default_dir))
        self._dir_field.var.trace_add("write", lambda *_: self._validate())
        self._dir_entry = self._dir_field.entry
        # 禁用态要用暗色，Tk 默认会用系统灰白（与暗色主题冲突）
        self._dir_entry.configure(
            disabledbackground=ui.BG_INPUT, disabledforeground=ui.FG_MUTED,
            readonlybackground=ui.BG_INPUT)

        self._browse_btn = ui.RoundButton(
            dir_row, "浏览…", self._browse, btn_width=84, btn_height=38,
            font_size=ui.FS_BTN)
        self._browse_btn.pack(side="left", padx=(10, 0))

        # ---------------- 模式单选
        mode_row = tk.Frame(body, bg=ui.BG_APP)
        mode_row.pack(fill="x", pady=(12, 0))

        cb_kw = dict(bg=ui.BG_APP, fg=ui.FG_TEXT, font=ui._ui_font(ui.FS_HINT),
                     activebackground=ui.BG_APP, activeforeground=ui.FG_TEXT,
                     selectcolor=ui.BG_INPUT, highlightthickness=0, bd=0,
                     cursor="hand2", anchor="w")
        tk.Radiobutton(mode_row, text="使用默认位置（文档）",
                       variable=self._mode, value="default",
                       command=self._on_mode_change, **cb_kw).pack(side="left")
        tk.Radiobutton(mode_row, text="自定义位置",
                       variable=self._mode, value="custom",
                       command=self._on_mode_change, **cb_kw).pack(
            side="left", padx=(18, 0))

        # ---------------- 状态提示
        self._status_label = tk.Label(
            body, textvariable=self._status_var, bg=ui.BG_APP,
            fg=ui.FG_MUTED, font=ui._ui_font(ui.FS_STATUS),
            anchor="w", justify="left", wraplength=self.WIDTH - 60)
        self._status_label.pack(fill="x", pady=(12, 0))

        # ---------------- 按钮
        btns = tk.Frame(body, bg=ui.BG_APP)
        btns.pack(fill="x", pady=(18, 0))
        self._ok = ui.RoundButton(btns, "下一步", self._confirm,
                                  btn_width=112, btn_height=40, primary=True,
                                  font_size=ui.FS_BTN)
        self._ok.pack(side="right")
        ui.RoundButton(btns, "取消", self._cancel, btn_width=100,
                       btn_height=40, font_size=ui.FS_BTN).pack(
            side="right", padx=(0, 12))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._confirm())

        self._on_mode_change()
        self.update_idletasks()
        self._center(parent)
        ui._apply_win11_chrome(self)
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after_safe(150, self._clear_topmost)
        self.after_safe(80, self._focus_name)
        self.grab_set()

    # ------------------------------------------------------------ 行为
    def _select_stem(self) -> None:
        """选中文件名的主体部分，保留扩展名不被选中。"""
        name = self._name_entry.get()
        stem_len = len(name) - len(Path(name).suffix)
        self._name_entry.selection_range(0, stem_len)
        self._name_entry.icursor(stem_len)

    def _focus_name(self) -> None:
        try:
            ui._force_foreground(self)
            self._name_entry.focus_force()
            ui._focus_hwnd(self._name_entry.winfo_id())
            self._select_stem()
        except tk.TclError:
            pass

    def _on_mode_change(self) -> None:
        custom = self._mode.get() == "custom"
        self._dir_entry.configure(state="normal" if custom else "disabled")
        self._browse_btn.set_enabled(custom)
        if not custom:
            self._dir_field.var.set(str(self._default_dir))
        self._validate()

    def _browse(self) -> None:
        try:
            chosen = filedialog.askdirectory(
                parent=self, title="选择保存位置",
                initialdir=self._dir_field.var.get() or str(self._default_dir))
        except tk.TclError:
            return
        if chosen:
            self._dir_field.var.set(chosen)
            self._mode.set("custom")
            self._on_mode_change()

    def _target(self) -> Path | None:
        """解析目标路径；无效时返回 None。"""
        name = self._name_var.get().strip()
        if not name:
            return None
        # 补扩展名
        if not Path(name).suffix:
            name += ".etxt"
        d = self._dir_field.var.get().strip()
        if not d:
            return None
        try:
            return Path(d) / name
        except (OSError, ValueError):
            return None

    def _validate(self) -> bool:
        """校验并更新状态提示 + 「下一步」可用性。"""
        name = self._name_var.get().strip()
        d = self._dir_field.var.get().strip()

        if not name:
            self._set_status("请输入文件名", ui.FG_DANGER, False)
            return False
        if not d:
            self._set_status("请选择保存位置", ui.FG_DANGER, False)
            return False

        try:
            dir_path = Path(d)
        except (OSError, ValueError):
            self._set_status("路径无效", ui.FG_DANGER, False)
            return False

        if not dir_path.is_dir():
            self._set_status(f"目录不存在：{dir_path}", ui.FG_DANGER, False)
            return False

        if not _is_writable_dir(dir_path):
            self._set_status(f"目录不可写：{dir_path}", ui.FG_DANGER, False)
            return False

        target = self._target()
        if target is None:
            self._set_status("路径无效", ui.FG_DANGER, False)
            return False

        if target.exists():
            self._set_status(f"文件已存在，请改名：{target.name}",
                             ui.FG_DANGER, False)
            return False

        self._set_status(f"将保存到：{target}", ui.FG_MUTED, True)
        return True

    def _set_status(self, text: str, color: str, ok: bool) -> None:
        self._status_var.set(text)
        self._status_label.configure(fg=color)
        self._ok.set_enabled(ok)

    def _confirm(self) -> None:
        if not self._validate():
            return
        self.result = self._target()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _center(self, parent: tk.Misc) -> None:
        w = max(self.winfo_reqwidth(), self.WIDTH)
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")


def ask_save_location(*, title: str = "新建加密文件",
                      initial_name: str = "新建加密文本.etxt",
                      initial_dir: Path | None = None) -> Path | None:
    """弹出保存位置选择框，返回目标路径或 None。"""
    root = tk.Tk()
    root.withdraw()
    dlg = SaveLocationDialog(root, title=title, initial_name=initial_name,
                             initial_dir=initial_dir)
    root.wait_window(dlg)
    root.destroy()
    return dlg.result
