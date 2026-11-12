"""生成「灰色亮度 × 内容占比」的候选矩阵，供挑选。

用法:
    python icon_matrix.py           生成对比图
    python icon_matrix.py apply G M 应用指定组合（G=灰色亮度编号，M=margin编号）
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_icon as gi

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# 灰色亮度档位（RGB 单值）
GRAYS = [
    ("G0 176 当前", 176),
    ("G1 192", 192),
    ("G2 208", 208),
    ("G3 224", 224),
    ("G4 240 近白", 240),
]

# 内容占比档位（margin 越小内容越大）
MARGINS = [
    ("M0 0.08 当前", 0.08),
    ("M1 0.06", 0.06),
    ("M2 0.04", 0.04),
    ("M3 0.02", 0.02),
    ("M4 0.00 满格", 0.00),
]

CELL = 120
PAD = 8


def render_cell(gray: int, margin: float, size: int = 96) -> Image.Image:
    """按指定灰度和边距渲染一个图标。"""
    old_fill, old_margin = gi.FILL, None
    gi.FILL = (gray, gray, gray, 255)
    try:
        icon = gi.draw_icon(size, margin=margin)
    finally:
        gi.FILL = old_fill
    return icon


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) >= 4 and sys.argv[1] == "apply":
        gi_idx = int(sys.argv[2])
        m_idx = int(sys.argv[3])
        gray = GRAYS[gi_idx][1]
        margin = MARGINS[m_idx][1]
        print(f"应用: 灰色={gray}, margin={margin}")
        # 直接改源码
        src = Path(__file__).resolve().parent / "gen_icon.py"
        text = src.read_text(encoding="utf-8")
        import re
        text = re.sub(r"^FILL = \(\d+, \d+, \d+, 255\)",
                      f"FILL = ({gray}, {gray}, {gray}, 255)", text, flags=re.M)
        text = re.sub(r"def __init__\(self, canvas: int, margin: float = [\d.]+\)",
                      f"def __init__(self, canvas: int, margin: float = {margin})", text)
        text = re.sub(r"def draw_icon\(size: int, ss: int = 8, margin: float = [\d.]+\)",
                      f"def draw_icon(size: int, ss: int = 8, margin: float = {margin})", text)
        src.write_text(text, encoding="utf-8")
        print("源码已更新，请运行 gen_icon.py 重新生成")
        return 0

    # ---- 生成矩阵图
    W = PAD + len(MARGINS) * (CELL + PAD)
    H = PAD + len(GRAYS) * (CELL + PAD + 18) + 30
    canvas = Image.new("RGB", (W, H), "#1a1a1a")
    d = ImageDraw.Draw(canvas)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 12)
        f2 = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        f = f2 = ImageFont.load_default()

    d.text((PAD, 6), "灰色亮度 × 内容占比（深色主题背景）", fill="white", font=f2)

    for r, (gname, gray) in enumerate(GRAYS):
        for c, (mname, margin) in enumerate(MARGINS):
            x = PAD + c * (CELL + PAD)
            y = 28 + r * (CELL + PAD + 18)
            icon = render_cell(gray, margin, 96)
            # 深色背景
            bg = Image.new("RGB", (CELL, CELL), (25, 25, 25))
            ox = (CELL - 96) // 2
            oy = (CELL - 96) // 2
            bg.paste(icon, (ox, oy), icon)
            canvas.paste(bg, (x, y))
            label = f"{gname.split()[0]} / {mname.split()[0]}"
            d.text((x + 4, y + CELL + 2), label, fill="#999999", font=f)

    out = ASSETS / "_matrix_dark.png"
    canvas.save(out)
    print("矩阵图:", out, canvas.size)
    print()
    print("灰色档位:", ", ".join(f"{i}={g[1]}" for i, g in enumerate(GRAYS)))
    print("占比档位:", ", ".join(f"{i}={m[1]}" for i, m in enumerate(MARGINS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
