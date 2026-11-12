"""统一的认证对话框：解锁 / 找回 / 设置 / 改密码。

设计目标
--------
把原本分散的「解锁密码框」和「新建密码框」合并成**一个**窗口，
内部用视图切换，而不是弹一堆不同的对话框。四种用途共用同一套
视觉语言（圆角输入框、暗色主题、链接按钮）。

::

    unlock   [🔒 输入密码 ............ 👁]  ← 默认视图
             忘记密码？                    ← 链接按钮，切到 recover
             [取消]           [解锁]

    recover  [🔑 输入恢复码 ..........]     ← 16 位，自动格式化
             返回                        ← 链接按钮，切回 unlock
             [取消]           [重置密码]

    setup    [🔒 设置密码 ............ 👁]
             ●●●○○ 较强
             [🔒 再输一次 ............ 👁]
             ⚠ 密码不会保存，忘记无法找回
             [取消]           [下一步]   ← 下一步展示恢复码

    setup2   [恢复码已生成，请立即抄下]
             3Rxh-b0NY-V6kW-tw5B        ← 等宽大字，可选中
             [复制]
             □ 我已妥善保存这个恢复码
             [上一步]           [完成]

    change   [🔒 当前密码 ............]
             [🔒 新密码 ..............]
             ●●●○○ 较强
             [🔒 确认新密码 ..........]
             [取消]           [修改]

    reset    （用恢复码验证后）
             [🔒 新密码 ..............]
             [🔒 确认新密码 ..........]
             [取消]           [重置]
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Callable

from . import crypto, ui

MIN_PASSWORD_LEN = 6


# ---------------------------------------------------------------- 密码强度
def password_strength(password: str) -> tuple[int, str, str]:
    """返回 (0-4 等级, 文案, 颜色)。

    评分按「长度优先」：对离线暴力破解，长度比符号复杂度更有效。
    门槛 6 位（用户要求），12 位起算较强。
    """
    n = len(password)
    if n == 0:
        return 0, "", ui.FG_DIM
    if n < MIN_PASSWORD_LEN:
        return 1, f"太短（至少 {MIN_PASSWORD_LEN} 位）", ui.FG_DANGER
    if n < 10:
        return 2, "一般", "#e0a030"
    if n < 14:
        return 3, "较强", "#5fbf5f"
    return 4, "很强", "#3fb950"


# ---------------------------------------------------------------- 链接按钮
class LinkButton(tk.Label):
    """文字链接按钮（模仿登录页的「忘记密码？」）。

    默认用强调色，hover 时加下划线，点击触发回调。
    """

    def __init__(self, parent: tk.Misc, text: str,
                 command: Callable[[], None], *,
                 bg: str | None = None, color: str | None = None):
        base_bg = bg or ui.BG_APP
        base_fg = color or ui.FG_ACCENT
        super().__init__(parent, text=text, bg=base_bg, fg=base_fg,
                         font=ui._ui_font(ui.FS_HINT), cursor="hand2",
                         bd=0, highlightthickness=0)
        self._fg = base_fg
        self.bind("<Enter>", lambda _e: self.configure(font=(
            ui.FONT_FAMILY, ui.FS_HINT, "underline")))
        self.bind("<Leave>", lambda _e: self.configure(font=(
            ui.FONT_FAMILY, ui.FS_HINT, "normal")))
        self.bind("<Button-1>", lambda _e: command())


# ---------------------------------------------------------------- 主对话框
class AuthDialog(ui.SafeToplevel):
    """统一认证对话框。

    通过 `purpose` 决定初始视图：
    - ``"unlock"``         解锁已有文件（可跳到找回）
    - ``"setup"``          首次设置密码 + 生成恢复码
    - ``"change"``         修改密码（需要当前密码）
    - ``"confirm_master"`` 加密前确认通用密码（可切「使用独立密码」）

    结果放在 `self.result`：
    - unlock         : {"password": str}
    - setup          : {"password": str, "recovery_code": str}
    - change         : {"old_password": str, "new_password": str,
                        "recovery_code": str | None}
    - confirm_master : {"master_password": str, "independent": bool}
    """

    WIDTH = 500

    def __init__(self, parent: tk.Misc, purpose: str, *,
                 filename: str = "",
                 on_verify_password: Callable[[str], str | None] | None = None,
                 on_verify_recovery: Callable[[str], str | None] | None = None,
                 on_apply_change: Callable[[str, str, str | None], str | None] | None = None,
                 on_confirm_master: Callable[[str], str | None] | None = None,
                 fixed_recovery_code: str | Callable[[], str] | None = None,
                 allow_recovery: bool = True):
        super().__init__(parent)
        self.resizable(False, False)
        self.configure(bg=ui.BG_APP)

        _TITLES = {
            "unlock": "解锁加密文本",
            "setup": "新建加密文本",
            "change": "修改密码",
            "confirm_master": "确认密码",
        }
        self.title(_TITLES.get(purpose, "加密文本"))

        try:
            if parent.winfo_viewable():
                self.transient(parent)
        except tk.TclError:
            pass

        self._purpose = purpose
        self._filename = filename
        self._on_verify_password = on_verify_password
        self._on_verify_recovery = on_verify_recovery
        self._on_apply_change = on_apply_change
        self._on_confirm_master = on_confirm_master
        self._fixed_recovery_code = fixed_recovery_code
        self._allow_recovery = allow_recovery
        self._independent = False

        self.result: dict | None = None
        self._error_var = tk.StringVar()
        # 错误文字变长时自动调整窗口高度，避免按钮被裁掉
        self._error_var.trace_add(
            "write", lambda *_: self._grow_to_fit())
        self._view = ""
        # 找回 / 重置流程中暂存已通过验证的恢复码
        self._verified_code: str | None = None
        # setup 流程中暂存密码与恢复码
        self._pending_password: str | None = None
        self._pending_code: str | None = None

        self._body = tk.Frame(self, bg=ui.BG_APP, padx=30, pady=26)
        self._body.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())

        self._switch(purpose)

        self.update_idletasks()
        self._fit()
        self._enable_autosize()

        ui._apply_win11_chrome(self)
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after_safe(150, self._clear_topmost)
        self.grab_set()

        self._focus_first()
        self.after_safe(0, self._focus_first)
        self.after_safe(60, self._focus_first)
        self.after_safe(200, self._focus_first)
        self.bind("<Map>", lambda _e: self._focus_first(), add="+")
        self.bind("<FocusIn>", lambda _e: self._focus_first(), add="+")

    # ------------------------------------------------------------ 布局
    def _fit(self) -> None:
        """按当前内容重新计算窗口尺寸并居中。

        只设宽度，**高度交给内容自适应**（见 `_enable_autosize`）。
        这样错误提示变长时窗口会长高，按钮不会被裁掉。
        """
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), self.WIDTH)
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _grow_to_fit(self) -> None:
        """内容变高时把窗口同步撑高（只增不减，避免抖动）。"""
        try:
            if not self.winfo_exists():
                return
            self.update_idletasks()
            need = self.winfo_reqheight()
            cur_h = self.winfo_height()
            if need > cur_h:
                cur_w = self.winfo_width()
                self.geometry(f"{cur_w}x{need}")
        except tk.TclError:
            pass

    def _enable_autosize(self) -> None:
        """让窗口高度随内容自动增长。

        为什么需要：错误提示 / 状态文字是动态的。用固定 geometry 时，
        文字从一行变成三行后窗口不变高，底部的「下一步」「完成」等按钮
        会被窗口边缘裁掉一截（能点，但显示不全）。

        做法：监听 `<Configure>`，内容需求高度变大时同步调整窗口高度。
        """
        self._autosize_last_h = 0

        def on_configure(_event=None) -> None:
            try:
                if not self.winfo_exists():
                    return
                need = self.winfo_reqheight()
                if need > self._autosize_last_h:
                    self._autosize_last_h = need
                    cur_w = self.winfo_width()
                    # 只在变高时调整，避免抖动
                    self.geometry(f"{cur_w}x{need}")
            except tk.TclError:
                pass

        self.bind("<Configure>", on_configure, add="+")
        # 内容变化（如错误文字换行）不一定会触发 Configure，
        # 所以再挂一次空闲检查兜底
        self.after_safe(120, on_configure)

    def _clear(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()
        self._error_var.set("")
        self._first_widget: tk.Widget | None = None

    def _focus_first(self) -> None:
        """把初始焦点放到第一个输入框。

        注意：只在「还没切换过视图」时执行。否则每次 FocusIn 都会
        把焦点拽回第一个框，导致回车跳转失效。
        """
        try:
            if not self.winfo_exists():
                return
            if getattr(self, "_focus_locked", False):
                return
            self._focus_locked = True
            ui._force_foreground(self)
            w = getattr(self, "_first_widget", None)
            if w is not None:
                w.focus_force()
                try:
                    ui._focus_hwnd(w.winfo_id())
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 公共部件
    def _title(self, text: str) -> None:
        tk.Label(self._body, text=text, bg=ui.BG_APP, fg=ui.FG_TEXT,
                 font=ui._ui_font(ui.FS_FIELD), anchor="w",
                 justify="left").pack(fill="x")

    def _subtitle(self, text: str) -> None:
        tk.Label(self._body, text=text, bg=ui.BG_APP, fg=ui.FG_MUTED,
                 font=ui._ui_font(ui.FS_HINT), anchor="w",
                 justify="left", wraplength=self.WIDTH - 60).pack(
            fill="x", pady=(6, 0))

    def _label(self, text: str, *, top: int = 16) -> None:
        tk.Label(self._body, text=text, bg=ui.BG_APP, fg=ui.FG_MUTED,
                 font=ui._ui_font(ui.FS_STATUS), anchor="w").pack(
            fill="x", pady=(top, 5))

    def _password_field(self, *, on_return=None, show_strength=False,
                        next_field=None):
        """创建密码输入框。

        `next_field` 用于「回车跳到下一个输入框」：登录类表单的常见习惯，
        避免用户必须用鼠标点击。设为 `"submit"` 表示回车即提交。
        """
        if on_return is None:
            if next_field == "submit":
                on_return = self._current_submit
            elif callable(next_field):
                on_return = next_field

        field = ui.SearchField(self._body, icon=ui.ICON_LOCK,
                               font_size=ui.FS_FIELD, height=42,
                               password=True, on_return=on_return,
                               on_escape=self._cancel)
        field.pack(fill="x")
        if show_strength:
            var = tk.StringVar(value="")
            lbl = tk.Label(self._body, textvariable=var, bg=ui.BG_APP,
                           fg=ui.FG_DIM, font=ui._ui_font(ui.FS_STATUS),
                           anchor="w")
            lbl.pack(fill="x", pady=(6, 0))
            field._strength_var = var          # type: ignore[attr-defined]
            field._strength_label = lbl        # type: ignore[attr-defined]
            field.var.trace_add(
                "write", lambda *_: self._update_strength(field))
        if self._first_widget is None:
            self._first_widget = field.entry
        return field

    def _current_submit(self) -> None:
        """当前视图的提交动作（供回车触发）。"""
        {
            "unlock": self._do_unlock,
            "recover": self._do_verify_code,
            "reset": self._do_reset,
            "setup": self._do_setup_next,
            "change": self._do_change,
        }.get(self._view, lambda: None)()

    def _focus_widget(self, widget: tk.Widget) -> None:
        """把焦点移到指定控件。

        只调 focus_force 不够：SearchField 外层是 Canvas（RoundedSurface），
        Canvas 会截住焦点。需要先把焦点交给 Canvas 的父级链再落到 Entry，
        并且用 Tk 的 focus_set + Win32 SetFocus 双保险。
        """
        try:
            widget.focus_set()
            self.update_idletasks()
            widget.focus_force()
            ui._focus_hwnd(widget.winfo_id())
        except tk.TclError:
            pass

    def _update_strength(self, field) -> None:
        var = getattr(field, "_strength_var", None)
        lbl = getattr(field, "_strength_label", None)
        if var is None:
            return
        level, text, color = password_strength(field.var.get())
        var.set(("●" * level + "○" * (4 - level) + "  " + text) if text else "")
        if lbl is not None:
            lbl.configure(fg=color)

    def _error_label(self) -> None:
        tk.Label(self._body, textvariable=self._error_var, bg=ui.BG_APP,
                 fg=ui.FG_DANGER, font=ui._ui_font(ui.FS_HINT),
                 anchor="w", justify="left",
                 wraplength=self.WIDTH - 60).pack(fill="x", pady=(10, 0))

    def _buttons(self, primary_text: str, primary_cmd,
                 *, secondary_text: str = "取消",
                 secondary_cmd=None) -> None:
        row = tk.Frame(self._body, bg=ui.BG_APP)
        row.pack(fill="x", pady=(20, 0))
        self._primary_btn = ui.RoundButton(
            row, primary_text, primary_cmd, btn_width=112, btn_height=40,
            primary=True, font_size=ui.FS_BTN)
        self._primary_btn.pack(side="right")
        ui.RoundButton(row, secondary_text, secondary_cmd or self._cancel,
                       btn_width=100, btn_height=40,
                       font_size=ui.FS_BTN).pack(side="right", padx=(0, 12))

    def _warn(self, text: str, color: str = "#e0a030") -> None:
        tk.Label(self._body, text=text, bg=ui.BG_APP, fg=color,
                 font=ui._ui_font(ui.FS_STATUS), anchor="w",
                 justify="left", wraplength=self.WIDTH - 60).pack(
            fill="x", pady=(12, 0))

    # ------------------------------------------------------------ 视图：解锁
    def _view_unlock(self) -> None:
        self._clear()
        self._view = "unlock"
        self._title("解锁加密文本")
        if self._filename:
            self._subtitle(f"输入密码以打开：{self._filename}")

        self._label("密码", top=18)
        self._pw = self._password_field(on_return=self._do_unlock)
        self._error_label()

        links = tk.Frame(self._body, bg=ui.BG_APP)
        links.pack(fill="x", pady=(10, 0))
        if self._allow_recovery and self._on_verify_recovery is not None:
            LinkButton(links, "忘记密码？", self._view_recover).pack(side="left")

        self._buttons("解锁", self._do_unlock)
        self._fit()

    def _do_unlock(self) -> None:
        pw = self._pw.var.get()
        if not pw:
            self._error_var.set("请输入密码")
            return
        err = None
        if self._on_verify_password is not None:
            err = self._on_verify_password(pw)
        if err:
            self._error_var.set(err)
            self._pw.entry.select_range(0, "end")
            self._pw.entry.focus_set()
            return
        self.result = {"password": pw}
        self.destroy()

    # ------------------------------------------------------------ 视图：找回
    def _view_recover(self) -> None:
        self._clear()
        self._view = "recover"
        self._title("用恢复码找回")
        self._subtitle(
            "输入创建文件时生成的 16 位恢复码。\n"
            "连字符和空格会自动忽略，大小写敏感。")

        self._label("恢复码", top=18)
        self._rc = self._recovery_field(on_return=self._do_verify_code)
        self._error_label()

        links = tk.Frame(self._body, bg=ui.BG_APP)
        links.pack(fill="x", pady=(10, 0))
        LinkButton(links, "返回密码登录", self._view_unlock).pack(side="left")

        self._buttons("验证", self._do_verify_code)
        self._fit()

    def _recovery_field(self, *, on_return=None):
        field = ui.SearchField(self._body, icon="\uE8D7",
                               font_size=ui.FS_FIELD, height=42,
                               on_return=on_return, on_escape=self._cancel)
        field.pack(fill="x")
        if self._first_widget is None:
            self._first_widget = field.entry
        return field

    def _do_verify_code(self) -> None:
        raw = self._rc.var.get()
        if not crypto.is_valid_recovery_code(raw):
            self._error_var.set(
                f"恢复码应为 {crypto.RECOVERY_LEN} 位字母数字")
            return
        code = crypto.normalize_recovery_code(raw)
        if self._on_verify_recovery is not None:
            err = self._on_verify_recovery(code)
            if err:
                self._error_var.set(err)
                self._rc.entry.select_range(0, "end")
                self._rc.entry.focus_set()
                return
        self._verified_code = code
        self._view_reset()

    # ------------------------------------------------------------ 视图：重置
    def _view_reset(self) -> None:
        self._clear()
        self._view = "reset"
        self._title("设置新密码")
        self._subtitle("恢复码验证通过。为这个文件设置一个新密码。")

        self._label("新密码", top=18)
        self._np1 = self._password_field(show_strength=True)

        self._label("确认新密码", top=12)
        self._np2 = self._password_field(
            on_return=self._current_submit)

        self._error_label()
        self._buttons("重置密码", self._do_reset)
        self._fit()
        self._np1.on_return_bind(lambda: self._focus_widget(self._np2.entry))

    def _do_reset(self) -> None:
        pw1 = self._np1.var.get()
        pw2 = self._np2.var.get()
        if len(pw1) < MIN_PASSWORD_LEN:
            self._error_var.set(f"密码至少 {MIN_PASSWORD_LEN} 位")
            return
        if pw1 != pw2:
            self._error_var.set("两次输入的密码不一致")
            self._np2.entry.select_range(0, "end")
            self._np2.entry.focus_set()
            return
        if self._on_apply_change is not None:
            err = self._on_apply_change("", pw1, self._verified_code)
            if err:
                self._error_var.set(err)
                return
        self.result = {"new_password": pw1,
                       "recovery_code": self._verified_code}
        self.destroy()

    # ------------------------------------------------------------ 视图：确认通用密码
    def _view_confirm_master(self) -> None:
        """加密前确认通用密码。

        与「解锁」视图的区别：
        - 文案是「确认密码」而不是「解锁」
        - 底部多一个「使用独立密码」链接，点了走 setup 流程
        """
        self._clear()
        self._view = "confirm_master"
        self._title("确认密码")
        if self._filename:
            self._subtitle(f"将用通用密码加密：{self._filename}")
        else:
            self._subtitle("将用通用密码加密。")

        self._label("密码", top=18)
        self._cm = self._password_field(on_return=self._do_confirm_master)
        self._error_label()

        links = tk.Frame(self._body, bg=ui.BG_APP)
        links.pack(fill="x", pady=(10, 0))
        LinkButton(links, "使用独立密码", self._switch_to_setup).pack(side="left")

        self._buttons("加密", self._do_confirm_master)
        self._fit()

    def _switch_to_setup(self) -> None:
        """用户选择独立密码 → 切到设置流程。

        必须先验证通用密码：恢复码是被通用密码加密存起来的，
        没有它就取不出恢复码，新文件会没有恢复通道。
        所以这里如果还没验证过，先提示用户输入密码。
        """
        pw = self._cm.var.get()
        if not pw:
            self._error_var.set(
                "请先输入通用密码 —— 恢复码由它保管，"
                "独立密码的文件也要用同一个恢复码。")
            self._cm.entry.focus_set()
            return
        if self._on_confirm_master is not None:
            err = self._on_confirm_master(pw)
            if err:
                self._error_var.set(err)
                self._cm.entry.select_range(0, "end")
                self._cm.entry.focus_set()
                return
        self._independent = True
        self._view_setup()

    def _do_confirm_master(self) -> None:
        pw = self._cm.var.get()
        if not pw:
            self._error_var.set("请输入密码")
            return
        err = None
        if self._on_confirm_master is not None:
            err = self._on_confirm_master(pw)
        if err:
            self._error_var.set(err)
            self._cm.entry.select_range(0, "end")
            self._cm.entry.focus_set()
            return
        self.result = {"master_password": pw, "independent": False}
        self.destroy()

    # ------------------------------------------------------------ 视图：设置
    def _view_setup(self) -> None:
        self._clear()
        self._view = "setup"
        self._title("设置独立密码" if self._independent else "设置密码")
        if self._filename:
            self._subtitle(f"为「{self._filename}」设置密码和恢复码。")
        if self._independent:
            self._warn(
                "⚠ 独立密码只对这个文件生效，不会成为通用密码。\n"
                "   恢复码仍是通用的那一个。", ui.FG_MUTED)

        self._label("密码", top=18)
        self._sp1 = self._password_field(show_strength=True)

        self._label("确认密码", top=12)
        # 回车时若密码框为空则不动，否则跳到确认框
        self._sp2 = self._password_field(
            on_return=self._do_setup_next)

        self._warn("⚠ 密码不会保存在任何地方，忘记后只能靠恢复码。")
        self._error_label()
        self._buttons("下一步", self._do_setup_next)
        self._fit()

        # 密码框回车 -> 跳到确认框
        self._sp1.on_return_bind(lambda: self._focus_widget(self._sp2.entry))

    def _do_setup_next(self) -> None:
        pw1 = self._sp1.var.get()
        pw2 = self._sp2.var.get()
        if len(pw1) < MIN_PASSWORD_LEN:
            self._error_var.set(f"密码至少 {MIN_PASSWORD_LEN} 位")
            return
        if pw1 != pw2:
            self._error_var.set("两次输入的密码不一致")
            self._sp2.entry.select_range(0, "end")
            self._sp2.entry.focus_set()
            return
        self._pending_password = pw1

        if self._independent:
            # 独立密码：恢复码沿用**已存在**的通用恢复码。
            #
            # 关键：**不要**再走「请保存你的恢复码」那一页。
            # 恢复码没变，用户早在首次设置时抄过了；再展示一遍就是
            # 无谓的重复暴露（用户实测反馈过这个问题）。
            # 这里直接取到恢复码就完成。
            if callable(self._fixed_recovery_code):
                self._pending_code = self._fixed_recovery_code()
            else:
                self._pending_code = self._fixed_recovery_code or ""
            if not self._pending_code:
                self._error_var.set(
                    "无法取得通用恢复码，请先用通用密码加密一次，"
                    "或改用通用密码。")
                return
            # 跳过恢复码展示页，直接产出结果
            self.result = {"password": self._pending_password,
                           "recovery_code": self._pending_code,
                           "independent": True}
            self.destroy()
            return

        self._pending_code = crypto.generate_recovery_code()
        self._view_setup_recovery()

    def _view_setup_recovery(self) -> None:
        self._clear()
        self._view = "setup_recovery"
        self._title("请保存你的恢复码")
        self._subtitle(
            "忘记密码时，这是唯一的找回方式。\n"
            "它和密码同等重要，请立刻抄下来。")

        code = self._pending_code or ""
        shown = crypto.format_recovery_code(code)

        box = ui.RoundedSurface(self._body, fill=ui.BG_INPUT,
                                radius=ui.R_FIELD, height=64)
        box.pack(fill="x", pady=(18, 0))
        lbl = tk.Label(box, text=shown, bg=ui.BG_INPUT, fg=ui.FG_ACCENT,
                       font=("Consolas", 19, "bold"))
        lbl.place(relx=0.5, rely=0.5, anchor="center")

        row = tk.Frame(self._body, bg=ui.BG_APP)
        row.pack(fill="x", pady=(10, 0))
        ui.RoundButton(row, "复制恢复码", self._copy_code,
                       btn_width=110, btn_height=32,
                       font_size=ui.FS_HINT).pack(side="left")
        self._copy_hint = tk.StringVar(value="")
        tk.Label(row, textvariable=self._copy_hint, bg=ui.BG_APP,
                 fg="#5fbf5f", font=ui._ui_font(ui.FS_STATUS)).pack(
            side="left", padx=(10, 0))

        self._confirm_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self._body, text="我已妥善保存这个恢复码",
            variable=self._confirm_var, command=self._update_primary_state,
            bg=ui.BG_APP, fg=ui.FG_TEXT, font=ui._ui_font(ui.FS_HINT),
            activebackground=ui.BG_APP, activeforeground=ui.FG_TEXT,
            selectcolor=ui.BG_INPUT, highlightthickness=0, bd=0,
            cursor="hand2", anchor="w",
        ).pack(fill="x", pady=(14, 0))

        self._error_label()
        self._buttons("完成", self._do_setup_finish,
                      secondary_text="上一步", secondary_cmd=self._view_setup)
        self._update_primary_state()
        self._fit()

    def _update_primary_state(self) -> None:
        btn = getattr(self, "_primary_btn", None)
        if btn is None:
            return
        ok = bool(self._confirm_var.get()) if self._view == "setup_recovery" else True
        btn.set_enabled(ok)

    def _copy_code(self) -> None:
        code = self._pending_code or ""
        try:
            self.clipboard_clear()
            self.clipboard_append(crypto.format_recovery_code(code))
            self.update_idletasks()
            self._copy_hint.set("已复制")
        except tk.TclError:
            self._copy_hint.set("复制失败，请手动抄写")

    def _do_setup_finish(self) -> None:
        if not self._confirm_var.get():
            self._error_var.set("请先确认已保存恢复码")
            return
        self.result = {"password": self._pending_password,
                       "recovery_code": self._pending_code,
                       "independent": bool(self._independent)}
        self.destroy()

    # ------------------------------------------------------------ 视图：改密码
    def _view_change(self) -> None:
        self._clear()
        self._view = "change"
        self._title("修改密码")
        if self._filename:
            self._subtitle(f"为「{self._filename}」设置新密码。")

        self._label("当前密码", top=18)
        self._cp = self._password_field()

        self._label("新密码", top=12)
        self._np1 = self._password_field(show_strength=True)

        self._label("确认新密码", top=12)
        self._np2 = self._password_field(
            on_return=self._current_submit)

        self._error_label()
        self._buttons("修改", self._do_change)
        self._fit()
        self._cp.on_return_bind(lambda: self._focus_widget(self._np1.entry))
        self._np1.on_return_bind(lambda: self._focus_widget(self._np2.entry))

    def _do_change(self) -> None:
        old = self._cp.var.get()
        new1 = self._np1.var.get()
        new2 = self._np2.var.get()

        if not old:
            self._error_var.set("请输入当前密码")
            return
        if len(new1) < MIN_PASSWORD_LEN:
            self._error_var.set(f"新密码至少 {MIN_PASSWORD_LEN} 位")
            return
        if new1 != new2:
            self._error_var.set("两次输入的新密码不一致")
            self._np2.entry.select_range(0, "end")
            self._np2.entry.focus_set()
            return
        if new1 == old:
            self._error_var.set("新密码不能与当前密码相同")
            return

        if self._on_apply_change is not None:
            err = self._on_apply_change(old, new1, None)
            if err:
                self._error_var.set(err)
                return
        self.result = {"old_password": old, "new_password": new1,
                       "recovery_code": None}
        self.destroy()

    # ------------------------------------------------------------ 分发
    def _switch(self, view: str) -> None:
        {
            "unlock": self._view_unlock,
            "recover": self._view_recover,
            "setup": self._view_setup,
            "change": self._view_change,
            "confirm_master": self._view_confirm_master,
        }.get(view, self._view_unlock)()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


# ---------------------------------------------------------------- 便捷函数
def ask_unlock(*, filename: str,
               verify: Callable[[str], str | None],
               verify_recovery: Callable[[str], str | None] | None = None,
               apply_reset: Callable[[str, str, str | None], str | None] | None = None,
               ) -> dict | None:
    """弹出解锁窗口。返回 {"password": str} 或改密码后的结果。"""
    root = tk.Tk()
    root.withdraw()
    dlg = AuthDialog(root, "unlock", filename=filename,
                     on_verify_password=verify,
                     on_verify_recovery=verify_recovery,
                     on_apply_change=apply_reset)
    root.wait_window(dlg)
    root.destroy()
    return dlg.result


def ask_setup(*, filename: str,
              independent: bool = False,
              fixed_recovery_code: str | None = None) -> dict | None:
    """弹出首次设置窗口。

    返回 {"password", "recovery_code", "independent"}。
    `independent=True` 时文案是「设置独立密码」，且恢复码用
    `fixed_recovery_code`（通用恢复码），不再生成新的。
    """
    root = tk.Tk()
    root.withdraw()
    dlg = AuthDialog(root, "setup", filename=filename,
                     fixed_recovery_code=fixed_recovery_code)
    if independent:
        # 直接以独立模式打开
        dlg._independent = True
        dlg._view_setup()
    root.wait_window(dlg)
    root.destroy()
    if dlg.result is None:
        return None
    dlg.result["independent"] = independent or bool(
        getattr(dlg, "_independent", False))
    return dlg.result


def ask_confirm_master(*, filename: str,
                       verify: Callable[[str], str | None],
                       fixed_recovery_code: str,
                       ) -> dict | None:
    """加密前确认通用密码。

    返回 {"master_password": str, "independent": False}
    或（用户点了「使用独立密码」）{"password", "recovery_code",
    "independent": True}。
    """
    root = tk.Tk()
    root.withdraw()
    dlg = AuthDialog(root, "confirm_master", filename=filename,
                     on_confirm_master=verify,
                     fixed_recovery_code=fixed_recovery_code)
    root.wait_window(dlg)
    root.destroy()
    return dlg.result


def ask_change(*, filename: str,
               apply_change: Callable[[str, str, str | None], str | None],
               ) -> dict | None:
    """弹出改密码窗口。"""
    root = tk.Tk()
    root.withdraw()
    dlg = AuthDialog(root, "change", filename=filename,
                     on_apply_change=apply_change)
    root.wait_window(dlg)
    root.destroy()
    return dlg.result



