"""用 ExtractIconExW 按**索引**批量提取图标（这是最可靠的方式）。

ExtractIconExW(path, -index, ...) 用负索引表示「第 index 个图标」，
比猜资源 ID 可靠得多。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


def count_icons(path: str) -> int:
    return shell32.ExtractIconExW(path, -1, None, None, 0)


def extract_nth(path: str, index: int, size: int = 64):
    """提取第 index 个图标（0-based）。"""
    large = wintypes.HICON()
    small = wintypes.HICON()
    n = shell32.ExtractIconExW(path, index, ctypes.byref(large),
                              ctypes.byref(small), 1)
    if n == 0 or not large.value:
        return None
    try:
        return _to_image(large, size)
    finally:
        user32.DestroyIcon(large)


def _to_image(hicon, size: int):
    from enum_icons import icon_to_image
    return icon_to_image(hicon, size)


def main() -> int:
    sources = [
        ("imageres", r"C:\Windows\System32\imageres.dll"),
        ("shell32", r"C:\Windows\System32\shell32.dll"),
    ]
    out_dir = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick"
    out_dir.mkdir(parents=True, exist_ok=True)

    for tag, path in sources:
        total = count_icons(path)
        print(f"{tag}: {total} 个图标")

        rendered = []
        for i in range(min(total, 400)):
            img = extract_nth(path, i, 64)
            if img is not None:
                rendered.append((i, img))
        print(f"  成功渲染: {len(rendered)}")

        cols = 12
        cell = 90
        rows = (len(rendered) + cols - 1) // cols
        W, H = cols * cell, rows * cell + 30
        canvas = Image.new("RGB", (W, H), "#202020")
        d = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
        except Exception:
            font = ImageFont.load_default()
        d.text((8, 6), f"{tag}.dll 全部图标（标签 = 索引）", fill="white", font=font)

        for k, (idx, img) in enumerate(rendered):
            r, c = divmod(k, cols)
            x = c * cell + 12
            y = r * cell + 28
            canvas.paste(img, (x, y), img)
            d.text((x, y + 66), str(idx), fill="#4cc2ff", font=font)

        out = out_dir / f"_{tag}_all.png"
        canvas.save(out)
        print(f"  总览图: {out} ({W}x{H})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

