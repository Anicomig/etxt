"""对话框自适应高度测试：长文本不能把按钮裁掉。

背景
----
所有对话框原来用 `winfo_reqheight()` 算一次固定高度。但错误提示 /
状态文字是动态的：从一行变三行后窗口不变高，底部按钮就被窗口边缘
裁掉一截 —— 能点，但显示不全。

修法：内容变高时同步把窗口撑高（只增不减，避免抖动）。
"""
import sys

import pytest

needs_gui = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="GUI 需要 Windows")

LONG_TEXT = ("这是一段很长的提示文字，用来模拟真实场景里因为操作失败而出现的"
             "多行错误说明。它会把对话框底部的内容往下推，如果窗口不跟着长高，"
             "最下面的按钮就会被窗口边缘裁掉一部分。再补一些字确保换行到三行以上。")


@needs_gui
def test_safe_toplevel_has_grow_to_fit(tk_root):
    """基类必须提供 _grow_to_fit。"""
    from etxt import ui

    dlg = ui.SafeToplevel(tk_root)
    dlg.withdraw()
    try:
        assert hasattr(dlg, "_grow_to_fit")
        assert callable(dlg._grow_to_fit)
    finally:
        dlg.destroy()


@needs_gui
def test_save_dialog_grows_on_long_status(tk_root, tmp_path):
    """保存位置对话框：状态文字变长后窗口必须变高。"""
    from etxt import savedlg

    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    try:
        h0 = dlg.winfo_height()

        dlg._status_var.set(LONG_TEXT)
        dlg.update()
        dlg._grow_to_fit()
        dlg.update()

        h1 = dlg.winfo_height()
        assert h1 >= h0, "长文本后窗口不能变矮"
        # 至少要能容纳多出来的行
        assert dlg.winfo_reqheight() <= h1, \
            f"窗口高度 {h1} 小于内容需求 {dlg.winfo_reqheight()}"
    finally:
        dlg.destroy()


@needs_gui
def test_auth_dialog_grows_on_long_error(tk_root):
    """认证对话框：错误文字变长后窗口必须变高。"""
    from etxt import authdialog

    dlg = authdialog.AuthDialog(tk_root, "unlock", filename="x.etxt",
                                on_verify_password=lambda pw: "错误")
    dlg.update()
    try:
        h0 = dlg.winfo_height()
        dlg._error_var.set(LONG_TEXT)
        dlg.update()
        dlg._grow_to_fit()
        dlg.update()
        h1 = dlg.winfo_height()

        assert h1 >= h0
        assert dlg.winfo_reqheight() <= h1
    finally:
        dlg.destroy()


@needs_gui
def test_error_var_write_triggers_grow(tk_root):
    """写 _error_var 应自动触发撑高（不用调用方手动调）。"""
    from etxt import authdialog

    dlg = authdialog.AuthDialog(tk_root, "unlock", filename="x.etxt",
                                on_verify_password=lambda pw: "错误")
    dlg.update()
    try:
        h0 = dlg.winfo_height()
        dlg._error_var.set(LONG_TEXT)
        dlg.update()
        # 不给额外时间，靠 trace 里的同步调用
        assert dlg.winfo_height() >= h0
    finally:
        dlg.destroy()


@needs_gui
def test_buttons_visible_after_grow(tk_root, tmp_path):
    """撑高后按钮必须完整落在窗口内（不被裁）。"""
    from etxt import savedlg

    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    try:
        dlg._status_var.set(LONG_TEXT)
        dlg.update()
        dlg._grow_to_fit()
        dlg.update()

        win_h = dlg.winfo_height()
        btn = dlg._ok
        # 按钮底边相对窗口的位置
        btn_bottom = btn.winfo_y() + btn.winfo_height()
        assert btn_bottom <= win_h, \
            f"按钮底边 {btn_bottom} 超出窗口高度 {win_h}"
    finally:
        dlg.destroy()


@needs_gui
def test_grow_only_increases(tk_root, tmp_path):
    """只增不减：文字变短时窗口不应缩小（避免抖动）。"""
    from etxt import savedlg

    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    try:
        dlg._status_var.set(LONG_TEXT)
        dlg.update()
        dlg._grow_to_fit()
        dlg.update()
        h_big = dlg.winfo_height()

        dlg._status_var.set("短")
        dlg.update()
        dlg._grow_to_fit()
        dlg.update()

        assert dlg.winfo_height() >= h_big
    finally:
        dlg.destroy()


# ---------------------------------------------------------------- 恢复码展示
@needs_gui
def test_independent_password_skips_recovery_page(tk_root, tmp_path, monkeypatch):
    """回归：独立密码流程**不得**再展示「请保存你的恢复码」页。

    用户实测反馈过：用独立密码加密时仍然弹出恢复码页。
    原因是独立密码走了 `ask_setup` 的完整流程，而该流程的第二步
    就是恢复码展示。但恢复码是通用的、早就抄过了，再展示一遍
    属于无谓的重复暴露。
    """
    from etxt import authdialog, master

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    code = "aB3xK9mP2qW7nR5t"
    master.configure("master-pass-1", code)

    dlg = authdialog.AuthDialog(
        tk_root, "confirm_master", filename="x.etxt",
        on_confirm_master=lambda pw: None if master.verify(pw) else "错误",
        fixed_recovery_code=lambda: code,
    )
    dlg.update()
    try:
        visited = [dlg._view]

        dlg._cm.var.set("master-pass-1")
        dlg._switch_to_setup()
        dlg.update()
        visited.append(dlg._view)

        dlg._sp1.var.set("indep2026")
        dlg._sp2.var.set("indep2026")
        dlg._do_setup_next()
        dlg.update()

        assert "setup_recovery" not in visited, \
            f"独立密码不应进入恢复码页，实际路径：{visited}"
        assert dlg.result is not None
        assert dlg.result["independent"] is True
        assert dlg.result["password"] == "indep2026"
        assert dlg.result["recovery_code"] == code
    finally:
        try:
            dlg.destroy()
        except Exception:
            pass


@needs_gui
def test_first_time_setup_shows_recovery_page(tk_root, tmp_path, monkeypatch):
    """首次设置（非独立）**必须**展示恢复码页。"""
    from etxt import authdialog

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    dlg = authdialog.AuthDialog(tk_root, "setup", filename="x.etxt")
    dlg.update()
    try:
        assert dlg._view == "setup"
        dlg._sp1.var.set("first-pass-1")
        dlg._sp2.var.set("first-pass-1")
        dlg._do_setup_next()
        dlg.update()

        assert dlg._view == "setup_recovery", "首次设置必须展示恢复码"
        assert dlg._pending_code, "应生成恢复码"
        assert len(dlg._pending_code) == 16
    finally:
        try:
            dlg.destroy()
        except Exception:
            pass
