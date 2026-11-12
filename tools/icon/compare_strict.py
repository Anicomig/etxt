"""严格同尺寸对比：把参考图和生成图都归一化到相同内容高度，再并排。

上一版对比图的问题：参考图裁切后拉伸到 400x400，生成图直接贴 256，
两者内容占比不同，视觉上线宽差异被放大。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
REF = Path(os.environ.get("ETXT_REF_ICON",
         Path(__file__).resolve().parent.parent.parent / "assets" / "_ref.jpg"))


def content_bbox(im: Image.Image, th: int = 10):
    """返回内容的包围盒。"""
    g = im.convert("RGBA")
    W, H = g.size
    px = g.load()
    minx, miny, maxx, maxy = W, H, 0, 0
    for y in range(H):
        for x in range(W):
            a = px[x, y][3]
            v = px[x, y][0]
            if a > th and v < 200:      # 不透明且偏黑
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    return minx, miny, maxx, maxy


def normalize(im: Image.Image, target_h: int) -> Image.Image:
    """裁到内容，再缩放到统一的内容高度，居中放到白底方图。"""
    box = content_bbox(im)
    crop = im.crop(box).convert("RGBA")
    w, h = crop.size
    scale = target_h / h
    nw, nh = max(1, round(w * scale)), target_h
    crop = crop.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGBA", (target_h + 40, target_h + 40), (255, 255, 255, 255))
    ox = (canvas.width - nw) // 2
    oy = (canvas.height - nh) // 2
    canvas.paste(crop, (ox, oy), crop)
    return canvas


def main() -> int:
    target_h = 400

    ref = Image.open(REF).convert("RGBA")
    # 参考图裁掉底部水印文字（y > 480）
    ref = ref.crop((0, 0, ref.width, 480))

    gen = Image.open(ASSETS / "etxt-512.png")

    a = normalize(ref, target_h)
    b = normalize(gen, target_h)

    pad = 20
    W = a.width + b.width + pad * 3
    H = max(a.height, b.height) + 50
    out = Image.new("RGB", (W, H), "#e8e8e8")
    out.paste(a, (pad, 10), a)
    out.paste(b, (pad * 2 + a.width, 10), b)

    d = ImageDraw.Draw(out)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
    except Exception:
        f = ImageFont.load_default()
    d.text((pad + 100, H - 32), "参考图", fill="#333333", font=f)
    d.text((pad * 2 + a.width + 90, H - 32), "生成图", fill="#333333", font=f)

    out_path = ASSETS / "_compare_strict.png"
    out.save(out_path)
    print("严格对比图:", out_path, out.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


