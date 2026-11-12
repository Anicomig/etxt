"""通用密码逻辑测试：设置 / 验证 / 独立密码。"""
import json
import sys

import pytest

from etxt import crypto, master


@pytest.fixture(autouse=True)
def isolated_master(tmp_path, monkeypatch):
    """把 master.json 指向临时目录。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------- 基础
def test_not_configured_initially():
    assert master.is_configured() is False


def test_configure_then_configured():
    assert master.configure("my-pass-123", "aB3xK9mP2qW7nR5t") is True
    assert master.is_configured() is True


def test_verify_correct_password():
    code = "aB3xK9mP2qW7nR5t"
    master.configure("my-pass-123", code)
    m = master.verify("my-pass-123")
    assert m is not None
    assert m.password == "my-pass-123"
    assert m.recovery_code == code


def test_verify_wrong_password():
    master.configure("my-pass-123", "aB3xK9mP2qW7nR5t")
    assert master.verify("wrong-pass") is None


def test_verify_empty_password():
    master.configure("my-pass-123", "aB3xK9mP2qW7nR5t")
    assert master.verify("") is None


def test_verify_when_not_configured():
    assert master.verify("anything") is None


def test_no_plaintext_password_in_file(isolated_master):
    """master.json 里不能出现明文密码或明文恢复码。"""
    pw = "SUPER-SECRET-PASSWORD-999"
    code = "aB3xK9mP2qW7nR5t"
    master.configure(pw, code)

    raw = master.master_path().read_text(encoding="utf-8")
    assert pw not in raw
    assert code not in raw
    # 连规范化的恢复码也不该出现
    assert crypto.normalize_recovery_code(code) not in raw


def test_configure_overwrites():
    master.configure("first-pass-1", "aB3xK9mP2qW7nR5t")
    master.configure("second-pass-2", "ZZZZZZZZZZZZZZZZ")
    assert master.verify("first-pass-1") is None
    m = master.verify("second-pass-2")
    assert m is not None
    assert m.recovery_code == "ZZZZZZZZZZZZZZZZ"


def test_clear():
    master.configure("my-pass-123", "aB3xK9mP2qW7nR5t")
    assert master.is_configured() is True
    master.clear()
    assert master.is_configured() is False
    assert master.verify("my-pass-123") is None


def test_corrupt_file_treated_as_unconfigured(isolated_master):
    p = master.master_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ broken json", encoding="utf-8")
    assert master.is_configured() is False
    assert master.verify("x") is None


def test_wrong_version_treated_as_unconfigured(isolated_master):
    p = master.master_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 99}), encoding="utf-8")
    assert master.is_configured() is False


def test_missing_fields_treated_as_unconfigured(isolated_master):
    p = master.master_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "salt_pw": "aa"}), encoding="utf-8")
    assert master.is_configured() is False


def test_save_leaves_no_temp_file(isolated_master):
    master.configure("my-pass-123", "aB3xK9mP2qW7nR5t")
    leftovers = [f for f in master.master_dir().iterdir()
                 if f.name != master.FILE_NAME]
    assert leftovers == []


def test_recovery_code_with_hyphens_normalized():
    """带连字符的恢复码应被规范化后存储。"""
    master.configure("my-pass-123", "aB3x-K9mP-2qW7-nR5t")
    m = master.verify("my-pass-123")
    assert m is not None
    assert m.recovery_code == "aB3xK9mP2qW7nR5t"


# ---------------------------------------------------------------- 与加密联动
def test_master_credentials_can_encrypt_files(tmp_path):
    """用通用密码 + 通用恢复码加密多个文件，两者都能打开。"""
    master.configure("shared-pass-1", "aB3xK9mP2qW7nR5t")
    m = master.verify("shared-pass-1")
    assert m is not None

    for i in range(3):
        blob = crypto.encrypt(f"content {i}".encode(), m.password,
                              recovery_code=m.recovery_code)
        assert crypto.decrypt(blob, m.password) == f"content {i}".encode()
        assert crypto.unlock_with_recovery(
            blob, m.recovery_code).plaintext == f"content {i}".encode()


def test_independent_password_still_uses_master_recovery(tmp_path):
    """独立密码的文件，恢复码仍是通用那个。"""
    master.configure("shared-pass-1", "aB3xK9mP2qW7nR5t")
    m = master.verify("shared-pass-1")

    # 用独立密码加密，但恢复码用通用的
    blob = crypto.encrypt(b"independent", "only-this-file-9",
                          recovery_code=m.recovery_code)

    # 独立密码能开
    assert crypto.decrypt(blob, "only-this-file-9") == b"independent"
    # 通用密码不能开（因为密码不同）
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(blob, m.password)
    # 通用恢复码能开
    assert crypto.unlock_with_recovery(
        blob, m.recovery_code).plaintext == b"independent"


# ---------------------------------------------------------------- 回归：恢复码不能为空
def test_independent_flow_gets_nonempty_recovery_code(monkeypatch, tmp_path):
    """回归测试：独立密码流程拿到的恢复码不能是空串。

    曾经的 bug：在验证密码**之前**就取通用恢复码，那时会话缓存可能为空，
    导致恢复码是空串，界面上恢复码区域一片空白，且加密出的文件
    没有恢复通道（has_recovery=False）。

    现在的约束：`_switch_to_setup` 强制先验证通用密码，
    因此 holder 一定有值。
    """
    from etxt import app, authdialog, store

    master.configure("master-pass-1", "aB3xK9mP2qW7nR5t")
    store.SESSION.clear()

    # 模拟用户：先输对密码，再点「使用独立密码」，
    # 然后在同一对话框里完成 setup（`_switch_to_setup` 不关窗）
    def fake_confirm_master(*, filename, verify, fixed_recovery_code):
        err = verify("master-pass-1")
        assert err is None, "密码应该验证通过"
        code = fixed_recovery_code() if callable(fixed_recovery_code) \
            else fixed_recovery_code
        return {"password": "independent-9",
                "recovery_code": code,
                "independent": True}

    monkeypatch.setattr(authdialog, "ask_confirm_master", fake_confirm_master)

    src = tmp_path / "doc.txt"
    src.write_text("content", encoding="utf-8")
    monkeypatch.setattr(app.ui, "show_encrypt_result", lambda **kw: False)
    monkeypatch.setattr(app.ui, "show_error",
                        lambda t, m: pytest.fail(f"不该报错：{t}: {m}"))

    rc = app.encrypt_plain_file(src)
    assert rc == 0

    blob = (tmp_path / "doc.etxt").read_bytes()
    assert crypto.has_recovery(blob) is True
    assert crypto.unlock_with_recovery(
        blob, "aB3xK9mP2qW7nR5t").plaintext == b"content"
    # 独立密码能开
    assert crypto.decrypt(blob, "independent-9") == b"content"
    # 通用密码不能开（密码不同）
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(blob, "master-pass-1")


def test_independent_without_verify_returns_none(monkeypatch, tmp_path):
    """没验证通用密码就走到独立分支时，必须报错而不是产出坏文件。"""
    from etxt import app, authdialog, store

    master.configure("master-pass-1", "aB3xK9mP2qW7nR5t")
    store.SESSION.clear()

    # 模拟异常：返回独立结果，但恢复码为空（verify 没被调用）
    monkeypatch.setattr(
        authdialog, "ask_confirm_master",
        lambda **kw: {"password": "x-123456",
                      "recovery_code": "",
                      "independent": True})

    errors = []
    monkeypatch.setattr(app.ui, "show_error",
                        lambda t, m: errors.append((t, m)))

    src = tmp_path / "doc.txt"
    src.write_text("content", encoding="utf-8")

    rc = app.encrypt_plain_file(src)
    assert rc == 0
    assert errors, "应明确报错"
    assert not (tmp_path / "doc.etxt").exists(), "不该产出文件"


# ---------------------------------------------------------------- 恢复码展示策略
def test_first_time_shows_recovery(monkeypatch, tmp_path):
    """首次设置通用密码时，完成提示必须展示恢复码。"""
    from etxt import app, authdialog

    master.clear()
    code = "aB3xK9mP2qW7nR5t"
    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "first-pass-1", "recovery_code": code})

    seen = {}

    def fake_result(*, target, recovery_code="", source=None,
                    show_recovery=False):
        seen["code"] = recovery_code
        seen["show"] = show_recovery
        return False

    monkeypatch.setattr(app.ui, "show_encrypt_result", fake_result)

    src = tmp_path / "doc.txt"
    src.write_text("content", encoding="utf-8")
    rc = app.encrypt_plain_file(src)

    assert rc == 0
    assert seen["show"] is True, "首次必须展示恢复码"
    assert seen["code"] == code


def test_later_encryption_hides_recovery(monkeypatch, tmp_path):
    """回归：之后的加密**不得**再展示恢复码。

    恢复码是通用的、只在首次生成一次。每次加密都弹出来纯属重复暴露，
    屏幕上多出现一次就多一次被旁人看到/截屏的机会。
    """
    from etxt import app, authdialog, store

    code = "aB3xK9mP2qW7nR5t"
    master.configure("master-pass-1", code)
    store.SESSION.clear()

    def fake_confirm(*, filename, verify, fixed_recovery_code):
        err = verify("master-pass-1")
        assert err is None
        return {"master_password": "master-pass-1"}

    monkeypatch.setattr(authdialog, "ask_confirm_master", fake_confirm)

    seen = {}

    def fake_result(*, target, recovery_code="", source=None,
                    show_recovery=False):
        seen["show"] = show_recovery
        seen["code"] = recovery_code
        return False

    monkeypatch.setattr(app.ui, "show_encrypt_result", fake_result)

    src = tmp_path / "doc.txt"
    src.write_text("content", encoding="utf-8")
    rc = app.encrypt_plain_file(src)

    assert rc == 0
    assert seen["show"] is False, "之后的加密不应再展示恢复码"


def test_encrypt_creds_first_time_flag():
    """EncryptCreds 的默认 first_time 是 False。"""
    from etxt import app

    c = app.EncryptCreds("pw", "code")
    assert c.first_time is False
    c2 = app.EncryptCreds("pw", "code", first_time=True)
    assert c2.first_time is True


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="GUI 需要 Windows")
def test_result_dialog_hides_recovery_by_default(tk_root, tmp_path):
    """EncryptResultDialog 默认不构建恢复码块。"""
    from etxt import ui

    target = tmp_path / "a.etxt"
    target.write_bytes(b"x")

    dlg = ui.EncryptResultDialog(tk_root, target=target,
                                 recovery_code="aB3xK9mP2qW7nR5t")
    dlg.update()
    try:
        assert not hasattr(dlg, "_copy_hint"), \
            "默认不应创建恢复码相关控件"
        assert dlg._show_recovery is False
    finally:
        dlg.destroy()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="GUI 需要 Windows")
def test_result_dialog_shows_recovery_when_asked(tk_root, tmp_path):
    """show_recovery=True 时才构建恢复码块。"""
    from etxt import ui

    target = tmp_path / "a.etxt"
    target.write_bytes(b"x")

    dlg = ui.EncryptResultDialog(tk_root, target=target,
                                 recovery_code="aB3xK9mP2qW7nR5t",
                                 show_recovery=True)
    dlg.update()
    try:
        assert hasattr(dlg, "_copy_hint"), "应创建恢复码控件"
        assert dlg._show_recovery is True
    finally:
        dlg.destroy()
