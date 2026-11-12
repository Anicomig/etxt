"""端到端测试：跳过 UI，验证完整加解密往返。"""

import pytest

from etxt import app, crypto, store


def test_full_roundtrip_via_store(tmp_path):
    """模拟：新建 → 加密写盘 → 读盘 → 解密 → 编辑 → 再加密 → 再解密。"""
    p = tmp_path / "note.etxt"
    pw = "my-master-password"

    # 新建
    original = "第一行\n第二行\r\n第三行"
    store.atomic_write(p, crypto.encrypt(original.encode("utf-8"), pw))

    # 打开
    blob = store.read_etxt(p)
    assert crypto.is_etxt(blob)
    assert crypto.decrypt(blob, pw).decode("utf-8") == original

    # 编辑并保存
    edited = original + "\n新增第四行"
    store.atomic_write(p, crypto.encrypt(edited.encode("utf-8"), pw))

    # 重新打开
    assert crypto.decrypt(store.read_etxt(p), pw).decode("utf-8") == edited


def test_file_is_unreadable_without_password(tmp_path):
    p = tmp_path / "note.etxt"
    pw = "right"
    store.atomic_write(p, crypto.encrypt("机密内容".encode("utf-8"), pw))

    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(store.read_etxt(p), "wrong")


def test_encrypted_file_has_no_plaintext(tmp_path):
    """密文里不应出现任何明文片段（基本泄露检查）。"""
    p = tmp_path / "note.etxt"
    secret = "TOPSECRET_MARKER_12345"
    store.atomic_write(p, crypto.encrypt(secret.encode("utf-8"), "pw123456"))

    raw = p.read_bytes()
    assert secret.encode("utf-8") not in raw
    assert secret.encode("utf-16-le") not in raw
    assert b"TOPSECRET" not in raw


def test_decode_utf8():
    text, note = app._decode("中文内容".encode("utf-8"))
    assert text == "中文内容"
    assert note == "UTF-8"


def test_decode_gbk_fallback():
    text, note = app._decode("中文内容".encode("gbk"))
    assert text == "中文内容"
    assert "GBK" in note


def test_decode_invalid_bytes():
    text, note = app._decode(b"\xff\xfe\x00\xff")
    assert isinstance(text, str)
    assert "UTF-8" in note


def test_one_password_multiple_files(tmp_path):
    """一个密码管理多个文件。"""
    pw = "master-pass-2026"
    files = []
    for i in range(5):
        p = tmp_path / f"f{i}.etxt"
        store.atomic_write(p, crypto.encrypt(f"内容 {i}".encode("utf-8"), pw))
        files.append((p, f"内容 {i}"))

    for p, expected in files:
        assert crypto.decrypt(store.read_etxt(p), pw).decode("utf-8") == expected


def test_empty_file_roundtrip(tmp_path):
    p = tmp_path / "empty.etxt"
    store.atomic_write(p, crypto.encrypt(b"", "pw123456"))
    assert crypto.decrypt(store.read_etxt(p), "pw123456") == b""
