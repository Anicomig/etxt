"""etxt 启动入口（.pyw，双击不弹控制台）。

这个文件是 PyInstaller 的入口脚本，也可以直接双击运行（源码模式）。
真正的逻辑在 `etxt/__main__.py`，这里只负责把异常兜住 ——
打包成 exe 后没有控制台，未捕获异常会让程序静默退出，
用户完全不知道发生了什么。
"""

from __future__ import annotations

import os
import sys
import traceback

# 源码模式下把项目根目录加进 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _fatal(exc: BaseException) -> None:
    """把致命错误用对话框展示，并落一份日志。"""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    log_path = ""
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "etxt")
        os.makedirs(d, exist_ok=True)
        log_path = os.path.join(d, "crash.log")
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(detail)
    except Exception:
        pass

    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        msg = detail[-1500:]
        if log_path:
            msg += f"\n\n日志已保存到：\n{log_path}"
        messagebox.showerror("etxt 发生错误", msg, parent=root)
        root.destroy()
    except Exception:
        pass


def main() -> int:
    try:
        from etxt.__main__ import main as _main
        return _main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 顶层兜底
        _fatal(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
