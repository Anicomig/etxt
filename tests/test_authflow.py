"""authdialog 与 app 层集成测试（不依赖真实 GUI 交互）。"""

import pytest

from etxt import authdialog, crypto, master, store


@pytest.fixture(autouse=True)
def isolated_master(tmp_path, monkeypatch):
    """隔离通用密码文件，并保证每个测试从「未设置通用密码」开始。

    未设置通用密码时，`_ask_credentials_for_encrypt` 会走
    `authdialog.ask_setup` 分支，这样测试里 mock ask_setup 就能生效。
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    master.clear()
    yield
    master.clear()


# ---------------------------------------------------------------- 强度
def test_strength_empty():
    assert authdialog.password_strength("")[0] == 0


def test_strength_too_short():
    level, text, _ = authdialog.password_strength("abc")
    assert level == 1
    assert "6" in text


def test_strength_at_minimum():
    """刚好 6 位应算「一般」，不再报太短。"""
    level, text, _ = authdialog.password_strength("abcdef")
    assert level == 2
    assert "太短" not in text


def test_strength_levels():
    # 门槛 6，10 起较强，14 起很强
    assert authdialog.password_strength("abcdef")[0] == 2
    assert authdialog.password_strength("abcdefghij")[0] == 3
    assert authdialog.password_strength("abcdefghijklmn")[0] == 4


def test_min_password_len_constant():
    assert authdialog.MIN_PASSWORD_LEN == 6


# ---------------------------------------------------------------- app 层
def test_encrypt_body_keeps_envelope(tmp_path):
    """编辑保存必须保留恢复码通道。"""
    from etxt import app

    pw = "password-1"
    code = "aB3xK9mP2qW7nR5t"
    f = tmp_path / "a.etxt"
    store.atomic_write(f, crypto.encrypt(b"v1", pw, recovery_code=code))

    new_blob = app._encrypt_body_with_same_dek(f.read_bytes(), pw, "v2 content")
    assert new_blob is not None
    assert crypto.has_recovery(new_blob)
    assert crypto.decrypt(new_blob, pw) == b"v2 content"
    assert crypto.unlock_with_recovery(new_blob, code).plaintext == b"v2 content"


def test_encrypt_body_wrong_password_returns_none(tmp_path):
    from etxt import app

    f = tmp_path / "a.etxt"
    store.atomic_write(f, crypto.encrypt(b"x", "right-pw-1"))
    assert app._encrypt_body_with_same_dek(f.read_bytes(), "wrong-pw-1", "y") is None


def test_encrypt_body_legacy_returns_none(tmp_path):
    """旧版 ETXT1 没有信封，无法保留通道，应返回 None 走降级路径。"""
    from etxt import app

    legacy = b"ETXT1\0" + b"\x00" * 28 + b"\x00" * 32
    assert app._encrypt_body_with_same_dek(legacy, "pw", "y") is None


def test_keep_recovery_block(tmp_path):
    """改密码后恢复块必须原样保留。"""
    from etxt import app

    pw = "pw-1-xxxx"
    code = "aB3xK9mP2qW7nR5t"
    blob = crypto.encrypt(b"content", pw, recovery_code=code)
    u = crypto.unlock(blob, pw)

    new_blob = crypto.rewrap(blob, u.dek, new_password="pw-2-yyyy",
                             new_recovery_code=None)
    assert not crypto.has_recovery(new_blob)

    restored = app._keep_recovery_block(blob, new_blob)
    assert crypto.has_recovery(restored)
    assert crypto.decrypt(restored, "pw-2-yyyy") == b"content"
    assert crypto.unlock_with_recovery(restored, code).plaintext == b"content"


def test_full_lifecycle(tmp_path):
    """新建 → 编辑 → 改密码 → 恢复码重置。"""
    from etxt import app

    f = tmp_path / "life.etxt"
    pw1, pw2, pw3 = "pw-first-1", "pw-second-2", "pw-third-3"
    code = crypto.generate_recovery_code()

    # 新建
    store.atomic_write(f, crypto.encrypt(b"v0", pw1, recovery_code=code))

    # 编辑
    nb = app._encrypt_body_with_same_dek(f.read_bytes(), pw1, "v1")
    store.atomic_write(f, nb)

    # 改密码
    blob = f.read_bytes()
    u = crypto.unlock(blob, pw1)
    nb = crypto.rewrap(blob, u.dek, new_password=pw2, new_recovery_code=None)
    store.atomic_write(f, app._keep_recovery_block(blob, nb))

    # 恢复码重置
    blob = f.read_bytes()
    u2 = crypto.unlock_with_recovery(blob, code)
    nb = crypto.rewrap(blob, u2.dek, new_password=pw3,
                       new_recovery_code=code)
    store.atomic_write(f, nb)

    final = f.read_bytes()
    assert crypto.decrypt(final, pw3) == b"v1"
    assert crypto.unlock_with_recovery(final, code).plaintext == b"v1"
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(final, pw1)
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(final, pw2)


def test_encrypt_plain_file_creates_etxt(tmp_path, monkeypatch):
    """encrypt_plain_file 应生成 .etxt 且保留原文件。"""
    from etxt import app

    src = tmp_path / "note.txt"
    src.write_text("plain text content", encoding="utf-8")

    code = "aB3xK9mP2qW7nR5t"
    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "pw-12345678", "recovery_code": code})
    # 不弹任何对话框
    monkeypatch.setattr(app.ui, "show_info", lambda *a, **k: None)
    monkeypatch.setattr(app.ui, "show_encrypt_result",
                        lambda **kw: False)

    rc = app.encrypt_plain_file(src)
    assert rc == 0

    dst = tmp_path / "note.etxt"
    assert dst.is_file()
    assert src.is_file(), "默认应保留原文件"
    blob = dst.read_bytes()
    assert crypto.decrypt(blob, "pw-12345678") == b"plain text content"
    assert crypto.unlock_with_recovery(blob, code).plaintext == b"plain text content"


def test_encrypt_plain_file_can_delete_original(tmp_path, monkeypatch):
    from etxt import app

    src = tmp_path / "note.txt"
    src.write_text("content", encoding="utf-8")

    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "pw-12345678",
                      "recovery_code": crypto.generate_recovery_code()})
    monkeypatch.setattr(app.ui, "show_info", lambda *a, **k: None)
    monkeypatch.setattr(app.ui, "show_encrypt_result", lambda **kw: False)

    rc = app.encrypt_plain_file(src, delete_original=True)
    assert rc == 0
    assert not src.exists()
    assert (tmp_path / "note.etxt").is_file()


def test_encrypt_plain_file_missing_source(tmp_path, monkeypatch):
    from etxt import app

    errors = []
    monkeypatch.setattr(app.ui, "show_error",
                        lambda t, m: errors.append((t, m)))
    rc = app.encrypt_plain_file(tmp_path / "nope.txt")
    assert rc == 1
    assert errors


# ---------------------------------------------------------------- 原地加密
def test_encrypt_in_place(tmp_path, monkeypatch):
    """原地加密：写回同一路径，不产生额外文件。"""
    from etxt import app

    f = tmp_path / "note.etxt"
    f.write_text("plain content", encoding="utf-8")

    code = "aB3xK9mP2qW7nR5t"
    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "pw-12345678", "recovery_code": code})
    monkeypatch.setattr(app.ui, "show_encrypt_result", lambda **kw: False)

    rc = app.encrypt_plain_file(f, in_place=True)
    assert rc == 0

    # 同一路径，现在是密文
    assert f.is_file()
    blob = f.read_bytes()
    assert crypto.is_etxt(blob)
    assert crypto.decrypt(blob, "pw-12345678") == b"plain content"
    # 目录里没有多出文件（排除 fixture 建的 appdata）
    etxt_files = [p.name for p in tmp_path.iterdir() if p.suffix == ".etxt"]
    assert etxt_files == ["note.etxt"]


def test_encrypt_in_place_failure_keeps_original(tmp_path, monkeypatch):
    """原地加密失败时原文件必须完好。"""
    from etxt import app

    f = tmp_path / "note.etxt"
    original = b"plain content"
    f.write_bytes(original)

    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "pw-12345678",
                      "recovery_code": "aB3xK9mP2qW7nR5t"})

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(app.store, "atomic_write", boom)
    errors = []
    monkeypatch.setattr(app.ui, "show_error",
                        lambda t, m: errors.append((t, m)))

    rc = app.encrypt_plain_file(f, in_place=True)
    assert rc == 1
    assert f.read_bytes() == original, "失败后原文件必须不变"
    assert errors


def test_encrypt_in_place_cancel(tmp_path, monkeypatch):
    """用户在密码框点取消时文件不变。"""
    from etxt import app

    f = tmp_path / "note.etxt"
    f.write_text("plain", encoding="utf-8")
    monkeypatch.setattr(authdialog, "ask_setup", lambda **kw: None)

    rc = app.encrypt_plain_file(f, in_place=True)
    assert rc == 0
    assert f.read_text(encoding="utf-8") == "plain"


# ---------------------------------------------------------------- 改名引导
def test_looks_like_text():
    from etxt import app

    assert app.looks_like_text(b"hello world")
    assert app.looks_like_text("中文内容".encode("utf-8"))
    assert app.looks_like_text(b"line1\r\nline2\r\n")
    assert app.looks_like_text(b"")
    assert not app.looks_like_text(bytes(range(256)))
    assert not app.looks_like_text(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)


def test_renamed_file_cancel_does_nothing(tmp_path, monkeypatch):
    """改名文件点「取消」时文件不变。"""
    from etxt import app

    f = tmp_path / "note.etxt"
    original = "plain text"
    f.write_text(original, encoding="utf-8")

    monkeypatch.setattr(app.ui, "ask_encrypt_renamed", lambda name: False)

    rc = app.open_etxt(f)
    assert rc == 0
    assert f.read_text(encoding="utf-8") == original


def test_binary_file_not_treated_as_renamed(tmp_path, monkeypatch):
    """二进制文件不该走改名引导，应直接报错。"""
    from etxt import app

    f = tmp_path / "blob.etxt"
    f.write_bytes(bytes(range(256)) * 4)

    errors = []
    monkeypatch.setattr(app.ui, "show_error",
                        lambda t, m: errors.append((t, m)))
    called = {"renamed": False}
    monkeypatch.setattr(app.ui, "ask_encrypt_renamed",
                        lambda name: called.__setitem__("renamed", True))

    rc = app.open_etxt(f)
    assert rc == 1
    assert errors
    assert not called["renamed"], "二进制文件不应弹改名引导"


# ---------------------------------------------------------------- 批量加密
def test_encrypt_multiple_files_shared_password(tmp_path, monkeypatch):
    """批量加密：一个密码管这一批。"""
    from etxt import app

    files = []
    for i in range(3):
        p = tmp_path / f"doc{i}.txt"
        p.write_text(f"content {i}", encoding="utf-8")
        files.append(p)

    code = "aB3xK9mP2qW7nR5t"
    pw = "shared-password-1"
    calls = {"n": 0}

    def fake_setup(**kw):
        calls["n"] += 1
        return {"password": pw, "recovery_code": code}

    monkeypatch.setattr(authdialog, "ask_setup", fake_setup)
    monkeypatch.setattr(app.ui, "show_info", lambda *a, **k: None)

    rc = app.encrypt_plain_files(files)
    assert rc == 0
    assert calls["n"] == 1, "整批只应设置一次密码"

    for i in range(3):
        blob = (tmp_path / f"doc{i}.etxt").read_bytes()
        assert crypto.decrypt(blob, pw) == f"content {i}".encode()
        assert crypto.unlock_with_recovery(blob, code).plaintext == \
            f"content {i}".encode()


def test_encrypt_multiple_files_skips_missing(tmp_path, monkeypatch):
    from etxt import app

    good = tmp_path / "ok.txt"
    good.write_text("x", encoding="utf-8")
    missing = tmp_path / "gone.txt"

    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "pw-12345678",
                      "recovery_code": crypto.generate_recovery_code()})
    monkeypatch.setattr(app.ui, "show_info", lambda *a, **k: None)

    rc = app.encrypt_plain_files([good, missing])
    assert rc == 0
    assert (tmp_path / "ok.etxt").is_file()


# ---------------------------------------------------------------- 另存为
def test_save_as_encrypted(tmp_path, monkeypatch):
    from etxt import app
    from etxt import savedlg

    target = tmp_path / "copy.etxt"
    monkeypatch.setattr(savedlg, "ask_save_location",
                        lambda **kw: target)
    code = "aB3xK9mP2qW7nR5t"
    monkeypatch.setattr(
        authdialog, "ask_setup",
        lambda **kw: {"password": "pw-12345678", "recovery_code": code})
    monkeypatch.setattr(app.ui, "show_encrypt_result", lambda **kw: False)

    rc = app.save_as_encrypted(None, "saved text")
    assert rc == 0
    blob = target.read_bytes()
    assert crypto.decrypt(blob, "pw-12345678") == b"saved text"
    assert crypto.unlock_with_recovery(blob, code).plaintext == b"saved text"


def test_save_as_encrypted_cancel(tmp_path, monkeypatch):
    from etxt import app
    from etxt import savedlg

    monkeypatch.setattr(savedlg, "ask_save_location", lambda **kw: None)
    rc = app.save_as_encrypted(None, "text")
    assert rc == 0
    assert list(tmp_path.iterdir()) == []

