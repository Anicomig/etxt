"""按参考图精确几何生成 SVG 图标，再转成多尺寸 .ico。

几何参数来自 extract_geom.py 的实测（已排除水印）：

  图形包围盒 261 x 350，宽高比 0.7457
  文档折角：右上，从 (0.720, 0) 斜切到 (1.0, 0.203)
  线条粗细 11px / 261px = 4.2%（按 24px 画布约 1.0px）
  锁体横向范围 0.218 ~ 0.782
  锁体纵向 0.286 ~ 0.854（含锁梁）

绘制策略：
- 用 1024 画布（留足精度），最后降采样
- 线条用「描边」而非填充，保证单色线条风格一致
- 圆角半径按参考图目测约 2.5%（文档角）
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick"
SVG_OUT = OUT_DIR / "_generated.svg"
PNG_OUT = OUT_DIR / "_generated_1024.png"

# ---- 画布与几何（归一化到 0..1 的「图形区域」，再映射到画布）
CANVAS = 1024
# 图形在画布中的留白（参考图 600x620 里图形占 261x350，
# 上下留白较大，这里按图标惯例收窄到 8%）
MARGIN = 0.08
BOX_W = CANVAS * (1 - 2 * MARGIN)      # 图形宽
BOX_H = BOX_W / 0.7457                  # 按参考宽高比算高
BOX_X = (CANVAS - BOX_W) / 2
BOX_Y = (CANVAS - BOX_H) / 2

STROKE = BOX_W * 0.0421                 # 实测 4.21%

# 关键点（归一化）
FOLD_X = 0.7203      # 顶部横线右端
FOLD_Y = 0.2029      # 折角纵向终点
CORNER_R = 0.028     # 文档圆角（相对宽度）

# 锁
LOCK_L = 0.2184
LOCK_R = 0.7816
LOCK_TOP = 0.2857
LOCK_BOTTOM = 0.8543
# 锁梁（上半圆弧）与锁体的分界：从数据看锁体约在 0.55 处开始
LOCK_BODY_TOP = 0.5714


def px(nx: float) -> float:
    return BOX_X + nx * BOX_W


def py(ny: float) -> float:
    return BOX_Y + ny * BOX_H


def build_svg() -> str:
    s = STROKE
    r = CORNER_R * BOX_W

    x0, y0 = px(0), py(0)
    x1, y1 = px(1), py(1)
    fx, fy = px(FOLD_X), py(FOLD_Y)

    # 文档轮廓：左上圆角 -> 顶部横线 -> 折角斜线 -> 右侧竖线
    #            -> 底部圆角 -> 左侧竖线 -> 闭合
    doc = f"""
    M {x0 + r} {y0}
    L {fx} {y0}
    L {x1} {fy}
    L {x1} {y1 - r}
    A {r} {r} 0 0 1 {x1 - r} {y1}
    L {x0 + r} {y1}
    A {r} {r} 0 0 1 {x0} {y1 - r}
    L {x0} {y0 + r}
    A {r} {r} 0 0 1 {x0 + r} {y0}
    Z
    """

    # 锁体：圆角矩形
    lx0, lx1 = px(LOCK_L), px(LOCK_R)
    ly0, ly1 = py(LOCK_BODY_TOP), py(LOCK_BOTTOM)
    lr = (lx1 - lx0) * 0.10

    body = f"""
    M {lx0 + lr} {ly0}
    L {lx1 - lr} {ly0}
    A {lr} {lr} 0 0 1 {lx1} {ly0 + lr}
    L {lx1} {ly1 - lr}
    A {lr} {lr} 0 0 1 {lx1 - lr} {ly1}
    L {lx0 + lr} {ly1}
    A {lr} {lr} 0 0 1 {lx0} {ly1 - lr}
    L {lx0} {ly0 + lr}
    A {lr} {lr} 0 0 1 {lx0 + lr} {ly0}
    Z
    """

    # 锁梁：上半圆 + 两条竖线（从锁体顶向下延伸一点）
    cx = (lx0 + lx1) / 2
    shackle_r = (lx1 - lx0) * 0.28
    shackle_top = py(LOCK_TOP)
    shackle_bottom = ly0 + (ly1 - ly0) * 0.18
    sx0 = cx - shackle_r
    sx1 = cx + shackle_r

    shackle = f"""
    M {sx0} {shackle_bottom}
    L {sx0} {shackle_top + shackle_r}
    A {shackle_r} {shackle_r} 0 0 1 {sx1} {shackle_top + shackle_r}
    L {sx1} {shackle_bottom}
    """

    # 钥匙孔：圆 + 下方小矩形
    kh_r = (lx1 - lx0) * 0.075
    kh_cy = ly0 + (ly1 - ly0) * 0.42
    kh = f"""
    M {cx - kh_r} {kh_cy}
    A {kh_r} {kh_r} 0 1 0 {cx + kh_r} {kh_cy}
    A {kh_r} {kh_r} 0 1 0 {cx - kh_r} {kh_cy}
    Z
    """
    # 钥匙孔下方缺口（描边风格：画一条竖线）
    kh_tail = f"M {cx} {kh_cy} L {cx} {ly0 + (ly1 - ly0) * 0.68}"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS}" height="{CANVAS}"
     viewBox="0 0 {CANVAS} {CANVAS}">
  <g fill="none" stroke="#1a1a1a" stroke-width="{s:.1f}"
     stroke-linecap="round" stroke-linejoin="round">
    <path d="{doc.strip()}"/>
    <path d="{shackle.strip()}"/>
    <path d="{body.strip()}"/>
    <path d="{kh_tail.strip()}"/>
    <circle cx="{cx:.1f}" cy="{kh_cy:.1f}" r="{kh_r:.1f}" fill="#1a1a1a" stroke="none"/>
  </g>
</svg>
"""


def svg_to_png(svg_path: Path, png_path: Path, size: int = CANVAS) -> bool:
    """用 cairosvg 或 svglib 渲染；都不可用时返回 False。"""
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path),
                         output_width=size, output_height=size,
                         background_color=None)
        return True
    except Exception:
        pass
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(str(svg_path))
        if drawing is None:
            return False
        scale = size / drawing.width
        drawing.scale(scale, scale)
        drawing.width = size
        drawing.height = size
        renderPM.drawToFile(drawing, str(png_path), fmt="PNG",
                            bg=0xFFFFFF, configPIL={"transparent": True})
        return True
    except Exception:
        return False


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg = build_svg()
    SVG_OUT.write_text(svg, encoding="utf-8")
    print("SVG:", SVG_OUT)

    ok = svg_to_png(SVG_OUT, PNG_OUT)
    print("PNG 渲染:", "成功" if ok else "失败（需要 cairosvg）")
    if ok:
        im = Image.open(PNG_OUT)
        print("尺寸:", im.size, "模式:", im.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
