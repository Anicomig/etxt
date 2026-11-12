"""crypto 层单元测试（信封加密 + 恢复码）。"""

import pytest

from etxt import crypto


# ---------------------------------------------------------------- 基础往返
def test_roundtrip_basic():
    plain = "hello 世界\n第二行".encode("utf-8")
    blob = crypto.encrypt(plain, "correct horse battery")
    assert crypto.decrypt(blob, "correct horse battery") == plain


def test_roundtrip_empty():
    blob = crypto.encrypt(b"", "pw12345678")
    assert crypto.decrypt(blob, "pw12345678") == b""


def test_roundtrip_large():
    plain = ("x" * 200 + "\n").encode() * 3000
    blob = crypto.encrypt(plain, "pw12345678")
    assert crypto.decrypt(blob, "pw12345678") == plain


def test_roundtrip_binary_safe():
    plain = bytes(range(256)) * 10
    blob = crypto.encrypt(plain, "pw12345678")
    assert crypto.decrypt(blob, "pw12345678") == plain


def test_roundtrip_crlf():
    plain = b"line1\r\nline2\r\n"
    blob = crypto.encrypt(plain, "pw12345678")
    assert crypto.decrypt(blob, "pw12345678") == plain


def test_unicode_password():
    blob = crypto.encrypt(b"data", "密码🔒中文长一点")
    assert crypto.decrypt(blob, "密码🔒中文长一点") == b"data"


# ---------------------------------------------------------------- 格式
def test_magic_and_version():
    blob = crypto.encrypt(b"x", "pw12345678")
    assert blob.startswith(crypto.MAGIC)
    assert blob[crypto.OFF_VERSION] == crypto.VERSION
    assert crypto.is_etxt(blob)


def test_header_len_constant():
    blob = crypto.encrypt(b"x", "pw12345678")
    assert len(blob) > crypto.HEADER_LEN
    # 正文 + tag 之前的固定头部
    assert crypto.HEADER_LEN == 176


def test_no_recovery_flag():
    blob = crypto.encrypt(b"x", "pw12345678")
    assert not crypto.has_recovery(blob)


def test_with_recovery_flag():
    blob = crypto.encrypt(b"x", "pw12345678", recovery_code="aB3xK9mP2qW7nR5t")
    assert crypto.has_recovery(blob)


# ---------------------------------------------------------------- 密码
def test_wrong_password():
    blob = crypto.encrypt(b"secret", "right-password-1")
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(blob, "wrong-password-1")


def test_tamper_body_detected():
    blob = bytearray(crypto.encrypt(b"secret content", "pw12345678"))
    blob[-1] ^= 0x01
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(bytes(blob), "pw12345678")


def test_tamper_wrapped_dek_detected():
    blob = bytearray(crypto.encrypt(b"secret content", "pw12345678"))
    # 改密码封装块里的一字节
    blob[crypto.OFF_WRAPPED_PW + 5] ^= 0xFF
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(bytes(blob), "pw12345678")


def test_truncated_rejected():
    blob = crypto.encrypt(b"x" * 100, "pw12345678")
    with pytest.raises(crypto.NotEtxtFile):
        crypto.decrypt(blob[:-10], "pw12345678")


def test_plain_text_rejected():
    with pytest.raises(crypto.NotEtxtFile):
        crypto.decrypt(b"just plain text" * 20, "pw12345678")


def test_nonce_and_salt_unique():
    a = crypto.encrypt(b"same", "pw12345678")
    b = crypto.encrypt(b"same", "pw12345678")
    assert a != b
    assert a[crypto.OFF_SALT_PW:crypto.OFF_SALT_PW + 16] != \
           b[crypto.OFF_SALT_PW:crypto.OFF_SALT_PW + 16]


# ---------------------------------------------------------------- 恢复码
def test_recovery_code_format():
    code = crypto.generate_recovery_code()
    assert len(code) == crypto.RECOVERY_LEN
    assert code.isalnum()
    assert crypto.is_valid_recovery_code(code)


def test_recovery_code_unique():
    codes = {crypto.generate_recovery_code() for _ in range(200)}
    assert len(codes) == 200, "恢复码必须足够随机，不能重复"


def test_recovery_unlock():
    code = "aB3xK9mP2qW7nR5t"
    plain = "机密内容".encode("utf-8")
    blob = crypto.encrypt(plain, "my-password-1", recovery_code=code)
    got = crypto.unlock_with_recovery(blob, code)
    assert got.plaintext == plain


def test_recovery_wrong_code():
    blob = crypto.encrypt(b"x", "pw12345678", recovery_code="aB3xK9mP2qW7nR5t")
    with pytest.raises(crypto.WrongPassword):
        crypto.unlock_with_recovery(blob, "ZZZZZZZZZZZZZZZZ")


def test_recovery_absent():
    blob = crypto.encrypt(b"x", "pw12345678")
    with pytest.raises(crypto.NoRecovery):
        crypto.unlock_with_recovery(blob, "aB3xK9mP2qW7nR5t")


def test_recovery_with_hyphens_and_spaces():
    code = "aB3xK9mP2qW7nR5t"
    blob = crypto.encrypt(b"x", "pw12345678", recovery_code=code)
    formatted = crypto.format_recovery_code(code)
    assert crypto.unlock_with_recovery(blob, formatted).plaintext == b"x"
    assert crypto.unlock_with_recovery(blob, f" {code} ").plaintext == b"x"


def test_recovery_code_case_sensitive():
    """大小写必须敏感：否则有效搜索空间被砍掉一大半。"""
    code = "aB3xK9mP2qW7nR5t"
    blob = crypto.encrypt(b"x", "pw12345678", recovery_code=code)
    with pytest.raises(crypto.WrongPassword):
        crypto.unlock_with_recovery(blob, code.lower())


def test_both_paths_give_same_plaintext():
    code = "aB3xK9mP2qW7nR5t"
    plain = b"same content"
    blob = crypto.encrypt(plain, "my-password-1", recovery_code=code)
    assert crypto.decrypt(blob, "my-password-1") == plain
    assert crypto.unlock_with_recovery(blob, code).plaintext == plain


def test_both_paths_give_same_dek():
    """两条通道解出的主密钥必须一致，否则改密码会丢数据。"""
    code = "aB3xK9mP2qW7nR5t"
    blob = crypto.encrypt(b"x", "my-password-1", recovery_code=code)
    a = crypto.unlock(blob, "my-password-1")
    b = crypto.unlock_with_recovery(blob, code)
    assert a.dek == b.dek


# ---------------------------------------------------------------- 改密码
def test_rewrap_change_password():
    code = "aB3xK9mP2qW7nR5t"
    plain = b"content to keep"
    blob = crypto.encrypt(plain, "old-password-1", recovery_code=code)

    unlocked = crypto.unlock(blob, "old-password-1")
    new_blob = crypto.rewrap(blob, unlocked.dek,
                             new_password="new-password-2",
                             new_recovery_code=code)

    # 新密码可开
    assert crypto.decrypt(new_blob, "new-password-2") == plain
    # 旧密码不可开
    with pytest.raises(crypto.WrongPassword):
        crypto.decrypt(new_blob, "old-password-1")
    # 恢复码仍然可开
    assert crypto.unlock_with_recovery(new_blob, code).plaintext == plain


def test_rewrap_reset_via_recovery():
    """忘记密码，用恢复码重置。"""
    code = "aB3xK9mP2qW7nR5t"
    plain = b"recover me"
    blob = crypto.encrypt(plain, "forgotten-pw-1", recovery_code=code)

    got = crypto.unlock_with_recovery(blob, code)
    new_blob = crypto.rewrap(blob, got.dek,
                             new_password="brand-new-pw-9",
                             new_recovery_code=code)
    assert crypto.decrypt(new_blob, "brand-new-pw-9") == plain


def test_rewrap_keeps_body_bytes():
    """改密码不应重新加密正文（性能与稳定性要求）。"""
    code = "aB3xK9mP2qW7nR5t"
    blob = crypto.encrypt(b"body stays identical", "pw1-old-xx",
                          recovery_code=code)
    unlocked = crypto.unlock(blob, "pw1-old-xx")
    new_blob = crypto.rewrap(blob, unlocked.dek, new_password="pw2-new-yy",
                             new_recovery_code=code)
    assert blob[crypto.HEADER_LEN:] == new_blob[crypto.HEADER_LEN:]


def test_rewrap_can_drop_recovery():
    code = "aB3xK9mP2qW7nR5t"
    blob = crypto.encrypt(b"x", "pw12345678", recovery_code=code)
    u = crypto.unlock(blob, "pw12345678")
    new_blob = crypto.rewrap(blob, u.dek, new_password="pw12345678",
                             new_recovery_code=None)
    assert not crypto.has_recovery(new_blob)


def test_rewrap_can_add_recovery():
    blob = crypto.encrypt(b"x", "pw12345678")
    u = crypto.unlock(blob, "pw12345678")
    new_blob = crypto.rewrap(blob, u.dek, new_password="pw12345678",
                             new_recovery_code="aB3xK9mP2qW7nR5t")
    assert crypto.has_recovery(new_blob)
    assert crypto.unlock_with_recovery(
        new_blob, "aB3xK9mP2qW7nR5t").plaintext == b"x"


# ---------------------------------------------------------------- 旧版兼容
def test_legacy_detection():
    assert crypto.is_legacy(b"ETXT1\0" + b"\x00" * 100)
    assert not crypto.is_legacy(crypto.encrypt(b"x", "pw12345678"))


def test_legacy_decrypt_still_works():
    """旧版 ETXT1 文件必须仍能打开（用户已有的文件不能失效）。"""
    import hashlib
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    pw = "legacy-password"
    plain = b"old file content"
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 15, r=8, p=1,
                         dklen=32, maxmem=128 * 2 ** 15 * 8 * 2)
    ct = AESGCM(key).encrypt(nonce, plain, b"ETXT1\0")
    legacy = b"ETXT1\0" + salt + nonce + ct

    assert crypto.is_legacy(legacy)
    assert crypto.decrypt_legacy(legacy, pw) == plain
