"""扫描 imageres.dll / shell32.dll 里的图标，按图形特征找出「锁 / 钥匙 / 盾牌」类。

不靠猜索引，而是批量提取后人工看图。
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from render_icons import extract_icon

OUT = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-demo" / "icons-scan.png"

SOURCES = [
    ("imageres", r"C:\Windows\System32\imageres.dll", list(range(1, 60))),
    ("imageres", r"C:\Windows\System32\imageres.dll", list(range(1000, 1080))),
    ("shell32", r"C:\Windows\System32\shell32.dll", list(range(1, 60))),
]


def main() -> int:
    items = []
    for tag, src, idxs in SOURCES:
        for idx in idxs:
            img = extract_icon(src, idx, 48)
            if img is not None:
                items.append((f"{tag}:{idx}", img))

    print("提取成功:", len(items))

    cols = 12
    cell = 74
    rows = (len(items) + cols - 1) // cols
    W, H = cols * cell, rows * cell + 30
    canvas = Image.new("RGB", (W, H), "#1f1f1f")
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 10)
    except Exception:
        font = ImageFont.load_default()

    d.text((8, 6), "扫描结果（标签 = 来源:索引）", fill="#ffffff", font=font)

    for i, (label, img) in enumerate(items):
        r, c = divmod(i, cols)
        x = c * cell + 6
        y = r * cell + 28
        canvas.paste(img, (x, y), img)
        d.text((x, y + 50), label, fill="#bbbbbb", font=font)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print("扫描图:", OUT, f"({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
