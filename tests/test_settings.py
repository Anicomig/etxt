"""settings 层单元测试：容错与范围收敛。"""

import json
import os

import pytest

from etxt import settings


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """把配置目录指向临时目录，避免污染真实用户配置。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield tmp_path


def test_defaults_when_missing():
    data = settings.load()
    assert data == settings.DEFAULTS


def test_save_then_load(isolated_config):
    settings.save({"window_width": 1111, "window_height": 666,
                   "font_size": 13, "wrap": True})
    data = settings.load()
    assert data["window_width"] == 1111
    assert data["window_height"] == 666
    assert data["font_size"] == 13
    assert data["wrap"] is True


def test_roundtrip_preserves_all_keys(isolated_config):
    settings.save(settings.DEFAULTS)
    assert set(settings.load()) == set(settings.DEFAULTS)


def test_corrupt_json_falls_back_to_defaults(isolated_config):
    p = settings.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", encoding="utf-8")
    assert settings.load() == settings.DEFAULTS


def test_non_dict_json_falls_back(isolated_config):
    p = settings.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert settings.load() == settings.DEFAULTS


def test_size_clamped_to_bounds(isolated_config):
    settings.save({"window_width": 999999, "window_height": 1})
    data = settings.load()
    assert data["window_width"] == settings.MAX_W
    assert data["window_height"] == settings.MIN_H


def test_bad_types_are_sanitized(isolated_config):
    p = settings.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "window_width": "abc",
        "window_height": None,
        "font_size": "big",
        "window_x": "??",
    }), encoding="utf-8")
    data = settings.load()
    assert data["window_width"] == settings.DEFAULTS["window_width"]
    assert data["window_height"] == settings.DEFAULTS["window_height"]
    assert data["font_size"] == settings.DEFAULTS["font_size"]
    assert data["window_x"] is None


def test_font_size_clamped(isolated_config):
    settings.save({"font_size": 999})
    assert settings.load()["font_size"] == 40
    settings.save({"font_size": -5})
    assert settings.load()["font_size"] == 7


def test_save_leaves_no_temp_file(isolated_config):
    settings.save({"window_width": 900})
    leftovers = [f for f in settings.config_dir().iterdir()
                 if f.name != settings.FILE_NAME]
    assert leftovers == [], f"残留临时文件：{leftovers}"


def test_save_returns_bool(isolated_config):
    assert settings.save({"window_width": 900}) is True


def test_save_survives_bad_input(isolated_config):
    # 非序列化对象不应抛异常
    assert settings.save({"window_width": object()}) in (True, False)


def test_config_path_under_appdata(isolated_config):
    assert str(isolated_config) in str(settings.config_path())
