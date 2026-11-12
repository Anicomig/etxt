"""用户设置持久化：记住上次的窗口尺寸 / 位置 / 缩放 / 换行。

为什么单独一个模块：
- 这些是「用户偏好」，与加密逻辑无关，不该污染 crypto / store
- 需要容错：配置文件损坏、权限不足、字段缺失都不能影响主流程
- 需要原子写：避免进程被强杀时留下半截 JSON

存放位置：`%APPDATA%\\etxt\\settings.json`
不放工作区目录，因为工作区可能被移动或删除，而偏好应该跟着用户走。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_DIR_NAME = "etxt"
FILE_NAME = "settings.json"

# 默认值：首次运行时使用
DEFAULTS: dict[str, Any] = {
    "window_width": 1000,
    "window_height": 720,
    "window_x": None,          # None = 居中
    "window_y": None,
    "maximized": False,
    "font_size": 11,
    "wrap": False,
    "status_bar": True,
}

# 尺寸合理性边界：防止损坏的配置把窗口撑爆或缩成一条线
MIN_W, MIN_H = 640, 400
MAX_W, MAX_H = 10000, 8000


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / FILE_NAME


def load() -> dict[str, Any]:
    """读取设置；任何异常都退回默认值，绝不让调用方处理。"""
    data = dict(DEFAULTS)
    try:
        p = config_path()
        if not p.is_file():
            return data
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return data
        for key in DEFAULTS:
            if key in raw:
                data[key] = raw[key]
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)
    return _sanitize(data)


def save(values: dict[str, Any]) -> bool:
    """保存设置；失败返回 False，不抛异常。"""
    try:
        data = _sanitize({**DEFAULTS, **values})
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{FILE_NAME}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, d / FILE_NAME)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
    """把字段收敛到合法范围，坏值用默认值替代。"""
    out = dict(DEFAULTS)

    def as_int(key: str, lo: int, hi: int) -> int:
        try:
            v = int(data.get(key, DEFAULTS[key]))
        except (TypeError, ValueError):
            v = int(DEFAULTS[key])
        return max(lo, min(hi, v))

    out["window_width"] = as_int("window_width", MIN_W, MAX_W)
    out["window_height"] = as_int("window_height", MIN_H, MAX_H)

    for key in ("window_x", "window_y"):
        v = data.get(key)
        if v is None:
            out[key] = None
        else:
            try:
                out[key] = int(v)
            except (TypeError, ValueError):
                out[key] = None

    out["maximized"] = bool(data.get("maximized", False))
    out["wrap"] = bool(data.get("wrap", False))
    out["status_bar"] = bool(data.get("status_bar", True))
    out["font_size"] = as_int("font_size", 7, 40)
    return out
