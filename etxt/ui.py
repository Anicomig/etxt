"""tkinter 界面：Win11 记事本暗色主题 + 密码框 + 内置编辑器 + 查找替换。

设计目标（对齐 Win11 记事本 11.2607 暗色模式）：
- 背景 #202020 / 栏位 #272727 / 输入 #2d2d2d
- 强调色 #4cc2ff
- 字体 Microsoft YaHei UI（与记事本一致；不用等宽，消除锯齿感）
- 窗口圆角：DWM DWMWA_WINDOW_CORNER_PREFERENCE
- 输入框 / 按钮圆角：**PIL 超采样渲染**（Tk 的 create_polygon 不做抗锯齿，
  小半径下看起来像「剪掉四个角」，必须走位图）

功能：
- 顶部菜单：文件 / 编辑 / 查看（仿记事本）
- Ctrl+S 保存并加密 / Ctrl+W 关闭
- Ctrl+F 查找、Ctrl+H 替换、F3 / Shift+F3 导航
- Ctrl+滚轮、Ctrl+= / Ctrl+- / Ctrl+0 缩放
- Ctrl+Shift+W 切换自动换行、Ctrl+Shift+S 切换状态栏

**没有任何明文落盘路径。** 文本只存在于 tkinter Text 控件里。
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw, ImageTk

from . import crypto
from . import settings as _settings

# ---------------- 主题 ----------------
BG_APP = "#202020"
BG_EDITOR = "#202020"
BG_CHROME = "#272727"
BG_BAR = "#242424"
BG_MENU = "#2b2b2b"
BG_INPUT = "#2d2d2d"
BG_HOVER = "#333333"
FG_TEXT = "#ffffff"
FG_MUTED = "#9d9d9d"
FG_DIM = "#6e6e6e"
FG_ACCENT = "#4cc2ff"
FG_DANGER = "#ff99a4"
BORDER = "#333333"
SELECT_BG = "#2c5d84"
FIND_ALL = "#4a4420"
FIND_CUR = "#7a6a00"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_SIZE = 11
MIN_FONT, MAX_FONT = 7, 40

ICON_FONT = "Segoe Fluent Icons"
ICON_SEARCH = "\uE721"
ICON_UP = "\uE70E"
ICON_DOWN = "\uE70D"
ICON_CLOSE = "\uE711"
ICON_CASE = "\uE8A1"
ICON_REPLACE = "\uE8AC"
ICON_LOCK = "\uE72E"
ICON_EYE = "\uE7B3"       # View / 睁眼：表示「当前已显示明文」
ICON_EYE_HIDE = "\uED1A"  # Hide / 闭眼带斜线：表示「当前已隐藏」

# 圆角半径（统一栅格）
R_FIELD = 8      # 输入框
R_BTN = 6        # 小图标按钮
R_BIG = 8        # 文字按钮

# 字号规范（对齐 Win11 记事本的视觉层级）
FS_MENU = 10       # 顶部菜单
FS_TITLE = 10      # 路径行
FS_BODY = 11       # 正文
FS_FIELD = 12      # 输入框（密码 / 查找）
FS_BTN = 11        # 按钮文字（本轮加大：9/10 → 11）
FS_STATUS = 9      # 状态栏
FS_HINT = 10       # 提示文字

# ---------------- Win32 / DWM ----------------
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_ROUND = 2


def _apply_win11_chrome(win: tk.Misc) -> None:
    """暗色标题栏 + 圆角 + 边框色。失败静默降级。"""
    if not sys.platform.startswith("win"):
        return
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        # 必须用 GetParent 拿顶层 HWND：winfo_id() 是子窗口，
        # DwmSetWindowAttribute 会返回 0x80070057（无效参数）。
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi

        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
                                  ctypes.byref(dark), 4)
        corner = ctypes.c_int(_DWMWCP_ROUND)
        dwm.DwmSetWindowAttribute(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
                                  ctypes.byref(corner), 4)
        color = ctypes.c_int(0x00333333)
        dwm.DwmSetWindowAttribute(hwnd, _DWMWA_BORDER_COLOR,
                                  ctypes.byref(color), 4)
    except Exception:
        pass


def _ui_font(size: int = FONT_SIZE, weight: str = "normal") -> tuple:
    return (FONT_FAMILY, size, weight)


def _force_foreground(win: tk.Misc) -> bool:
    """把窗口强制切到前台并让指定控件拿到真实键盘焦点。

    为什么必须这么做
    ----------------
    本机 `SPI_GETFOREGROUNDLOCKTIMEOUT` 实测为 `0x7FFFFFFF`
    （2147483647ms = 永久前台锁）。在这种设置下，后台进程调用
    `SetForegroundWindow` 会被 Windows 静默忽略，Tk 的
    `focus_force()` 只改 Tk 内部状态，真实键盘焦点仍在原来的窗口上
    —— 表现就是「密码框弹出来了，但直接打字没反应」。

    标准绕过手法（微软文档认可的 AttachThreadInput 组合）：
      1. 取当前前台窗口所在线程 id
      2. 取目标窗口所在线程 id
      3. AttachThreadInput 把两个输入队列临时合并
      4. 合并期间 SetForegroundWindow / BringWindowToTop / SetFocus 才生效
      5. 立刻 Detach，避免影响其他窗口的输入处理

    返回 True 表示调用链走完（不代表系统一定接受，所以上层仍会重试）。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        win.update_idletasks()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        if not hwnd:
            return False

        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return True

        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        my_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached = []
        for tid in (fg_thread, target_thread):
            if tid and tid != my_thread:
                if user32.AttachThreadInput(my_thread, tid, True):
                    attached.append(tid)

        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
        finally:
            for tid in attached:
                user32.AttachThreadInput(my_thread, tid, False)

        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _focus_hwnd(hwnd: int) -> None:
    """把系统级键盘焦点设到指定子窗口（Entry 的 HWND）。"""
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.user32.SetFocus(hwnd)
    except Exception:
        pass


def _bg_of(widget: tk.Misc) -> str:
    try:
        return widget.cget("bg")
    except tk.TclError:
        return BG_BAR


class SafeToplevel(tk.Toplevel):
    """自动清理挂起 `after` 回调的 Toplevel。

    为什么需要
    ----------
    对话框常用 `self.after(150, lambda: ...)` 做「稍后再设一次属性」
    之类的操作。如果窗口在那之前就被 `destroy()`（用户点取消、
    或程序连续弹多个对话框），Tk 会执行一个已失效的 lambda，报：

        invalid command name "2640278465472<lambda>"
        while executing "2640278465472<lambda>"

    这个错误会污染当前 Tcl 解释器，导致**后续创建窗口时偶发**
    `Can't find a usable tk.tcl` —— 实测连续弹 4 个保存对话框就会复现。

    解决：所有 `after()` 走 `self.after_safe()` 登记，销毁时统一取消。
    """

    def __init__(self, parent: tk.Misc, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self._after_ids: list[str] = []

    def after_safe(self, ms: int, fn) -> str:
        """登记一个可取消的延迟回调。"""
        aid = self.after(ms, fn)
        try:
            self._after_ids.append(aid)
        except AttributeError:
            self._after_ids = [aid]
        return aid

    def cancel_afters(self) -> None:
        for aid in getattr(self, "_after_ids", []):
            try:
                self.after_cancel(aid)
            except tk.TclError:
                pass
        self._after_ids = []

    def _clear_topmost(self) -> None:
        """取消置顶（延迟执行，等窗口真正显示出来）。"""
        try:
            if self.winfo_exists():
                self.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _grow_to_fit(self) -> None:
        """内容变高时把窗口同步撑高（只增不减，避免抖动）。

        为什么需要：对话框里常有动态文本（错误提示、状态说明）。
        用固定 geometry 时，文字从一行变三行后窗口不变高，
        底部按钮会被窗口边缘裁掉一截 —— 能点，但显示不全。
        """
        try:
            if not self.winfo_exists():
                return
            self.update_idletasks()
            need = self.winfo_reqheight()
            if need > self.winfo_height():
                self.geometry(f"{self.winfo_width()}x{need}")
        except tk.TclError:
            pass

    def destroy(self) -> None:
        self.cancel_afters()
        try:
            super().destroy()
        except tk.TclError:
            pass


# ---------------- 抗锯齿圆角位图 ----------------
class _RoundArt:
    """用 PIL 以 4 倍超采样渲染圆角矩形，再降采样得到抗锯齿边缘。

    为什么不用 Canvas 的 create_polygon：Tk 的 canvas 图元**不做抗锯齿**，
    半径 6-8px 时四个角会呈现明显的「斜切」台阶，看起来就像
    长方形被剪掉四个角。位图方案能拿到真正的平滑圆角。

    ⚠️ 缓存必须按 Tk 实例隔离：
    ImageTk.PhotoImage 绑定到创建它的 Tcl 解释器。本程序会先后创建
    多个 `Tk()`（每次弹对话框一个），若缓存跨实例复用，
    第二个窗口会报 `image "pyimage1" doesn't exist`。
    所以 key 里带上 `id(tk_interp)`。
    """

    SS = 4  # supersampling 倍数

    def __init__(self) -> None:
        self._cache: dict[tuple, ImageTk.PhotoImage] = {}

    def photo(self, widget: tk.Misc, w: int, h: int, radius: int,
              fill: str, outline: str | None = None
              ) -> ImageTk.PhotoImage | None:
        if w <= 1 or h <= 1:
            return None
        try:
            interp = widget.tk.interpaddr()
        except (tk.TclError, AttributeError):
            interp = 0
        key = (interp, w, h, radius, fill, outline)
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        ss = self.SS
        W, H = w * ss, h * ss
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        box = [0, 0, W - 1, H - 1]
        r = radius * ss
        if outline:
            d.rounded_rectangle(box, radius=r, fill=fill,
                                outline=outline, width=ss)
        else:
            d.rounded_rectangle(box, radius=r, fill=fill)
        img = img.resize((w, h), Image.LANCZOS)
        ph = ImageTk.PhotoImage(img, master=widget)
        self._cache[key] = ph
        return ph


_ART = _RoundArt()


# ---------------- 暗色滚动条 ----------------
_SB_STYLE = "EtxtDark.Vertical.TScrollbar"


def _init_scrollbar_style(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        _SB_STYLE,
        background="#3c3c3c", troughcolor=BG_EDITOR,
        bordercolor=BG_EDITOR, darkcolor="#3c3c3c", lightcolor="#3c3c3c",
        arrowcolor=FG_MUTED, relief="flat", arrowsize=10,
        width=14, gripcount=0, borderwidth=0,
    )
    style.map(_SB_STYLE,
              background=[("active", "#4d4d4d"), ("pressed", FG_ACCENT)],
              arrowcolor=[("active", FG_TEXT)])
    style.configure(".", background=BG_CHROME, foreground=FG_TEXT,
                    fieldbackground=BG_INPUT, bordercolor=BORDER)
    return style


# =====================================================================
#  圆角容器 / 控件
# =====================================================================
class RoundedSurface(tk.Canvas):
    """抗锯齿圆角矩形背景，子控件用 place() 内缩放置。

    透明角：位图四角是透明像素，画布底色设为父容器底色，
    因此圆角外露出的就是父容器背景，视觉上是真正的圆角。
    """

    def __init__(self, parent: tk.Misc, *, fill: str = BG_INPUT,
                 outline: str | None = None, radius: int = R_FIELD,
                 parent_bg: str | None = None, height: int = 32):
        pb = parent_bg or _bg_of(parent)
        super().__init__(parent, bg=pb, highlightthickness=0, bd=0,
                         height=height)
        self._fill = fill
        self._outline = outline
        self._radius = radius
        self._parent_bg = pb
        self._img_item: int | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event=None) -> None:
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1 or h <= 1:
            return
        ph = _ART.photo(self, w, h, self._radius, self._fill, self._outline)
        if ph is None:
            return
        self._photo = ph  # 必须持引用，否则被 GC 后显示空白
        if self._img_item is None:
            self._img_item = self.create_image(0, 0, image=ph, anchor="nw")
        else:
            self.itemconfigure(self._img_item, image=ph)
            self.coords(self._img_item, 0, 0)

    def set_outline(self, color: str | None) -> None:
        if color != self._outline:
            self._outline = color
            self._redraw()

    def set_fill(self, color: str) -> None:
        if color != self._fill:
            self._fill = color
            self._redraw()

    @property
    def inset(self) -> int:
        return self._radius + 2


class SearchField(RoundedSurface):
    """圆角输入框：左侧图标 + 输入 +（可选）右侧计数。"""

    def __init__(self, parent: tk.Misc, *, icon: str = ICON_SEARCH,
                 font_size: int = 11, height: int = 34,
                 on_change: Callable[[], None] | None = None,
                 on_return: Callable[[], None] | None = None,
                 on_shift_return: Callable[[], None] | None = None,
                 on_escape: Callable[[], None] | None = None,
                 show_count: bool = False,
                 password: bool = False):
        super().__init__(parent, fill=BG_INPUT, outline=None,
                         radius=R_FIELD, height=height)
        self._h = height
        self._password = password
        self._revealed = False

        self.icon_label = tk.Label(self, text=icon, font=(ICON_FONT, 11),
                                   bg=BG_INPUT, fg=FG_DIM, bd=0,
                                   highlightthickness=0)
        self.icon_label.place(x=12, rely=0.5, anchor="w")

        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self, textvariable=self.var, font=_ui_font(font_size),
            bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT,
            relief="flat", bd=0, highlightthickness=0,
        )

        # 右侧留白：计数 / 眼睛按钮 / 无
        right = 12
        if show_count:
            right += 54
        if password:
            right += 34

        self.entry.place(x=36, y=5, relwidth=1, width=-(36 + right),
                         relheight=1, height=-10)

        self.count_label = None
        if show_count:
            self.count_label = tk.Label(self, text="", font=_ui_font(FS_STATUS),
                                        bg=BG_INPUT, fg=FG_DIM,
                                        anchor="e", bd=0, highlightthickness=0)
            self.count_label.place(relx=1.0, x=-(34 if password else 12),
                                   rely=0.5, anchor="e")

        # 密码显隐切换（眼睛图标）
        # 图标语义：显示「当前状态」而不是「点击后的动作」。
        #   掩码状态 -> 闭眼带斜线（表示现在是隐藏的）
        #   明文状态 -> 睁眼（表示现在是可见的）
        self.reveal_btn: IconButton | None = None
        if password:
            self.entry.configure(show="●")
            self.reveal_btn = IconButton(
                self, ICON_EYE_HIDE, self.toggle_reveal, size=28,
                radius=6, parent_bg=BG_INPUT)
            self.reveal_btn.place(relx=1.0, x=-6, rely=0.5, anchor="e")

        # 聚焦时描边变亮（用位图描边，不是矩形框）
        self.entry.bind("<FocusIn>", lambda _e: self.set_outline(FG_ACCENT),
                        add="+")
        self.entry.bind("<FocusOut>", lambda _e: self.set_outline(None),
                        add="+")

        if on_change is not None:
            self.var.trace_add("write", lambda *_: on_change())
        if on_return is not None:
            self.entry.bind("<Return>", lambda _e: on_return())
        if on_shift_return is not None:
            self.entry.bind("<Shift-Return>", lambda _e: on_shift_return())
        if on_escape is not None:
            self.entry.bind("<Escape>", lambda _e: on_escape())

    def toggle_reveal(self) -> None:
        """在「掩码」和「明文」之间切换密码显示。

        图标反映当前状态：
        - 明文可见 -> 睁眼（ICON_EYE）
        - 已隐藏   -> 闭眼带斜线（ICON_EYE_HIDE）
        """
        if not self._password:
            return
        self._revealed = not self._revealed
        self.entry.configure(show="" if self._revealed else "●")
        if self.reveal_btn is not None:
            self.reveal_btn.set_glyph(ICON_EYE if self._revealed else ICON_EYE_HIDE)
            self.reveal_btn.set_active(self._revealed)
        # 保持焦点在输入框，方便继续打字
        self.entry.focus_set()

    @property
    def revealed(self) -> bool:
        return self._revealed

    def on_return_bind(self, handler: Callable[[], None]) -> None:
        """追加一个回车处理器，**替换**掉构造时的那个。

        为什么需要：tkinter 的 bind() 对同一事件是追加，不是替换。
        构造时若已绑定 on_return，后续再 bind("<Return>") 会两个都触发，
        导致「回车跳下一格」和「回车提交」同时发生。
        这里先解绑再加，保证只有一个处理器。
        """
        self.entry.unbind("<Return>")
        self.entry.bind("<Return>", lambda _e: handler())

    def set_count(self, text: str) -> None:
        if self.count_label is not None:
            self.count_label.configure(text=text)


class IconButton(tk.Canvas):
    """圆角图标按钮（Segoe Fluent Icons），hover 显示抗锯齿圆角底。"""

    def __init__(self, parent: tk.Misc, glyph: str,
                 command: Callable[[], None], *, size: int = 32,
                 radius: int = R_BTN, parent_bg: str | None = None):
        pb = parent_bg or _bg_of(parent)
        super().__init__(parent, width=size, height=size, bg=pb,
                         highlightthickness=0, bd=0)
        self._size = size
        self._radius = radius
        self._bg = pb
        self._hover = False
        self._enabled = True
        self._glyph = glyph
        self._command = command
        self._photo: ImageTk.PhotoImage | None = None
        self._bg_item: int | None = None

        self._icon = self.create_text(
            size / 2, size / 2, text=glyph, font=(ICON_FONT, 11),
            fill=FG_MUTED, anchor="center",
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _paint_bg(self) -> None:
        if self._hover and self._enabled:
            ph = _ART.photo(self, self._size, self._size, self._radius, BG_HOVER)
            if ph is not None:
                self._photo = ph
                if self._bg_item is None:
                    self._bg_item = self.create_image(0, 0, image=ph,
                                                      anchor="nw")
                    self.tag_lower(self._bg_item)
                else:
                    self.itemconfigure(self._bg_item, image=ph)
        elif self._bg_item is not None:
            self.delete(self._bg_item)
            self._bg_item = None
            self._photo = None

    def _on_enter(self, _e=None) -> None:
        self._hover = True
        if self._enabled:
            self.itemconfigure(self._icon, fill=FG_TEXT)
        self._paint_bg()

    def _on_leave(self, _e=None) -> None:
        self._hover = False
        self._paint_bg()

    def _on_click(self, _e=None) -> None:
        if self._enabled:
            self._command()

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        self.itemconfigure(self._icon, fill=FG_MUTED if on else FG_DIM)
        if not on:
            self._hover = False
            self._paint_bg()

    def set_active(self, on: bool) -> None:
        self.itemconfigure(self._icon, fill=FG_ACCENT if on else FG_MUTED)

    def set_glyph(self, glyph: str) -> None:
        """切换图标字形（例如密码框的睁眼 / 闭眼）。"""
        self._glyph = glyph
        self.itemconfigure(self._icon, text=glyph)


class RoundButton(tk.Canvas):
    """抗锯齿圆角文字按钮。

    三个 tkinter 命名坑（都实测踩过）：
    1. 参数名不能叫 width/height —— 与 widget 配置参数混淆；
    2. 内部属性不能叫 _w / _h —— Widget 用 self._w 存控件路径名，
       覆盖后 create_text 抛 TclError: invalid command name "72"；
    3. 文字用 10pt normal，与记事本按钮一致；主按钮用 semibold 观感。
    """

    def __init__(self, parent: tk.Misc, text: str,
                 command: Callable[[], None], *, btn_width: int = 76,
                 btn_height: int = 34, radius: int = R_BIG,
                 primary: bool = False, font_size: int = FS_BTN,
                 parent_bg: str | None = None):
        pb = parent_bg or _bg_of(parent)
        super().__init__(parent, width=btn_width, height=btn_height, bg=pb,
                         highlightthickness=0, bd=0)
        self._bw, self._bh, self._br = btn_width, btn_height, radius
        self._bg = FG_ACCENT if primary else BG_INPUT
        self._fg = "#0d1f2b" if primary else FG_TEXT
        self._hover = "#6fd0ff" if primary else BG_HOVER
        self._command = command
        self._hovering = False
        self._enabled = True
        self._photo: ImageTk.PhotoImage | None = None
        self._bg_item: int | None = None

        self._txt = self.create_text(btn_width / 2, btn_height / 2, text=text,
                                     font=_ui_font(font_size), fill=self._fg,
                                     anchor="center")
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", lambda _e: self._on_click())
        self._draw()

    def _draw(self) -> None:
        fill = self._hover if self._hovering else self._bg
        ph = _ART.photo(self, self._bw, self._bh, self._br, fill)
        if ph is None:
            return
        self._photo = ph
        if self._bg_item is None:
            self._bg_item = self.create_image(0, 0, image=ph, anchor="nw")
            self.tag_lower(self._bg_item)
        else:
            self.itemconfigure(self._bg_item, image=ph)
        self.tag_raise(self._txt)

    def _enter(self, _e=None) -> None:
        if not self._enabled:
            return
        self._hovering = True
        self._draw()

    def _leave(self, _e=None) -> None:
        self._hovering = False
        self._draw()

    def set_enabled(self, on: bool) -> None:
        """启用 / 禁用按钮。禁用时变暗且不响应点击。"""
        self._enabled = on
        self._hovering = False
        self.configure(cursor="hand2" if on else "arrow")
        self.itemconfigure(self._txt, fill=self._fg if on else FG_DIM)
        self._draw()

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._txt, text=text)

    def _on_click(self) -> None:
        if self._enabled:
            self._command()


class MenuBar(tk.Frame):
    """自绘暗色菜单栏（文件 / 编辑 / 查看）。

    不用原生 Menu 挂到窗口：Windows 原生菜单栏无法可靠变暗。
    这里用 Frame + 弹出式 tk.Menu，颜色完全可控。
    """

    def __init__(self, master: "EditorWindow"):
        super().__init__(master, bg=BG_MENU, height=34)
        self._win = master
        self.pack(fill="x")
        self.pack_propagate(False)

        self._menus: list[tuple[str, tk.Menu, tk.Label]] = []
        self._open_menu: tk.Menu | None = None
        self._open_label: tk.Label | None = None

        self._add_menu("文件", self._build_file)
        self._add_menu("编辑", self._build_edit)
        self._add_menu("查看", self._build_view)

        # 右侧：加密状态
        self.lock_label = tk.Label(self, text="● 已加密", bg=BG_MENU,
                                   fg=FG_ACCENT, font=_ui_font(FS_STATUS))
        self.lock_label.pack(side="right", padx=(0, 16))

        # 点击别处关闭菜单
        master.bind("<Button-1>", self._maybe_close, add="+")

    def _add_menu(self, title: str, builder: Callable[[tk.Menu], None]) -> None:
        lbl = tk.Label(self, text=title, bg=BG_MENU, fg=FG_TEXT,
                       font=_ui_font(FS_MENU), padx=12, pady=0,
                       cursor="hand2", anchor="center")
        lbl.pack(side="left", fill="y")

        menu = tk.Menu(self, tearoff=0, bg=BG_MENU, fg=FG_TEXT,
                       activebackground=FG_ACCENT, activeforeground="#0d1f2b",
                       bd=0, relief="flat", font=_ui_font(FS_MENU),
                       activeborderwidth=0)
        builder(menu)

        lbl.bind("<Button-1>", lambda _e, m=menu, l=lbl: self._toggle(m, l))
        lbl.bind("<Enter>", lambda _e, l=lbl: self._hover_on(l))
        lbl.bind("<Leave>", lambda _e, l=lbl: self._hover_off(l))
        self._menus.append((title, menu, lbl))

    def _hover_on(self, lbl: tk.Label) -> None:
        if self._open_label is lbl:
            return
        lbl.configure(bg=BG_HOVER)

    def _hover_off(self, lbl: tk.Label) -> None:
        if self._open_label is lbl:
            return
        lbl.configure(bg=BG_MENU)

    def _toggle(self, menu: tk.Menu, lbl: tk.Label) -> None:
        if self._open_menu is menu:
            self._close()
            return
        self._close()
        self._open_menu = menu
        self._open_label = lbl
        lbl.configure(bg=BG_HOVER)
        x = lbl.winfo_rootx()
        y = lbl.winfo_rooty() + lbl.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _close(self) -> None:
        if self._open_label is not None:
            self._open_label.configure(bg=BG_MENU)
        self._open_menu = None
        self._open_label = None

    def _maybe_close(self, event) -> None:
        if self._open_label is not None and event.widget is not self._open_label:
            self._close()

    # ---------------- 各菜单内容 ----------------
    def _build_file(self, m: tk.Menu) -> None:
        m.add_command(label="保存并加密", accelerator="Ctrl+S",
                      command=self._win._save)
        m.add_command(label="另存为加密文件…",
                      command=self._win.save_as_encrypted)
        m.add_separator()
        m.add_command(label="修改密码…", command=self._win.change_password)
        m.add_separator()
        m.add_command(label="关闭", accelerator="Ctrl+W",
                      command=self._win._request_close)

    def _build_edit(self, m: tk.Menu) -> None:
        # 注意：这里不能直接抓 self._win.text_widget —— 菜单在
        # EditorWindow.__init__ 早期就构建了，那时 Text 还不存在。
        # 用 lambda 延迟到点击时再解析。
        m.add_command(label="撤销", accelerator="Ctrl+Z",
                      command=lambda: self._edit("<<Undo>>"))
        m.add_command(label="重做", accelerator="Ctrl+Y",
                      command=lambda: self._edit("<<Redo>>"))
        m.add_separator()
        m.add_command(label="剪切", accelerator="Ctrl+X",
                      command=lambda: self._edit("<<Cut>>"))
        m.add_command(label="复制", accelerator="Ctrl+C",
                      command=lambda: self._edit("<<Copy>>"))
        m.add_command(label="粘贴", accelerator="Ctrl+V",
                      command=lambda: self._edit("<<Paste>>"))
        m.add_command(label="全选", accelerator="Ctrl+A",
                      command=self._select_all)
        m.add_separator()
        m.add_command(label="查找", accelerator="Ctrl+F",
                      command=lambda: self._win.find_bar.show())
        m.add_command(label="替换", accelerator="Ctrl+H",
                      command=lambda: self._win.find_bar.show())

    def _edit(self, seq: str) -> None:
        try:
            self._win.text_widget.event_generate(seq)
        except (tk.TclError, AttributeError):
            pass
        self._win.mark_dirty()

    def _select_all(self) -> None:
        t = self._win.text_widget
        t.tag_add("sel", "1.0", "end-1c")
        t.mark_set("insert", "1.0")

    def _build_view(self, m: tk.Menu) -> None:
        w = self._win
        m.add_command(label="放大", accelerator="Ctrl+=",
                      command=lambda: w.zoom(+1))
        m.add_command(label="缩小", accelerator="Ctrl+-",
                      command=lambda: w.zoom(-1))
        m.add_command(label="恢复默认缩放", accelerator="Ctrl+0",
                      command=lambda: w.set_font_size(FONT_SIZE))
        m.add_separator()
        self._status_var = tk.BooleanVar(value=True)
        self._wrap_var = tk.BooleanVar(value=False)
        m.add_checkbutton(label="状态栏", accelerator="Ctrl+Shift+S",
                          variable=self._status_var,
                          command=w.toggle_status_bar)
        m.add_checkbutton(label="自动换行", accelerator="Ctrl+Shift+W",
                          variable=self._wrap_var,
                          command=w.toggle_wrap)

    def sync_view_state(self, *, wrap: bool, status: bool) -> None:
        """让菜单勾选状态与真实状态同步（快捷键改状态时调用）。"""
        try:
            self._wrap_var.set(wrap)
            self._status_var.set(status)
        except (AttributeError, tk.TclError):
            pass


def _hsep(parent: tk.Misc, color: str = BORDER) -> None:
    tk.Frame(parent, bg=color, height=1).pack(fill="x")


# =====================================================================
#  密码框
# =====================================================================
class PasswordDialog(SafeToplevel):
    """模态密码框（暗色圆角）。"""

    def __init__(self, parent: tk.Misc, title: str, prompt: str,
                 on_submit: Callable[[str], str | None]):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.configure(bg=BG_APP)

        try:
            if parent.winfo_viewable():
                self.transient(parent)
        except tk.TclError:
            pass

        self._on_submit = on_submit
        self.result: str | None = None
        self._error_var = tk.StringVar()

        body = tk.Frame(self, bg=BG_APP, padx=28, pady=26)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=prompt, bg=BG_APP, fg=FG_TEXT,
                 font=_ui_font(FS_FIELD), anchor="w",
                 justify="left").pack(fill="x")

        field = SearchField(body, icon=ICON_LOCK, font_size=FS_FIELD + 1,
                            height=44, on_return=self._submit,
                            on_escape=self._cancel, password=True)
        field.pack(fill="x", pady=(18, 0))
        self._field = field
        self._entry = field.entry
        self._reveal_btn = field.reveal_btn

        self._error_label = tk.Label(body, textvariable=self._error_var,
                                     bg=BG_APP, fg=FG_DANGER,
                                     font=_ui_font(FS_HINT),
                                     anchor="w", justify="left", wraplength=360)
        self._error_label.pack(fill="x", pady=(12, 0))

        btns = tk.Frame(body, bg=BG_APP)
        btns.pack(fill="x", pady=(22, 0))

        self._ok = RoundButton(btns, "解锁", self._submit, btn_width=104,
                               btn_height=40, primary=True, font_size=FS_BTN)
        self._ok.pack(side="right")
        RoundButton(btns, "取消", self._cancel, btn_width=104,
                    btn_height=40, font_size=FS_BTN).pack(side="right",
                                                          padx=(0, 12))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 448)
        h = self.winfo_reqheight()
        self._center_on(parent, w, h)

        _apply_win11_chrome(self)
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after_safe(150, self._clear_topmost)
        self.grab_set()

        # 焦点加固：Windows 在窗口刚映射时，焦点可能先落在 Toplevel 本身
        # 或标题栏，导致用户直接打字没有反应。分多次尝试并在窗口真正
        # 可见后强制一次，确保光标就在密码框里。
        self._focus_entry()
        self.after_safe(0, self._focus_entry)
        self.after_safe(60, self._focus_entry)
        self.after_safe(200, self._focus_entry)
        self.bind("<Map>", lambda _e: self._focus_entry(), add="+")
        self.bind("<FocusIn>", lambda _e: self._focus_entry(), add="+")

    def _focus_entry(self) -> None:
        """把窗口切前台，并让键盘焦点落到密码输入框。

        只做 Tk 的 focus_force 不够：本机前台锁是永久的
        （SPI_GETFOREGROUNDLOCKTIMEOUT=0x7FFFFFFF），必须走
        AttachThreadInput 才能真的把窗口提到前台。
        """
        try:
            if not self.winfo_exists():
                return
            self._focus_tries = getattr(self, "_focus_tries", 0) + 1

            _force_foreground(self)
            self._entry.focus_force()
            _focus_hwnd(self._entry.winfo_id())
            self._entry.icursor("end")
            self._entry.select_range(0, "end")

            # 前几次若没拿到前台，稍后再补一次（系统偶尔需要一拍）
            if self._focus_tries <= 4:
                self.after_safe(120, self._focus_entry)
        except tk.TclError:
            pass

    def _center_on(self, parent: tk.Misc, w: int, h: int) -> None:
        x = y = None
        try:
            if parent.winfo_viewable():
                px, py = parent.winfo_rootx(), parent.winfo_rooty()
                pw, ph = parent.winfo_width(), parent.winfo_height()
                x = px + max(0, (pw - w) // 2)
                y = py + max(0, (ph - h) // 3)
        except tk.TclError:
            pass
        if x is None or y is None:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _submit(self) -> None:
        pw = self._entry.get()
        if not pw:
            self._error_var.set("请输入密码")
            return
        self._error_var.set("")
        self.update_idletasks()
        err = self._on_submit(pw)
        if err:
            self._error_var.set(err)
            self._entry.select_range(0, "end")
            self._entry.focus_set()
            return
        self.result = pw
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


# =====================================================================
#  查找 / 替换栏
# =====================================================================
class FindBar(tk.Frame):
    """仿 Win11 记事本查找栏。

    ::

        [🔍 查找内容 ................ 3/12] [↑] [↓] [Aa] [✕]
        [⇄ 替换为 ....................]      [替换] [全部替换]
    """

    PAD_X = 16
    PAD_Y = 10
    GAP = 8
    FIELD_H = 34

    def __init__(self, master: "EditorWindow"):
        super().__init__(master, bg=BG_BAR, padx=self.PAD_X, pady=self.PAD_Y)
        self._win = master
        self._matches: list[str] = []
        self._index = -1
        self._query = ""
        self._wrap_var = tk.BooleanVar(value=True)
        self._case_var = tk.BooleanVar(value=False)

        row = tk.Frame(self, bg=BG_BAR)
        row.pack(fill="x")

        self._find_field = SearchField(
            row, icon=ICON_SEARCH, height=self.FIELD_H, show_count=True,
            on_change=self._on_query_change,
            on_return=self.find_next,
            on_shift_return=self.find_prev,
            on_escape=self.hide,
        )
        self._find_field.pack(side="left", fill="x", expand=True)
        self._find_entry = self._find_field.entry
        self._find_var = self._find_field.var

        btns = tk.Frame(row, bg=BG_BAR)
        btns.pack(side="left", padx=(self.GAP, 0))

        self._prev_btn = IconButton(btns, ICON_UP, self.find_prev, size=34)
        self._prev_btn.pack(side="left")
        self._next_btn = IconButton(btns, ICON_DOWN, self.find_next, size=34)
        self._next_btn.pack(side="left", padx=(2, 0))
        self._opt_btn = IconButton(btns, ICON_CASE, self._toggle_options, size=34)
        self._opt_btn.pack(side="left", padx=(2, 0))
        self._close_btn = IconButton(btns, ICON_CLOSE, self.hide, size=34)
        self._close_btn.pack(side="left", padx=(2, 0))

        # 成员名不能叫 _options：tkinter.Widget 内部用 self._options() 解析配置，
        # 被 Frame 覆盖后 pack() 会抛 "TypeError: 'Frame' object is not callable"。
        self._options_panel = tk.Frame(self, bg=BG_BAR)
        cb_kw = dict(bg=BG_BAR, fg=FG_MUTED, font=_ui_font(FS_STATUS),
                     activebackground=BG_BAR, activeforeground=FG_TEXT,
                     selectcolor=BG_INPUT, highlightthickness=0, bd=0,
                     cursor="hand2", anchor="w")
        tk.Checkbutton(self._options_panel, text="区分大小写",
                       variable=self._case_var, command=self._on_query_change,
                       **cb_kw).pack(side="left")
        tk.Checkbutton(self._options_panel, text="环绕",
                       variable=self._wrap_var, **cb_kw).pack(side="left", padx=(16, 0))

        self._row2 = tk.Frame(self, bg=BG_BAR)

        self._repl_field = SearchField(
            self._row2, icon=ICON_REPLACE, height=self.FIELD_H,
            on_return=self.replace_current, on_escape=self.hide,
        )
        self._repl_field.pack(side="left", fill="x", expand=True)
        self._repl_entry = self._repl_field.entry
        self._repl_var = self._repl_field.var

        RoundButton(self._row2, "替换", self.replace_current,
                    btn_width=76, btn_height=self.FIELD_H).pack(
            side="left", padx=(self.GAP, 0))
        RoundButton(self._row2, "全部替换", self.replace_all,
                    btn_width=94, btn_height=self.FIELD_H).pack(
            side="left", padx=(6, 0))

        self._options_visible = False

    # ---------------- 行为 ----------------
    def _text(self) -> tk.Text:
        return self._win.text_widget

    def _toggle_options(self) -> None:
        self._options_visible = not self._options_visible
        if self._options_visible:
            self._options_panel.pack(fill="x", pady=(self.GAP, 0))
        else:
            self._options_panel.pack_forget()
        self._opt_btn.set_active(self._options_visible)

    def show(self, *, with_selection: bool = True) -> None:
        sel = self._text().tag_ranges("sel")
        if with_selection and sel:
            self._find_var.set(self._text().get(sel[0], sel[1]))
        if not self.winfo_ismapped():
            self.pack(fill="x", before=self._win.text_wrap)
            self._row2.pack(fill="x", pady=(self.GAP, 0))
        self._find_entry.focus_set()
        self._find_entry.select_range(0, "end")
        self._on_query_change()

    def hide(self) -> None:
        self._clear_tags()
        self.pack_forget()
        self._win.text_widget.focus_set()

    def _clear_tags(self) -> None:
        t = self._text()
        t.tag_remove("found", "1.0", "end")
        t.tag_remove("found_current", "1.0", "end")

    def _on_query_change(self) -> None:
        q = self._find_var.get()
        self._clear_tags()
        self._query = q
        if not q:
            self._matches = []
            self._index = -1
            self._find_field.set_count("")
            self._prev_btn.set_enabled(False)
            self._next_btn.set_enabled(False)
            return

        t = self._text()
        nocase = not self._case_var.get()
        found: list[str] = []
        start = "1.0"
        while True:
            pos = t.search(q, start, stopindex="end", nocase=nocase)
            if not pos:
                break
            found.append(pos)
            start = f"{pos}+{len(q)}c"

        self._matches = found
        self._index = -1
        for pos in found:
            t.tag_add("found", pos, f"{pos}+{len(q)}c")

        if found:
            self._find_field.set_count(f"{len(found)} 个")
        else:
            self._find_field.set_count("无结果")
        self._prev_btn.set_enabled(bool(found))
        self._next_btn.set_enabled(bool(found))

    def _goto(self, idx: int) -> None:
        if not self._matches:
            return
        q = self._query
        n = len(self._matches)
        if self._wrap_var.get():
            self._index = idx % n
        else:
            self._index = max(0, min(idx, n - 1))
        pos = self._matches[self._index]
        t = self._text()
        t.tag_remove("found_current", "1.0", "end")
        t.tag_add("found_current", pos, f"{pos}+{len(q)}c")
        t.mark_set("insert", pos)
        t.see(pos)
        self._find_field.set_count(f"{self._index + 1}/{n}")

    def find_next(self) -> None:
        if not self._matches:
            self._on_query_change()
            if not self._matches:
                return
        self._goto(self._index + 1)

    def find_prev(self) -> None:
        if not self._matches:
            self._on_query_change()
            if not self._matches:
                return
        self._goto(self._index - 1)

    def replace_current(self) -> None:
        t = self._text()
        if self._index < 0 or not self._matches:
            self.find_next()
            return
        q = self._query
        pos = self._matches[self._index]
        end = f"{pos}+{len(q)}c"
        if t.get(pos, end) == q:
            t.delete(pos, end)
            t.insert(pos, self._repl_var.get())
            self._win.mark_dirty()
        keep = self._index
        self._on_query_change()
        if self._matches:
            self._goto(min(keep, len(self._matches) - 1))

    def replace_all(self) -> None:
        q = self._query
        if not q:
            return
        t = self._text()
        repl = self._repl_var.get()
        nocase = not self._case_var.get()
        count = 0
        start = "1.0"
        while True:
            pos = t.search(q, start, stopindex="end", nocase=nocase)
            if not pos:
                break
            t.delete(pos, f"{pos}+{len(q)}c")
            t.insert(pos, repl)
            start = f"{pos}+{len(repl)}c"
            count += 1
        if count:
            self._win.mark_dirty()
        self._on_query_change()
        self._find_field.set_count(f"替换 {count} 处")


# =====================================================================
#  编辑器主窗口
# =====================================================================
class EditorWindow(tk.Tk):
    """内置文本编辑器（Win11 记事本暗色风格）。"""

    def __init__(self, *, title: str, subtitle: str, initial_text: str,
                 on_save: Callable[[str], str | None],
                 on_close_discard: Callable[[], None] | None = None,
                 read_only: bool = False,
                 file_path=None):
        super().__init__()
        self.title(title)
        self.configure(bg=BG_APP)
        self.minsize(680, 420)

        # 读取上次的窗口尺寸 / 缩放 / 换行等偏好
        self._prefs = _settings.load()
        self._font_size = int(self._prefs.get("font_size", FONT_SIZE))
        self._wrap_on = bool(self._prefs.get("wrap", False))
        self._restore_geometry()

        self.file_path = file_path
        self._on_save = on_save
        self._on_close_discard = on_close_discard
        self._read_only = read_only
        self._dirty = False
        self._saved_text = initial_text
        self.saved = False

        _init_scrollbar_style(self)

        self.menu_bar = MenuBar(self)
        self._build_chrome(subtitle)
        # 顺序很重要：编辑区 expand=True 会吃掉全部剩余空间，
        # 若先打包编辑区，后打包的状态栏就分不到高度。
        self._build_status()
        self._build_editor(initial_text)

        self.find_bar = FindBar(self)

        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self.bind_all("<Control-s>", lambda _e: self._save())
        self.bind_all("<Control-S>", lambda _e: self._save())
        self.bind_all("<Control-w>", lambda _e: self._request_close())
        self.bind_all("<Control-W>", lambda _e: self._request_close())
        self.bind_all("<Control-f>", lambda _e: self.find_bar.show())
        self.bind_all("<Control-F>", lambda _e: self.find_bar.show())
        self.bind_all("<Control-h>", lambda _e: self.find_bar.show())
        self.bind_all("<Control-H>", lambda _e: self.find_bar.show())
        self.bind_all("<F3>", lambda _e: self.find_bar.find_next())
        self.bind_all("<Shift-F3>", lambda _e: self.find_bar.find_prev())
        self.bind_all("<Escape>", self._on_escape)

        self.bind_all("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.bind_all("<Control-equal>", lambda _e: self.zoom(+1))
        self.bind_all("<Control-minus>", lambda _e: self.zoom(-1))
        self.bind_all("<Control-Key-0>", lambda _e: self.set_font_size(FONT_SIZE))
        self.bind_all("<Control-Shift-W>", lambda _e: self.toggle_wrap())
        self.bind_all("<Control-Shift-w>", lambda _e: self.toggle_wrap())
        self.bind_all("<Control-Shift-S>", lambda _e: self.toggle_status_bar())
        self.bind_all("<Control-Shift-s>", lambda _e: self.toggle_status_bar())

        self.text_widget.focus_set()
        self._refresh_status()
        _apply_win11_chrome(self)

        # 应用已恢复的换行 / 状态栏状态
        if self._wrap_on:
            self.text_widget.configure(wrap="word")
            self._wrap_var.set("自动换行:开")
            self._wrap_label.configure(fg=FG_ACCENT)
        if not self._prefs.get("status_bar", True):
            self._status_bar.pack_forget()
        self.menu_bar.sync_view_state(
            wrap=self._wrap_on,
            status=bool(self._status_bar.winfo_ismapped()))
        self._update_zoom_label()

        self.after(80, self._grab_focus)

    # ---------------- 窗口几何记忆 ----------------
    def _restore_geometry(self) -> None:
        """恢复上次的窗口大小与位置；首次运行则居中。"""
        w = int(self._prefs.get("window_width", 1000))
        h = int(self._prefs.get("window_height", 720))
        x = self._prefs.get("window_x")
        y = self._prefs.get("window_y")

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        # 尺寸不能超过屏幕，否则窗口会跑到屏幕外
        w = min(w, sw - 40)
        h = min(h, sh - 60)

        if x is None or y is None:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2 - 30)
        else:
            # 位置校验：标题栏必须还留在屏幕内，否则用户拖不回来
            x = max(-w + 120, min(int(x), sw - 120))
            y = max(0, min(int(y), sh - 80))

        self.geometry(f"{w}x{h}+{x}+{y}")
        if self._prefs.get("maximized"):
            self.after(10, lambda: self.state("zoomed"))

    def _remember_geometry(self) -> None:
        """把当前窗口尺寸 / 位置 / 缩放 / 换行写回配置。"""
        try:
            maximized = self.state() == "zoomed"
            if maximized:
                # 最大化时记「还原后」的尺寸，否则下次打开是个满屏窗口
                vals = {
                    "window_width": self._prefs.get("window_width", 1000),
                    "window_height": self._prefs.get("window_height", 720),
                    "window_x": self._prefs.get("window_x"),
                    "window_y": self._prefs.get("window_y"),
                }
            else:
                vals = {
                    "window_width": self.winfo_width(),
                    "window_height": self.winfo_height(),
                    "window_x": self.winfo_x(),
                    "window_y": self.winfo_y(),
                }
            vals.update({
                "maximized": maximized,
                "font_size": self._font_size,
                "wrap": self._wrap_on,
                "status_bar": bool(self._status_bar.winfo_ismapped()),
            })
            _settings.save(vals)
            self._prefs = _settings.load()
        except (tk.TclError, OSError):
            pass

    def _grab_focus(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.text_widget.focus_force()
            self.text_widget.mark_set("insert", "1.0")
            self._refresh_status()
        except tk.TclError:
            pass

    # ---------------- 构建 ----------------
    def _build_chrome(self, subtitle: str) -> None:
        head = tk.Frame(self, bg=BG_CHROME, padx=18, pady=9)
        head.pack(fill="x")

        self._title_label = tk.Label(head, text=subtitle, bg=BG_CHROME,
                                     fg=FG_MUTED, font=_ui_font(FS_TITLE), anchor="w")
        self._title_label.pack(side="left")

        _hsep(self)

    def _build_editor(self, initial_text: str) -> None:
        self.text_wrap = tk.Frame(self, bg=BG_EDITOR)
        self.text_wrap.pack(fill="both", expand=True)

        self.text_widget = tk.Text(
            self.text_wrap, wrap="none", undo=True, maxundo=-1,
            bg=BG_EDITOR, fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=_ui_font(self._font_size),
            relief="flat", bd=0, highlightthickness=0,
            padx=18, pady=14,
            selectbackground=SELECT_BG, selectforeground=FG_TEXT,
            spacing1=0, spacing3=0,
        )
        self.text_widget.pack(side="left", fill="both", expand=True)

        self._vsb = ttk.Scrollbar(self.text_wrap, orient="vertical",
                                  command=self.text_widget.yview,
                                  style=_SB_STYLE)
        self._vsb.pack(side="right", fill="y")
        self.text_widget.configure(yscrollcommand=self._vsb.set)

        self.text_widget.tag_configure("found", background=FIND_ALL,
                                       foreground=FG_TEXT)
        self.text_widget.tag_configure("found_current", background=FIND_CUR,
                                       foreground=FG_TEXT)

        if initial_text:
            self.text_widget.insert("1.0", initial_text)
            self.text_widget.mark_set("insert", "1.0")
            self.text_widget.edit_modified(False)

        if self._read_only:
            self.text_widget.configure(state="disabled")

        self.text_widget.bind("<<Modified>>", self._on_modified)
        self.text_widget.bind("<KeyRelease>", lambda _e: self._refresh_status())
        self.text_widget.bind("<ButtonRelease-1>", lambda _e: self._refresh_status())

    def _build_status(self) -> None:
        self._status_bar = tk.Frame(self, bg=BG_CHROME, padx=18, pady=7)
        self._status_bar.pack(side="bottom", fill="x")
        tk.Frame(self._status_bar, bg=BORDER, height=1).place(x=0, y=0, relwidth=1)
        bar = self._status_bar

        self._pos_var = tk.StringVar(value="行 1，列 1")
        self._count_var = tk.StringVar(value="0 个字符")
        self._state_var = tk.StringVar(value="已保存")
        self._wrap_var = tk.StringVar(value="自动换行:关")
        self._zoom_var = tk.StringVar(value="100%")

        tk.Label(bar, textvariable=self._pos_var, bg=BG_CHROME, fg=FG_MUTED,
                 font=_ui_font(FS_STATUS)).pack(side="left", padx=(0, 22))
        tk.Label(bar, textvariable=self._count_var, bg=BG_CHROME, fg=FG_MUTED,
                 font=_ui_font(FS_STATUS)).pack(side="left", padx=(0, 22))
        self._state_label = tk.Label(bar, textvariable=self._state_var,
                                     bg=BG_CHROME, fg=FG_MUTED, font=_ui_font(FS_STATUS))
        self._state_label.pack(side="left")

        self._wrap_label = tk.Label(bar, textvariable=self._wrap_var,
                                    bg=BG_CHROME, fg=FG_MUTED,
                                    font=_ui_font(FS_STATUS), cursor="hand2")
        self._wrap_label.pack(side="right", padx=(18, 0))
        self._wrap_label.bind("<Button-1>", lambda _e: self.toggle_wrap())
        self._wrap_label.bind("<Enter>",
                              lambda _e: self._wrap_label.configure(fg=FG_TEXT))
        self._wrap_label.bind("<Leave>",
                              lambda _e: self._wrap_label.configure(
                                  fg=FG_ACCENT if self._wrap_on else FG_MUTED))

        self._zoom_label = tk.Label(bar, textvariable=self._zoom_var,
                                    bg=BG_CHROME, fg=FG_MUTED,
                                    font=_ui_font(FS_STATUS), cursor="hand2")
        self._zoom_label.pack(side="right", padx=(18, 0))
        self._zoom_label.bind("<Button-1>", lambda _e: self.zoom(+1))
        self._zoom_label.bind("<Button-3>",
                              lambda _e: self.set_font_size(FONT_SIZE))
        self._zoom_label.bind("<Enter>",
                              lambda _e: self._zoom_label.configure(fg=FG_TEXT))
        self._zoom_label.bind("<Leave>",
                              lambda _e: self._zoom_label.configure(fg=FG_MUTED))

        tk.Label(bar, text="UTF-8 · CRLF · AES-256-GCM", bg=BG_CHROME,
                 fg=FG_DIM, font=_ui_font(FS_STATUS)).pack(side="right", padx=(18, 0))

    def _center_screen(self) -> None:
        """仅用于密码框等无记忆需求的窗口。"""
        self.update_idletasks()
        w, h = 1000, 720
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 30)}")
    def _on_ctrl_wheel(self, event) -> str:
        self.zoom(+1 if event.delta > 0 else -1)
        return "break"

    def zoom(self, step: int) -> None:
        self.set_font_size(self._font_size + step)

    def set_font_size(self, size: int) -> None:
        size = max(MIN_FONT, min(MAX_FONT, size))
        if size == self._font_size:
            self._update_zoom_label()
            return
        self._font_size = size
        self.text_widget.configure(font=_ui_font(size))
        self._update_zoom_label()

    def _update_zoom_label(self) -> None:
        pct = round(self._font_size / FONT_SIZE * 100)
        self._zoom_var.set(f"{pct}%")

    def toggle_wrap(self) -> None:
        self._wrap_on = not self._wrap_on
        self.text_widget.configure(wrap="word" if self._wrap_on else "none")
        self._wrap_var.set("自动换行:开" if self._wrap_on else "自动换行:关")
        self._wrap_label.configure(fg=FG_ACCENT if self._wrap_on else FG_MUTED)
        self.menu_bar.sync_view_state(wrap=self._wrap_on,
                                      status=bool(self._status_bar.winfo_ismapped()))

    def toggle_status_bar(self) -> None:
        """显示 / 隐藏状态栏（对齐记事本「查看 → 状态栏」）。"""
        if self._status_bar.winfo_ismapped():
            self._status_bar.pack_forget()
        else:
            self._status_bar.pack(side="bottom", fill="x")
            self._refresh_status()
            self._update_zoom_label()
            self._wrap_var.set("自动换行:开" if self._wrap_on else "自动换行:关")
        self.menu_bar.sync_view_state(
            wrap=self._wrap_on,
            status=bool(self._status_bar.winfo_ismapped()))

    # ---------------- 行为 ----------------
    def mark_dirty(self) -> None:
        self._dirty = True
        self._refresh_status()

    def change_password(self) -> None:
        """从「文件」菜单触发改密码。"""
        if self.file_path is None:
            show_info("无法修改", "这个窗口没有关联到磁盘文件。")
            return
        # 有未保存修改时先保存，否则改完密码会丢内容
        if self._dirty:
            if not self._save():
                return
        from . import app as _app
        _app.change_password(self.file_path)

    def save_as_encrypted(self) -> None:
        """另存为加密文件。"""
        # 有未保存修改时先保存，保证另存的是当前内容
        if self._dirty and not self._save():
            return
        from . import app as _app
        _app.save_as_encrypted(self.file_path, self._current_text())

    def _on_modified(self, _event=None) -> None:
        if self.text_widget.edit_modified():
            self._dirty = True
            self.text_widget.edit_modified(False)
            self._refresh_status()

    def _current_text(self) -> str:
        return self.text_widget.get("1.0", "end-1c")

    def _on_escape(self, _event=None) -> None:
        if self.find_bar.winfo_ismapped():
            self.find_bar.hide()
        else:
            self.text_widget.focus_set()

    def _refresh_status(self) -> None:
        try:
            idx = self.text_widget.index("insert")
            line, col = idx.split(".")
            self._pos_var.set(f"行 {line}，列 {int(col) + 1}")
            self._count_var.set(f"{len(self._current_text())} 个字符")
        except tk.TclError:
            pass

        if self._dirty:
            self._state_var.set("● 未保存")
            self._state_label.configure(fg=FG_DANGER)
            self.menu_bar.lock_label.configure(text="● 有未保存修改", fg=FG_DANGER)
        else:
            self._state_var.set("已保存")
            self._state_label.configure(fg=FG_MUTED)
            self.menu_bar.lock_label.configure(text="● 已加密", fg=FG_ACCENT)

    def _save(self) -> bool:
        if self._read_only:
            return False
        text = self._current_text()
        err = self._on_save(text)
        if err:
            from tkinter import messagebox
            messagebox.showerror("保存失败", err, parent=self)
            return False
        self._saved_text = text
        self._dirty = False
        self.saved = True
        self.text_widget.edit_modified(False)
        self._refresh_status()
        return True

    def _request_close(self) -> None:
        if self._dirty:
            from tkinter import messagebox
            ans = messagebox.askyesnocancel(
                "未保存的修改", "内容已修改。关闭前保存并加密吗？", parent=self)
            if ans is None:
                return
            if ans:
                if not self._save():
                    return
        elif not self.saved and self._on_close_discard is not None:
            self._on_close_discard()
        self._remember_geometry()
        self.destroy()


# =====================================================================
#  对外便捷函数
# =====================================================================
def show_error(title: str, message: str) -> None:
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    _apply_win11_chrome(root)
    messagebox.showerror(title, message, parent=root)
    root.destroy()


def show_info(title: str, message: str) -> None:
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    _apply_win11_chrome(root)
    messagebox.showinfo(title, message, parent=root)
    root.destroy()


# =====================================================================
#  改名文件引导：这个文件还没有加密
# =====================================================================
class RenamedFileDialog(SafeToplevel):
    """用户把 笔记.txt 改名成 笔记.etxt 后双击时的引导。

    两个按钮（按用户确认的设计）：
      [加密后打开]  [取消]
    """

    WIDTH = 460

    def __init__(self, parent: tk.Misc, filename: str):
        super().__init__(parent)
        self.resizable(False, False)
        self.configure(bg=BG_APP)
        self.title("这个文件还没有加密")
        self.result: bool = False        # True = 加密后打开

        try:
            if parent.winfo_viewable():
                self.transient(parent)
        except tk.TclError:
            pass

        body = tk.Frame(self, bg=BG_APP, padx=30, pady=26)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="这个文件还没有加密", bg=BG_APP, fg=FG_TEXT,
                 font=_ui_font(FS_FIELD), anchor="w").pack(fill="x")

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(12, 0))

        tk.Label(body,
                 text=f"{filename} 的内容仍是明文。",
                 bg=BG_APP, fg=FG_MUTED, font=_ui_font(FS_HINT),
                 anchor="w", justify="left",
                 wraplength=self.WIDTH - 60).pack(fill="x", pady=(14, 0))

        tk.Label(body,
                 text="加密后会用新密码保护这个文件，\n"
                      "文件位置和名称保持不变。",
                 bg=BG_APP, fg=FG_DIM, font=_ui_font(FS_STATUS),
                 anchor="w", justify="left",
                 wraplength=self.WIDTH - 60).pack(fill="x", pady=(8, 0))

        btns = tk.Frame(body, bg=BG_APP)
        btns.pack(fill="x", pady=(20, 0))

        ok = RoundButton(btns, "加密后打开", self._confirm, btn_width=128,
                         btn_height=40, primary=True, font_size=FS_BTN)
        ok.pack(side="right")
        RoundButton(btns, "取消", self._cancel, btn_width=100,
                    btn_height=40, font_size=FS_BTN).pack(
            side="right", padx=(0, 12))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", lambda _e: self._confirm())

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), self.WIDTH)
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        self._grow_to_fit()

        _apply_win11_chrome(self)
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after_safe(150, self._clear_topmost)
        self.grab_set()
        self.after_safe(80, lambda: _force_foreground(self))

    def _confirm(self) -> None:
        self.result = True
        self.destroy()

    def _cancel(self) -> None:
        self.result = False
        self.destroy()


def ask_encrypt_renamed(filename: str) -> bool:
    """返回 True 表示用户选择「加密后打开」。"""
    root = tk.Tk()
    root.withdraw()
    dlg = RenamedFileDialog(root, filename)
    root.wait_window(dlg)
    root.destroy()
    return dlg.result


# =====================================================================
#  加密完成提示（含删除原文件复选）
# =====================================================================
class EncryptResultDialog(SafeToplevel):
    """加密完成后的提示。

    恢复码展示策略
    --------------
    `show_recovery=True` 时才显示恢复码大字块。**默认 False**。

    原因：恢复码是**通用**的、只在首次设置时生成一次。首次设置流程
    已经强制用户抄写并勾选确认，之后每次加密再弹一遍纯属重复暴露
    —— 屏幕上多出现一次，就多一次被旁人看到/截屏的机会。

    `source` 为原明文路径时显示「删除原文件」复选；
    原地加密（source is None）不显示，因为没有残留明文。
    """

    WIDTH = 500

    def __init__(self, parent: tk.Misc, *, target: Path,
                 recovery_code: str = "", source: Path | None = None,
                 show_recovery: bool = False):
        super().__init__(parent)
        self.resizable(False, False)
        self.configure(bg=BG_APP)
        self.title("加密完成")
        self.delete_source: bool = False
        self._source = source
        self._recovery_code = recovery_code
        self._show_recovery = show_recovery

        try:
            if parent.winfo_viewable():
                self.transient(parent)
        except tk.TclError:
            pass

        body = tk.Frame(self, bg=BG_APP, padx=30, pady=26)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="加密完成", bg=BG_APP, fg=FG_TEXT,
                 font=_ui_font(FS_FIELD), anchor="w").pack(fill="x")

        tk.Label(body, text=str(target), bg=BG_APP, fg=FG_MUTED,
                 font=_ui_font(FS_STATUS), anchor="w", justify="left",
                 wraplength=self.WIDTH - 60).pack(fill="x", pady=(6, 0))

        if show_recovery and recovery_code:
            self._build_recovery_block(body, recovery_code)

        # ---- 删除原文件（仅右键加密场景）
        self._del_var = tk.BooleanVar(value=False)
        if source is not None:
            tk.Checkbutton(
                body, text=f"删除原文件 {source.name}（明文）",
                variable=self._del_var,
                bg=BG_APP, fg=FG_TEXT, font=_ui_font(FS_HINT),
                activebackground=BG_APP, activeforeground=FG_TEXT,
                selectcolor=BG_INPUT, highlightthickness=0, bd=0,
                cursor="hand2", anchor="w",
            ).pack(fill="x", pady=(16, 0))

        btns = tk.Frame(body, bg=BG_APP)
        btns.pack(fill="x", pady=(20, 0))
        RoundButton(btns, "确定", self._confirm, btn_width=104,
                    btn_height=40, primary=True,
                    font_size=FS_BTN).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._confirm)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self._confirm())

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), self.WIDTH)
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        self._grow_to_fit()

        _apply_win11_chrome(self)
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after_safe(150, self._clear_topmost)
        self.grab_set()
        self.after_safe(80, lambda: _force_foreground(self))

    def _build_recovery_block(self, body: tk.Misc, recovery_code: str) -> None:
        """恢复码大字块（仅首次设置时调用）。"""
        tk.Label(body, text="恢复码", bg=BG_APP, fg=FG_MUTED,
                 font=_ui_font(FS_STATUS), anchor="w").pack(
            fill="x", pady=(16, 5))

        box = RoundedSurface(body, fill=BG_INPUT, radius=R_FIELD, height=58)
        box.pack(fill="x")
        tk.Label(box, text=crypto.format_recovery_code(recovery_code),
                 bg=BG_INPUT, fg=FG_ACCENT,
                 font=("Consolas", 17, "bold")).place(
            relx=0.5, rely=0.5, anchor="center")

        tk.Label(body,
                 text="请立即抄下，忘记密码时只能靠它。",
                 bg=BG_APP, fg="#e0a030", font=_ui_font(FS_STATUS),
                 anchor="w", justify="left").pack(fill="x", pady=(8, 0))

        row = tk.Frame(body, bg=BG_APP)
        row.pack(fill="x", pady=(8, 0))
        RoundButton(row, "复制恢复码", self._copy, btn_width=110,
                    btn_height=30, font_size=FS_HINT).pack(side="left")
        self._copy_hint = tk.StringVar(value="")
        tk.Label(row, textvariable=self._copy_hint, bg=BG_APP,
                 fg="#5fbf5f", font=_ui_font(FS_STATUS)).pack(
            side="left", padx=(10, 0))

    def _copy(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(
                crypto.format_recovery_code(self._recovery_code))
            self.update_idletasks()
            self._copy_hint.set("已复制")
        except tk.TclError:
            self._copy_hint.set("复制失败，请手动抄写")

    def _confirm(self) -> None:
        self.delete_source = bool(self._del_var.get())
        self.destroy()


def show_encrypt_result(*, target: Path, recovery_code: str = "",
                        source: Path | None = None,
                        show_recovery: bool = False) -> bool:
    """显示加密完成提示。返回「是否删除原文件」。

    `show_recovery` 默认 False —— 恢复码只在首次设置时展示一次，
    之后每次加密不再重复暴露。
    """
    root = tk.Tk()
    root.withdraw()
    dlg = EncryptResultDialog(root, target=target,
                              recovery_code=recovery_code, source=source,
                              show_recovery=show_recovery)
    root.wait_window(dlg)
    root.destroy()
    return dlg.delete_source


def ask_password_blocking(*, title: str, prompt: str,
                          on_submit: Callable[[str], str | None]) -> str | None:
    root = tk.Tk()
    root.withdraw()
    dlg = PasswordDialog(root, title, prompt, on_submit)
    root.wait_window(dlg)
    root.destroy()
    return dlg.result





