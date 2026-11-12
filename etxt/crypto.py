"""加密格式：信封加密（envelope encryption）+ 恢复码。

设计
----
明文**不直接用密码加密**。改为：

1. 生成一个随机 **主密钥 (DEK)**，32 字节，只用于加密正文
2. 正文用 DEK 做 AES-256-GCM 加密
3. DEK 再被**分别封装两份**：
   - 用「密码」派生的密钥 (KEK_pw) 封装
   - 用「恢复码」派生的密钥 (KEK_rc) 封装
4. 两个封装结果都存进文件

为什么这样设计
--------------
- 改密码 / 用恢复码重置密码时，**不需要重新加密正文**，只重写被封装的那 32 字节
- 恢复码和密码是**两个独立通道**，任一个都能解开 DEK
- 代价（必然的）：拿到文件和恢复码的人能解开。这是「可恢复」的固有代价，
  不是实现缺陷。

文件格式（小端）
----------------
::

    offset  size   field
    0       6      magic  = b"ETXT2\\0"
    6       1      version = 2
    7       1      flags（bit0 = 含恢复码）
    8       16     salt_pw     (密码派生用)
    24      16     salt_rc     (恢复码派生用，无恢复码时全 0)
    40      12     nonce_body  (正文 GCM)
    52      12     nonce_wrap_pw (密码封装 DEK 用)
    64      12     nonce_wrap_rc (恢复码封装 DEK 用)
    76      4      body_len    (密文长度，不含 tag)
    80      16     wrapped_pw  (DEK 密文 + tag = 32+16 = 48 字节)
    ...     48     wrapped_rc  (无恢复码时为 0)

    wrapped 块固定 48 字节（32 字节 DEK + 16 字节 GCM tag）。
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ETXT2\0"
VERSION = 2

SALT_LEN = 16
NONCE_LEN = 12
DEK_LEN = 32
TAG_LEN = 16
WRAP_LEN = DEK_LEN + TAG_LEN      # 48

FLAG_HAS_RECOVERY = 0x01

# 偏移表
OFF_MAGIC = 0
OFF_VERSION = 6
OFF_FLAGS = 7
OFF_SALT_PW = 8
OFF_SALT_RC = 24
OFF_NONCE_BODY = 40
OFF_NONCE_WRAP_PW = 52
OFF_NONCE_WRAP_RC = 64
OFF_BODY_LEN = 76
OFF_WRAPPED_PW = 80
OFF_WRAPPED_RC = OFF_WRAPPED_PW + WRAP_LEN   # 128

HEADER_LEN = OFF_WRAPPED_RC + WRAP_LEN        # 176

# scrypt 参数：n=2^15 本机实测约 82ms，是「可接受延迟 / 足够昂贵」的平衡点
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32

# 恢复码：16 位字母数字
RECOVERY_LEN = 16
_RECOVERY_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)

_AAD_BODY = b"ETXT2-body"
_AAD_WRAP_PW = b"ETXT2-wrap-pw"
_AAD_WRAP_RC = b"ETXT2-wrap-rc"


class EtxtError(Exception):
    """本工具所有可预期错误的基类。"""


class WrongPassword(EtxtError):
    """密码 / 恢复码错误，或文件被篡改。刻意不区分，避免判定 oracle。"""


class NotEtxtFile(EtxtError):
    """文件头不是 ETXT2 格式。"""


class NoRecovery(EtxtError):
    """该文件没有设置恢复码。"""


@dataclass(frozen=True)
class KdfParams:
    n: int = SCRYPT_N
    r: int = SCRYPT_R
    p: int = SCRYPT_P


def derive_key(secret: str, salt: bytes, params: KdfParams = KdfParams()) -> bytes:
    """把口令 / 恢复码派生成 32 字节密钥。"""
    if not isinstance(secret, str):
        raise TypeError("secret must be str")
    if len(salt) != SALT_LEN:
        raise ValueError(f"salt must be {SALT_LEN} bytes")
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=params.n, r=params.r, p=params.p,
        dklen=KEY_LEN,
        maxmem=128 * params.n * params.r * 2,
    )


# ---------------------------------------------------------------- 恢复码
def generate_recovery_code(length: int = RECOVERY_LEN) -> str:
    """生成一个 16 位字母数字恢复码。

    用 `secrets` 而不是 `random` —— 这是密钥材料，必须用密码学安全随机源。
    """
    import secrets
    alphabet = _RECOVERY_ALPHABET
    return "".join(secrets.choice(alphabet) for _ in range(length))


def normalize_recovery_code(code: str) -> str:
    """规范化用户输入：去空格 / 连字符 / 常见分隔符，保留大小写。"""
    return "".join(ch for ch in code if ch.isalnum())


def format_recovery_code(code: str) -> str:
    """展示用：每 4 位加连字符，便于抄写。"""
    c = normalize_recovery_code(code)
    return "-".join(c[i:i + 4] for i in range(0, len(c), 4))


def is_valid_recovery_code(code: str) -> bool:
    c = normalize_recovery_code(code)
    return len(c) == RECOVERY_LEN and c.isalnum()


# ---------------------------------------------------------------- 加密
def encrypt(plaintext: bytes, password: str, *,
            recovery_code: str | None = None,
            kdf: KdfParams = KdfParams()) -> bytes:
    """信封加密。recovery_code 非空时同时封装一份恢复通道。"""
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext must be bytes")

    dek = os.urandom(DEK_LEN)
    salt_pw = os.urandom(SALT_LEN)
    nonce_body = os.urandom(NONCE_LEN)
    nonce_wrap_pw = os.urandom(NONCE_LEN)

    kek_pw = derive_key(password, salt_pw, kdf)
    body = AESGCM(dek).encrypt(nonce_body, bytes(plaintext), _AAD_BODY)
    wrapped_pw = AESGCM(kek_pw).encrypt(nonce_wrap_pw, dek, _AAD_WRAP_PW)

    has_rc = recovery_code is not None and recovery_code != ""
    if has_rc:
        rc = normalize_recovery_code(recovery_code)
        salt_rc = os.urandom(SALT_LEN)
        nonce_wrap_rc = os.urandom(NONCE_LEN)
        kek_rc = derive_key(rc, salt_rc, kdf)
        wrapped_rc = AESGCM(kek_rc).encrypt(nonce_wrap_rc, dek, _AAD_WRAP_RC)
    else:
        salt_rc = b"\x00" * SALT_LEN
        nonce_wrap_rc = b"\x00" * NONCE_LEN
        wrapped_rc = b"\x00" * WRAP_LEN

    flags = FLAG_HAS_RECOVERY if has_rc else 0

    out = bytearray()
    out += MAGIC
    out += bytes([VERSION, flags])
    out += salt_pw
    out += salt_rc
    out += nonce_body
    out += nonce_wrap_pw
    out += nonce_wrap_rc
    out += struct.pack("<I", len(body) - TAG_LEN)
    out += wrapped_pw
    out += wrapped_rc
    out += body
    return bytes(out)


# ---------------------------------------------------------------- 解密
@dataclass(frozen=True)
class Unlocked:
    """解密结果：明文 + 主密钥（用于改密码 / 重置）。"""

    plaintext: bytes
    dek: bytes


def decrypt(blob: bytes, password: str) -> bytes:
    """用密码解密，返回明文。"""
    return unlock(blob, password).plaintext


def unlock(blob: bytes, password: str) -> Unlocked:
    """用密码解开信封，返回明文与主密钥。"""
    hdr = _parse(blob)
    kek = derive_key(password, hdr.salt_pw)
    try:
        dek = AESGCM(kek).decrypt(hdr.nonce_wrap_pw, hdr.wrapped_pw, _AAD_WRAP_PW)
    except InvalidTag:
        raise WrongPassword("密码错误，或文件已损坏") from None
    return Unlocked(_open_body(blob, hdr, dek), dek)


def unlock_with_recovery(blob: bytes, recovery_code: str) -> Unlocked:
    """用恢复码解开信封。"""
    hdr = _parse(blob)
    if not hdr.has_recovery:
        raise NoRecovery("这个文件没有设置恢复码")
    rc = normalize_recovery_code(recovery_code)
    kek = derive_key(rc, hdr.salt_rc)
    try:
        dek = AESGCM(kek).decrypt(hdr.nonce_wrap_rc, hdr.wrapped_rc, _AAD_WRAP_RC)
    except InvalidTag:
        raise WrongPassword("恢复码错误，或文件已损坏") from None
    return Unlocked(_open_body(blob, hdr, dek), dek)


def has_recovery(blob: bytes) -> bool:
    """文件是否带恢复通道（不解密）。"""
    try:
        return _parse(blob).has_recovery
    except EtxtError:
        return False


def rewrap(blob: bytes, dek: bytes, *,
           new_password: str,
           new_recovery_code: str | None = None,
           kdf: KdfParams = KdfParams()) -> bytes:
    """只重写信封头（换密码 / 换恢复码），**不重新加密正文**。

    这是信封加密的核心收益：改密码的代价与文件大小无关。
    """
    hdr = _parse(blob)
    body = blob[HEADER_LEN:]

    salt_pw = os.urandom(SALT_LEN)
    nonce_wrap_pw = os.urandom(NONCE_LEN)
    kek_pw = derive_key(new_password, salt_pw, kdf)
    wrapped_pw = AESGCM(kek_pw).encrypt(nonce_wrap_pw, dek, _AAD_WRAP_PW)

    has_rc = new_recovery_code is not None and new_recovery_code != ""
    if has_rc:
        rc = normalize_recovery_code(new_recovery_code)
        salt_rc = os.urandom(SALT_LEN)
        nonce_wrap_rc = os.urandom(NONCE_LEN)
        kek_rc = derive_key(rc, salt_rc, kdf)
        wrapped_rc = AESGCM(kek_rc).encrypt(nonce_wrap_rc, dek, _AAD_WRAP_RC)
    else:
        salt_rc = b"\x00" * SALT_LEN
        nonce_wrap_rc = b"\x00" * NONCE_LEN
        wrapped_rc = b"\x00" * WRAP_LEN

    flags = FLAG_HAS_RECOVERY if has_rc else 0

    out = bytearray()
    out += MAGIC
    out += bytes([VERSION, flags])
    out += salt_pw
    out += salt_rc
    out += hdr.nonce_body
    out += nonce_wrap_pw
    out += nonce_wrap_rc
    out += struct.pack("<I", len(body) - TAG_LEN)
    out += wrapped_pw
    out += wrapped_rc
    out += body
    return bytes(out)


# ---------------------------------------------------------------- 内部
@dataclass(frozen=True)
class _Header:
    version: int
    flags: int
    salt_pw: bytes
    salt_rc: bytes
    nonce_body: bytes
    nonce_wrap_pw: bytes
    nonce_wrap_rc: bytes
    body_len: int
    wrapped_pw: bytes
    wrapped_rc: bytes

    @property
    def has_recovery(self) -> bool:
        return bool(self.flags & FLAG_HAS_RECOVERY)


def _parse(blob: bytes) -> _Header:
    if len(blob) < HEADER_LEN + TAG_LEN:
        raise NotEtxtFile("文件太小，不是有效的 ETXT2 文件")
    if blob[OFF_MAGIC:OFF_MAGIC + len(MAGIC)] != MAGIC:
        raise NotEtxtFile("文件头不是 ETXT2，可能不是加密文件或已损坏")
    version = blob[OFF_VERSION]
    if version != VERSION:
        raise NotEtxtFile(f"不支持的文件版本：{version}")
    flags = blob[OFF_FLAGS]
    body_len = struct.unpack("<I", blob[OFF_BODY_LEN:OFF_BODY_LEN + 4])[0]

    expected = HEADER_LEN + body_len + TAG_LEN
    if len(blob) != expected:
        raise NotEtxtFile(
            f"文件长度不符（期望 {expected}，实际 {len(blob)}），可能被截断")

    return _Header(
        version=version, flags=flags,
        salt_pw=blob[OFF_SALT_PW:OFF_SALT_PW + SALT_LEN],
        salt_rc=blob[OFF_SALT_RC:OFF_SALT_RC + SALT_LEN],
        nonce_body=blob[OFF_NONCE_BODY:OFF_NONCE_BODY + NONCE_LEN],
        nonce_wrap_pw=blob[OFF_NONCE_WRAP_PW:OFF_NONCE_WRAP_PW + NONCE_LEN],
        nonce_wrap_rc=blob[OFF_NONCE_WRAP_RC:OFF_NONCE_WRAP_RC + NONCE_LEN],
        body_len=body_len,
        wrapped_pw=blob[OFF_WRAPPED_PW:OFF_WRAPPED_PW + WRAP_LEN],
        wrapped_rc=blob[OFF_WRAPPED_RC:OFF_WRAPPED_RC + WRAP_LEN],
    )


def _open_body(blob: bytes, hdr: _Header, dek: bytes) -> bytes:
    body = blob[HEADER_LEN:HEADER_LEN + hdr.body_len + TAG_LEN]
    try:
        return AESGCM(dek).decrypt(hdr.nonce_body, body, _AAD_BODY)
    except InvalidTag:
        raise WrongPassword("文件正文已损坏") from None


def is_etxt(blob: bytes) -> bool:
    """快速判断是否像 ETXT2 文件（不验证密码）。"""
    return len(blob) >= HEADER_LEN + TAG_LEN and blob[:len(MAGIC)] == MAGIC


# ---------------------------------------------------------------- 兼容 v1
_LEGACY_MAGIC = b"ETXT1\0"
_LEGACY_SALT_LEN = 16
_LEGACY_NONCE_LEN = 12
_LEGACY_HEADER_LEN = len(_LEGACY_MAGIC) + _LEGACY_SALT_LEN + _LEGACY_NONCE_LEN


def is_legacy(blob: bytes) -> bool:
    """是否是旧版 ETXT1 文件（无恢复码、无信封）。"""
    return blob[:len(_LEGACY_MAGIC)] == _LEGACY_MAGIC


def decrypt_legacy(blob: bytes, password: str) -> bytes:
    """解开旧版 ETXT1 文件（只为兼容已存在的文件）。"""
    if len(blob) < _LEGACY_HEADER_LEN + TAG_LEN:
        raise NotEtxtFile("文件太小，不是有效的 ETXT1 文件")
    salt = blob[len(_LEGACY_MAGIC):len(_LEGACY_MAGIC) + _LEGACY_SALT_LEN]
    nonce = blob[len(_LEGACY_MAGIC) + _LEGACY_SALT_LEN:_LEGACY_HEADER_LEN]
    ct = blob[_LEGACY_HEADER_LEN:]
    kek = derive_key(password, salt)
    try:
        return AESGCM(kek).decrypt(nonce, ct, _LEGACY_MAGIC)
    except InvalidTag:
        raise WrongPassword("密码错误，或文件已损坏") from None
