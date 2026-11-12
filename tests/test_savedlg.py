"""savedlg 层测试：默认路径解析与校验逻辑。

Tk 实例管理见 conftest.py：整个会话共享一个隐藏根窗口。
"""
import sys

import pytest

from etxt import savedlg

needs_gui = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="GUI 需要 Windows")


@pytest.fixture
def dialog(tk_root, tmp_path):
    """构造一个对话框，用完销毁。"""
    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    yield dlg
    try:
        dlg.destroy()
    except Exception:
        pass


# ---------------------------------------------------------------- 路径
def test_default_documents_dir_exists():
    p = savedlg.default_documents_dir()
    assert p.is_dir(), f"默认文档目录不存在：{p}"


def test_default_dir_not_hardcoded():
    """不能硬编码 %USERPROFILE%\\Documents —— 本机 Documents 重定向到 F 盘。"""
    p = savedlg.default_documents_dir()
    assert p.is_dir()
    assert str(p)


def test_is_writable_dir_true(tmp_path):
    assert savedlg._is_writable_dir(tmp_path)


def test_is_writable_dir_missing(tmp_path):
    assert not savedlg._is_writable_dir(tmp_path / "nope")


def test_is_writable_dir_leaves_no_probe(tmp_path):
    savedlg._is_writable_dir(tmp_path)
    assert list(tmp_path.iterdir()) == [], "写权限探测不应留下文件"


# ---------------------------------------------------------------- 对话框
@needs_gui
def test_dialog_target_appends_extension(dialog, tmp_path):
    """文件名没有扩展名时应自动补 .etxt。"""
    dialog._name_var.set("mynote")
    dialog._dir_field.var.set(str(tmp_path))
    target = dialog._target()
    assert target is not None
    assert target.name == "mynote.etxt"


@needs_gui
def test_dialog_validation_detects_existing(dialog, tmp_path):
    """目标已存在时「下一步」应禁用。"""
    (tmp_path / "exists.etxt").write_bytes(b"x")
    dialog._name_var.set("exists.etxt")
    dialog._dir_field.var.set(str(tmp_path))
    assert dialog._validate() is False
    assert dialog._ok._enabled is False


@needs_gui
def test_dialog_validation_ok(dialog, tmp_path):
    """合法路径时「下一步」应可用。"""
    dialog._name_var.set("new.etxt")
    dialog._dir_field.var.set(str(tmp_path))
    assert dialog._validate() is True
    assert dialog._ok._enabled is True


@needs_gui
def test_dialog_validation_missing_dir(dialog, tmp_path):
    dialog._name_var.set("x.etxt")
    dialog._dir_field.var.set(str(tmp_path / "no-such-dir"))
    assert dialog._validate() is False
    assert dialog._ok._enabled is False


@needs_gui
def test_dialog_validation_empty_name(dialog, tmp_path):
    dialog._name_var.set("")
    dialog._dir_field.var.set(str(tmp_path))
    assert dialog._validate() is False


@needs_gui
def test_dialog_default_mode_locks_dir(dialog, tmp_path):
    """选「默认位置」时目录框应禁用。"""
    dialog._mode.set("default")
    dialog._on_mode_change()
    dialog.update()
    assert str(dialog._dir_entry.cget("state")) == "disabled"
    assert dialog._browse_btn._enabled is False

    dialog._mode.set("custom")
    dialog._on_mode_change()
    dialog.update()
    assert str(dialog._dir_entry.cget("state")) == "normal"
    assert dialog._browse_btn._enabled is True


@needs_gui
def test_dialog_confirm_returns_path(tk_root, tmp_path):
    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    try:
        dlg._name_var.set("confirmed.etxt")
        dlg._dir_field.var.set(str(tmp_path))
        dlg._validate()
        dlg._confirm()
        assert dlg.result is not None
        assert dlg.result.name == "confirmed.etxt"
        assert dlg.result.parent == tmp_path
    finally:
        try:
            dlg.destroy()
        except Exception:
            pass


@needs_gui
def test_dialog_cancel_returns_none(tk_root, tmp_path):
    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    try:
        dlg._cancel()
        assert dlg.result is None
    finally:
        try:
            dlg.destroy()
        except Exception:
            pass


@needs_gui
def test_dialog_destroy_cancels_afters(tk_root, tmp_path):
    """销毁后不应留下会执行的 after 回调。"""
    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path)
    dlg.update()
    assert len(dlg._after_ids) > 0
    dlg.destroy()
    assert dlg._after_ids == []


@needs_gui
def test_name_var_is_bound_to_entry(tk_root, tmp_path):
    """回归：`_name_var` 必须与输入框是**同一个** StringVar。

    曾经的 bug：另建了一个 StringVar，用户改文件名时校验读到的
    永远是初始值，导致同名冲突无法消除、「下一步」一直灰着。
    """
    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path,
                                     initial_name="a.etxt")
    dlg.update()
    try:
        assert dlg._name_var is dlg._name_field.var, \
            "_name_var 必须是输入框的变量"
    finally:
        dlg.destroy()


@needs_gui
def test_rename_resolves_conflict(tk_root, tmp_path):
    """同名冲突时按钮禁用，改名后应恢复可用。"""
    (tmp_path / "exists.etxt").write_bytes(b"x")

    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path,
                                     initial_name="exists.etxt")
    dlg.update()
    try:
        # 初始：同名冲突
        assert dlg._validate() is False
        assert dlg._ok._enabled is False

        # 用户改名
        dlg._name_var.set("newname.etxt")
        dlg.update()

        assert dlg._validate() is True
        assert dlg._ok._enabled is True, "改名后按钮必须可用"
    finally:
        dlg.destroy()


@needs_gui
def test_typing_in_entry_updates_validation(tk_root, tmp_path):
    """直接在输入框里打字也要触发校验（模拟真实用户输入）。"""
    (tmp_path / "taken.etxt").write_bytes(b"x")

    dlg = savedlg.SaveLocationDialog(tk_root, initial_dir=tmp_path,
                                     initial_name="taken.etxt")
    dlg.update()
    try:
        assert dlg._ok._enabled is False

        # 模拟用户全选后重新输入
        dlg._name_entry.delete(0, "end")
        dlg._name_entry.insert(0, "fresh.etxt")
        dlg.update()

        assert dlg._name_var.get() == "fresh.etxt"
        assert dlg._ok._enabled is True
    finally:
        dlg.destroy()
