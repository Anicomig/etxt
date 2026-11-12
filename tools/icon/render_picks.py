"""按 demo_icon_pick.py 的 PICKS 列表，渲染一张大尺寸对照图。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_icon_pick import PICKS
from render_icons import extract_icon

OUT = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick" / "_对照图.png"


def main() -> int:
    cols = 5
    cell_w, cell_h = 170, 150
    rows = (len(PICKS) + cols - 1) // cols
    W, H = cols * cell_w, rows * cell_h + 40
    canvas = Image.new("RGB", (W, H), "#202020")
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
        font_s = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
    except Exception:
        font = font_s = ImageFont.load_default()

    d.text((12, 10), "etxt 图标候选（放大 96px）— 按编号告诉我要哪个",
           fill="#ffffff", font=font)

    for i, (num, desc, icon) in enumerate(PICKS):
        r, c = divmod(i, cols)
        x = c * cell_w + 20
        y = r * cell_h + 44

        src = icon.rsplit(",", 1)[0].strip('"')
        idx = int(icon.rsplit(",", 1)[1])
        img = extract_icon(src, idx, 96)

        if img is None:
            d.rectangle([x, y, x + 96, y + 96], outline="#ff5555")
            d.text((x + 20, y + 40), "N/A", fill="#ff5555", font=font)
        else:
            canvas.paste(img, (x, y), img)

        d.text((x, y + 102), num, fill="#4cc2ff", font=font)
        # 说明文字截断
        short = desc[:16]
        d.text((x + 22, y + 104), short, fill="#bbbbbb", font=font_s)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print("对照图:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
