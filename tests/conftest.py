"""pytest 全局配置。

Tk 实例管理
-----------
整个测试会话只创建一个隐藏的 `Tk()` 根窗口，所有需要窗口的测试
复用它、只创建 Toplevel。

原因：同一进程内反复 `Tk()` → `destroy()` 会让 Tcl 解释器不稳定，
实测连开 4-6 个会偶发：

    _tkinter.TclError: Can't find a usable tk.tcl ...

这是 Tk 的已知脆弱点，不是本项目的 bug，但会让测试随机失败。
共享根窗口能彻底避免。
"""
import sys

import pytest


@pytest.fixture(scope="session")
def tk_root():
    """整个测试会话共享的隐藏 Tk 根窗口。"""
    if not sys.platform.startswith("win"):
        pytest.skip("GUI 测试需要 Windows")
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass
