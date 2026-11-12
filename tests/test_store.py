"""store 层单元测试。"""

import time

import pytest

from etxt import store


def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "a.etxt"
    store.atomic_write(p, b"hello")
    assert p.read_bytes() == b"hello"


def test_atomic_write_overwrites(tmp_path):
    p = tmp_path / "a.etxt"
    store.atomic_write(p, b"old")
    store.atomic_write(p, b"new")
    assert p.read_bytes() == b"new"


def test_atomic_write_leaves_no_temp(tmp_path):
    p = tmp_path / "a.etxt"
    store.atomic_write(p, b"x" * 1000)
    leftovers = [f for f in tmp_path.iterdir() if f.name != "a.etxt"]
    assert leftovers == [], f"残留临时文件：{leftovers}"


def test_atomic_write_missing_dir(tmp_path):
    with pytest.raises(store.StoreError):
        store.atomic_write(tmp_path / "nope" / "a.etxt", b"x")


def test_read_missing_file(tmp_path):
    with pytest.raises(store.StoreError):
        store.read_etxt(tmp_path / "missing.etxt")


def test_read_roundtrip(tmp_path):
    p = tmp_path / "a.etxt"
    data = b"\x00\x01\x02binary"
    store.atomic_write(p, data)
    assert store.read_etxt(p) == data


def test_password_cache_basic():
    c = store.PasswordCache(ttl_seconds=60)
    assert c.get() is None
    c.put("secret")
    assert c.get() == "secret"


def test_password_cache_expiry():
    c = store.PasswordCache(ttl_seconds=0.05)
    c.put("secret")
    assert c.get() == "secret"
    time.sleep(0.08)
    assert c.get() is None


def test_password_cache_touch_extends():
    c = store.PasswordCache(ttl_seconds=0.3)
    c.put("secret")
    time.sleep(0.2)
    c.touch()
    time.sleep(0.2)
    assert c.get() == "secret", "touch 应刷新有效期"


def test_password_cache_clear():
    c = store.PasswordCache()
    c.put("secret")
    c.clear()
    assert c.get() is None


def test_password_cache_remaining():
    c = store.PasswordCache(ttl_seconds=60)
    assert c.remaining == 0.0
    c.put("secret")
    assert 55 < c.remaining <= 60
