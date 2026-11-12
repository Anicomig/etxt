"""通用密码（master password）与通用恢复码的本地保管。

设计背景
--------
用户希望「一个密码管多个文件」，且恢复码也只记一个。但程序**不能存明文
密码**，否则加密就失去意义。做法是：

1. 存一个 **verifier**：用密码派生的密钥加密一段固定串。
   输入密码时解它，能解开就说明密码正确。verifier 本身不泄露密码。
2. 存一个**被密码加密的恢复码**：用户输对密码后，程序取出恢复码，
   用它封装新文件的 DEK。这样用户只需记密码，恢复码由程序保管
   （同时提示用户自己备份）。

存放位置：`%APPDATA%\\etxt\\master.json`

安全说明
--------
- verifier 和恢复码都只用密码派生密钥（scrypt）加密，不存明文
- 文件本身不含密码；拿到 master.json 仍需暴力破解密码
- 威胁模型与主程序一致：防随手翻看 / 云同步 / 拷走，不防同机进程读内存

失败模式
--------
- master.json 损坏 / 缺失 → 视为「未设置通用密码」，下次加密重新设置
- 用户忘记通用密码 → 旧文件仍可用各自密码或恢复码打开；
  但无法再用「通用密码」加密新文件，需要重新设置
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import crypto

FILE_NAME = "master.json"
VERSION = 1

# 用于验证密码正确性的固定串（不含敏感信息，只作比对）
_VERIFIER_PLAINTEXT = b"ETXT-MASTER-VERIFIER-V1"
_AAD_VERIFIER = b"ETXT-master-verifier"
_AAD_RECOVERY = b"ETXT-master-recovery"


def master_dir() -> Path:
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "etxt"


def master_path() -> Path:
    return master_dir() / FILE_NAME


@dataclass(frozen=True)
class Master:
    """已解开的通用凭据。"""

    password: str
    recovery_code: str


# ---------------------------------------------------------------- 读取
def _load_raw() -> dict | None:
    try:
        p = master_path()
        if not p.is_file():
            return None
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        if data.get("version") != VERSION:
            return None
        for key in ("salt_pw", "nonce_verifier", "verifier",
                    "nonce_recovery", "recovery"):
            if not isinstance(data.get(key), str) or not data[key]:
                return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def is_configured() -> bool:
    """是否已经设置过通用密码。"""
    return _load_raw() is not None


# ---------------------------------------------------------------- 写入
def configure(password: str, recovery_code: str) -> bool:
    """设置 / 覆盖通用密码与恢复码。返回是否成功。"""
    if not password:
        return False
    try:
        salt = os.urandom(crypto.SALT_LEN)
        kek = crypto.derive_key(password, salt)

        nonce_v = os.urandom(crypto.NONCE_LEN)
        verifier = AESGCM(kek).encrypt(nonce_v, _VERIFIER_PLAINTEXT,
                                       _AAD_VERIFIER)

        nonce_r = os.urandom(crypto.NONCE_LEN)
        rc = crypto.normalize_recovery_code(recovery_code)
        recovery_ct = AESGCM(kek).encrypt(nonce_r, rc.encode("utf-8"),
                                          _AAD_RECOVERY)

        data = {
            "version": VERSION,
            "salt_pw": salt.hex(),
            "nonce_verifier": nonce_v.hex(),
            "verifier": verifier.hex(),
            "nonce_recovery": nonce_r.hex(),
            "recovery": recovery_ct.hex(),
        }

        d = master_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{FILE_NAME}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, master_path())
        return True
    except (OSError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------- 验证 / 取出
def verify(password: str) -> Master | None:
    """验证密码，成功则返回解开的通用凭据；失败返回 None。"""
    data = _load_raw()
    if data is None or not password:
        return None
    try:
        salt = bytes.fromhex(data["salt_pw"])
        kek = crypto.derive_key(password, salt)

        nonce_v = bytes.fromhex(data["nonce_verifier"])
        verifier = bytes.fromhex(data["verifier"])
        try:
            AESGCM(kek).decrypt(nonce_v, verifier, _AAD_VERIFIER)
        except InvalidTag:
            return None

        nonce_r = bytes.fromhex(data["nonce_recovery"])
        recovery_ct = bytes.fromhex(data["recovery"])
        rc = AESGCM(kek).decrypt(nonce_r, recovery_ct, _AAD_RECOVERY)
        return Master(password=password,
                      recovery_code=rc.decode("utf-8"))
    except (ValueError, KeyError, UnicodeDecodeError):
        return None
    except InvalidTag:
        return None


def clear() -> bool:
    """清除通用密码（用户主动重置时用）。"""
    try:
        p = master_path()
        if p.is_file():
            p.unlink()
        return True
    except OSError:
        return False
