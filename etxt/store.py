"""文件层：原子写回、安全删除、以及本工具的会话口令缓存。

设计要点
--------
**本工具不产生临时明文文件。**
解密后的内容直接进入内存里的编辑器控件，保存时从内存重新加密。
这是「内置编辑器」相对「外部编辑器」的核心安全收益，因此
`store` 只负责 .etxt 本身的原子读写，不提供任何明文落盘能力。
"""

from __future__ import annotations

import os
import time
from pathlib import Path


class StoreError(Exception):
    """文件读写相关的可预期错误。"""


def read_etxt(path: Path) -> bytes:
    """读取 .etxt 原始字节。"""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        raise StoreError(f"文件不存在：{path}") from None
    except PermissionError:
        raise StoreError(f"没有读取权限：{path}") from None
    except OSError as exc:
        raise StoreError(f"读取失败：{exc}") from None


def atomic_write(path: Path, data: bytes) -> None:
    """原子写回：先写同目录临时文件，fsync 后用 os.replace 顶替。

    中途失败时原文件保持完好，不会出现「写了一半的加密文件」。
    """
    path = Path(path)
    parent = path.parent
    if not parent.is_dir():
        raise StoreError(f"目录不存在：{parent}")

    tmp = parent / f".{path.name}.etxt-tmp-{os.getpid()}-{time.time_ns()}"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except PermissionError:
        _silent_unlink(tmp)
        raise StoreError(f"没有写入权限：{path}") from None
    except OSError as exc:
        _silent_unlink(tmp)
        raise StoreError(f"写入失败：{exc}") from None


def _silent_unlink(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class PasswordCache:
    """同一密码管理多个文件时，避免反复输入。

    只把口令留在内存里，并带 TTL。威胁模型不含「同机进程读内存」，
    因此这里不做额外的内存加密（做了也只是象征性）。

    每次成功解锁都会刷新时间戳，所以连续编辑多个文件只需输入一次。
    """

    def __init__(self, ttl_seconds: float = 15 * 60) -> None:
        self._ttl = ttl_seconds
        self._password: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str | None:
        if self._password is None:
            return None
        if time.monotonic() >= self._expires_at:
            self.clear()
            return None
        return self._password

    def put(self, password: str) -> None:
        self._password = password
        self._expires_at = time.monotonic() + self._ttl

    def touch(self) -> None:
        """续期（解锁成功后调用）。"""
        if self._password is not None:
            self._expires_at = time.monotonic() + self._ttl

    def clear(self) -> None:
        self._password = None
        self._expires_at = 0.0

    @property
    def remaining(self) -> float:
        if self._password is None:
            return 0.0
        return max(0.0, self._expires_at - time.monotonic())


# 进程级单例：一次会话里所有文件共用一个口令
SESSION = PasswordCache()
