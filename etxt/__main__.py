"""etxt 统一入口。

三种运行形态
------------
1. **源码运行**：`python -m etxt` / `run_etxt.pyw`
2. **打包后的 exe**：PyInstaller 单文件
3. **双击 exe（无参数）**：自动安装 `.etxt` 关联，并提示结果

命令行
------
::

    etxt.exe                 首次运行：安装文件关联（双击即可）
    etxt.exe <文件.etxt>      打开并解锁编辑（文件关联调用的就是这个）
    etxt.exe --install       显式安装关联
    etxt.exe --uninstall     取消关联
    etxt.exe --new <路径>     新建加密文件
    etxt.exe --status        查看关联状态
    etxt.exe --help          帮助

设计要点
--------
- 无参数时**不弹控制台**：所有提示走 tkinter 对话框
- 打包后 sys.executable 就是自身路径，关联直接指向它
- 源码运行时自动改用 pythonw.exe，同样不弹控制台
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import assoc, crypto, store, ui


def _exe_path() -> Path:
    """当前可执行体（exe 或 pythonw.exe）。

    注意不要用 `Path(sys.executable).with_name(...)`：在某些环境下
    Path 会把路径解析到非预期位置（实测在本机解析成了
    `F:\\Program Files\\Python\\...` 这种不存在的路径）。
    直接用 os.path 拼目录最稳。
    """
    import os

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()

    exe = os.path.abspath(sys.executable)
    d = os.path.dirname(exe)
    for cand in ("pythonw.exe", "python.exe"):
        p = os.path.join(d, cand)
        if os.path.isfile(p):
            return Path(p)
    return Path(exe)


def _show_info(title: str, message: str) -> None:
    from tkinter import messagebox
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        ui._apply_win11_chrome(root)
    except Exception:
        pass
    messagebox.showinfo(title, message, parent=root)
    root.destroy()


def _show_error(title: str, message: str) -> None:
    from tkinter import messagebox
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        ui._apply_win11_chrome(root)
    except Exception:
        pass
    messagebox.showerror(title, message, parent=root)
    root.destroy()


HELP = """加密文本工具 etxt

用法：
  etxt.exe                    新建加密文件（首次运行会自动装关联）
  etxt.exe <文件.etxt>         打开加密文件
  etxt.exe --new [路径]        新建加密文件
  etxt.exe --encrypt <文件…>   把普通文本加密为 .etxt（右键菜单 / 拖拽）
  etxt.exe --change <文件>     修改密码
  etxt.exe --install          安装 / 修复文件关联
  etxt.exe --uninstall        取消文件关联
  etxt.exe --status           查看关联状态
  etxt.exe --help             显示本帮助

快捷键：
  Ctrl+S           保存并加密
  Ctrl+W           关闭
  Ctrl+F / Ctrl+H  查找 / 替换
  Ctrl+滚轮        缩放
  Ctrl+Shift+W     自动换行
"""


def _ask_new_path(initial_name: str = "新建加密文本.etxt") -> Path | None:
    """弹保存位置选择框（带默认位置 + 自定义）。"""
    from . import savedlg
    return savedlg.ask_save_location(initial_name=initial_name)


def cmd_install(*, silent: bool = False) -> int:
    """显式安装 / 修复关联（`--install` 走这里）。"""
    try:
        msg = assoc.install(_exe_path())
    except assoc.AssocError as exc:
        _show_error("安装关联失败", str(exc))
        return 1

    if silent:
        return 0

    missing = assoc.check_health(_exe_path())
    if missing:
        _show_error("关联不完整", "以下项目未能正确注册：\n\n"
                                + "\n".join(f"  • {m}" for m in missing))
        return 1

    _show_info(
        "关联已就绪",
        msg + "\n\n"
        "现在可以：\n"
        "  • 双击任意 .etxt 文件打开\n"
        "  • 在 .txt / .md 文件上右键 →「加密为 etxt」\n\n"
        "提示：文件图标可能需要几秒才刷新，\n"
        "没变的话重启一次资源管理器。",
    )
    return 0


def cmd_new_file() -> int:
    """双击 exe 的默认行为：先确保关联健康（静默），再新建。

    用户双击 exe 的意图就是「我要新建一个」，
    所以不弹任何「已关联」提示，只在安装失败时报错。
    """
    # ---- 静默修复关联（不弹提示）
    try:
        healthy = assoc.ensure_installed(_exe_path())
    except Exception:
        healthy = False
    if not healthy:
        _show_error(
            "初始化失败",
            "无法注册文件关联。\n\n"
            "可能原因：\n"
            "  • 注册表写入被安全软件拦截\n"
            "  • 程序目录无权限\n\n"
            "你仍然可以手动指定路径来新建/打开文件。",
        )
        # 不中止：新建本身不需要关联，继续走

    # ---- 选保存位置
    target = _ask_new_path()
    if target is None:
        return 0
    return cmd_new(target)


def cmd_uninstall() -> int:
    try:
        msg = assoc.uninstall()
    except assoc.AssocError as exc:
        _show_error("取消关联失败", str(exc))
        return 1
    _show_info("已取消关联", msg)
    return 0


def cmd_status() -> int:
    if assoc.is_installed():
        cmd = assoc.current_command()
        _show_info("关联状态", f"已关联\n\n打开命令：\n{cmd}")
    else:
        _show_info("关联状态", "尚未关联 .etxt 文件")
    return 0


def cmd_new(target: Path) -> int:
    return ui_create(target)


def ui_create(target: Path) -> int:
    from . import app as _app
    return _app.create_etxt(target)


def cmd_open(target: Path) -> int:
    from . import app as _app
    return _app.open_etxt(target)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # ---- 无参数：双击 exe 的默认行为 = 确保关联健康 + 新建
    if not argv:
        return cmd_new_file()

    first = argv[0]

    if first in ("--help", "-h", "/?"):
        _show_info("帮助", HELP)
        return 0

    if first == "--install":
        return cmd_install()

    if first == "--uninstall":
        return cmd_uninstall()

    if first == "--status":
        return cmd_status()

    if first == "--selftest":
        from . import selftest
        return selftest.run_selftest(argv[1] if len(argv) > 1 else None)

    if first == "--new":
        if len(argv) < 2:
            # 不带路径：走和双击 exe 一样的流程（选位置 → 设密码）
            return cmd_new_file()
        return cmd_new(Path(argv[1]))

    if first == "--shell-new":
        # 右键「新建 → 加密文本文档」走这里。
        # Shell 已建好 0 字节空文件并把路径传进来，直接接管即可。
        if len(argv) < 2:
            _show_error("参数错误", "用法：etxt.exe --shell-new <文件.etxt>")
            return 1
        from . import app as _app
        return _app.create_etxt(Path(argv[1]), from_shell_new=True)

    if first == "--encrypt":
        # 右键菜单 / 拖拽多文件走这里
        files = [Path(a) for a in argv[1:]]
        if not files:
            _show_error("参数错误", "用法：etxt.exe --encrypt <文件…>")
            return 1
        from . import app as _app
        if len(files) == 1:
            return _app.encrypt_plain_file(files[0])
        return _app.encrypt_plain_files(files)

    if first == "--change":
        # 改密码（也可从编辑器「文件」菜单触发）
        if len(argv) < 2:
            _show_error("参数错误", "用法：etxt.exe --change <文件.etxt>")
            return 1
        from . import app as _app
        return _app.change_password(Path(argv[1]))

    # ---- 其余情况当作文件路径（文件关联就是这么调用的）
    target = Path(first)
    if not target.is_file():
        _show_error("文件不存在", f"找不到文件：\n{target}")
        return 1

    # 不是加密格式 → 交给 app 层决定（可能是改名文件，需要引导）
    return cmd_open(target)


if __name__ == "__main__":
    raise SystemExit(main())
