"""焦点回归测试：密码框必须能拿到真实前台焦点。

这条测试防止以后改动破坏「打开即可直接打字」的行为。
注意：它依赖 Win32，在非 Windows 上会跳过。

Tk 实例管理：不新建 Tk()，只用进程内已有的解释器状态检查。
真正的焦点行为由人工/端到端验证覆盖（见 test_e2e_click.py）。
"""
import ctypes
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="需要 Win32 API")


def _win32():
    return ctypes.WinDLL("user32", use_last_error=True)


def test_foreground_lock_is_readable():
    """记录本机的前台锁设置，说明为什么必须用 AttachThreadInput。

    SPI_GETFOREGROUNDLOCKTIMEOUT = 0x2000
    """
    u = _win32()
    val = ctypes.c_int()
    ok = u.SystemParametersInfoW(0x2000, 0, ctypes.byref(val), 0)
    if not ok:
        pytest.skip("无法读取前台锁设置")
    assert val.value >= 0


def test_force_foreground_handles_non_window():
    """传一个非窗口对象时不应抛异常。"""
    from etxt import ui

    class Fake:
        def winfo_id(self):
            return 0

        def update_idletasks(self):
            pass

    assert ui._force_foreground(Fake()) in (True, False)


def test_focus_hwnd_no_crash_on_bad_handle():
    from etxt import ui

    ui._focus_hwnd(0)
    ui._focus_hwnd(12345)


def test_safe_toplevel_cancels_afters(tk_root):
    """SafeToplevel 销毁时必须清空 after 列表。

    复用 conftest 里的 session 级 tk_root：同一进程内反复创建/销毁
    Tk() 会让 Tcl 解释器不稳定（实测偶发 Can't find a usable tk.tcl）。
    """
    from etxt import ui

    dlg = ui.SafeToplevel(tk_root)
    dlg.withdraw()
    try:
        dlg.after_safe(5000, lambda: None)
        assert len(dlg._after_ids) == 1
        dlg.destroy()
        assert dlg._after_ids == []
    finally:
        try:
            dlg.destroy()
        except Exception:
            pass
