"""按参考图精确几何绘制图标，生成多尺寸 .ico。

几何参数全部来自对参考图的像素级实测（已排除 Shutterstock 水印）：

  图形包围盒          261 x 350 px   (宽高比 0.7457)
  线宽                11 px          (占图形宽 4.21%)
  左上/左下/右下圆角  约 21 px        (占图形宽 8.0%)
  右上折角            顶边到 (0.7203, 0)，再斜切到 (1.0, 0.2029)

  锁梁（空心环，外拱 + 内拱）:
    外拱   x 0.2720 ~ 0.7280   顶 y 0.2857
    内拱   x 0.3602 ~ 0.6398
  锁体（圆角矩形环）:
    x 0.2146 ~ 0.7854          y 0.5714 ~ 0.8286
    高宽比 179/149 = 1.201

绘制方式
--------
用「外轮廓填充 + 内轮廓挖空」得到等宽线条。
超采样 8 倍后 LANCZOS 降采样，消除 PIL 无抗锯齿的锯齿。
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "assets"

# ---- 实测几何（归一化到图形包围盒）
ASPECT = 0.7457           # 宽 / 高
STROKE_NORM = 0.0421      # 线宽 / 图形宽度
CORNER_NORM = 0.080       # 圆角半径 / 图形宽度

FOLD_X = 0.7203           # 顶部横线右端
FOLD_Y = 0.2029           # 折角纵向终点

# 锁梁
SHACKLE_OUT_L = 0.2720
SHACKLE_OUT_R = 0.7280
SHACKLE_TOP = 0.2857
SHACKLE_IN_L = 0.3602
SHACKLE_IN_R = 0.6398

# 锁体
LOCK_L = 0.2146
LOCK_R = 0.7854
LOCK_TOP = 0.5457        # 锁体顶（实测：宽 147px 横边起点）
LOCK_BOTTOM = 0.8543      # 锁体底（实测）
LOCK_RADIUS_NORM = 0.035   # 锁体圆角（相对图形宽度）

INK = (26, 26, 26, 255)          # 黑色线条
FILL = (224, 224, 224, 255)      # 灰色填充（文档内部）

# 为什么需要灰色填充
# ----------------
# 纯黑线图标在 Windows 深色主题（资源管理器背景 RGB 25,25,25）下
# 几乎完全不可见 —— 实测图标主色 26 vs 背景 25，只差 1。
# 加灰色填充后：
#   深色主题：灰色块清晰可见
#   浅色主题：灰色块 + 黑线条，对比度足够
# 这也是 Windows 自带文本文档图标的做法（浅底 + 深色线条）。


class Geo:
    """归一化坐标 -> 像素坐标。

    适配逻辑（修正版）
    -----------------
    旧实现：先取 BOX_W = 可用宽度，再算 BOX_H = BOX_W / ASPECT。
    由于 ASPECT = 0.7457 < 1（高 > 宽），高度会超出可用区域，
    于是被迫改成「按高度适配」，宽度被压缩到 68.6% —— 图标显得偏小。

    正确做法：**同时**约束宽高，取能放下的最大尺寸：
        scale = min(avail_w / 1, avail_h / (1/ASPECT))
    即宽最多占 avail_w，高最多占 avail_h，按比例取小者。
    这样文档轮廓能真正撑满可用区域。
    """

    def __init__(self, canvas: int, margin: float = 0.0):
        avail = canvas * (1 - 2 * margin)
        # 归一化尺寸：宽 1，高 1/ASPECT
        need_w = 1.0
        need_h = 1.0 / ASPECT
        scale = min(avail / need_w, avail / need_h)
        self.box_w = need_w * scale
        self.box_h = need_h * scale
        self.box_x = (canvas - self.box_w) / 2
        self.box_y = (canvas - self.box_h) / 2
        self.canvas = canvas
        self.stroke = max(1.0, self.box_w * STROKE_NORM)

    def x(self, n):
        return self.box_x + n * self.box_w

    def y(self, n):
        return self.box_y + n * self.box_h


def _arc_pts(cx, cy, r, a0, a1, steps=10):
    """生成圆弧上的点（角度制，顺时针）。"""
    pts = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def doc_polygon(g: Geo, inset: float = 0.0):
    """文档轮廓：左上圆角 -> 顶边 -> 折角 -> 右边 -> 右下圆角
    -> 底边 -> 左下圆角 -> 左边 -> 左上圆角。"""
    r = max(0.5, CORNER_NORM * g.box_w - inset)
    x0, y0 = g.x(0) + inset, g.y(0) + inset
    x1, y1 = g.x(1) - inset, g.y(1) - inset
    fx, fy = g.x(FOLD_X), g.y(FOLD_Y)

    pts = []
    # 顶边（从左圆角结束到折角起点）
    pts.append((x0 + r, y0))
    pts.append((fx, y0))
    # 折角斜边
    pts.append((x1, fy))
    # 右边到右下圆角起点
    pts.append((x1, y1 - r))
    # 右下圆角 0° -> 90°
    pts += _arc_pts(x1 - r, y1 - r, r, 0, 90)
    # 底边到左下圆角
    pts.append((x0 + r, y1))
    # 左下圆角 90° -> 180°
    pts += _arc_pts(x0 + r, y1 - r, r, 90, 180)
    # 左边到左上圆角
    pts.append((x0, y0 + r))
    # 左上圆角 180° -> 270°
    pts += _arc_pts(x0 + r, y0 + r, r, 180, 270)
    return pts


def shackle_outer(g: Geo):
    """锁梁**外层**拱：细线环（外沿 x 0.2720~0.7280，线宽 = 标准线宽）。

    参考图的锁梁是「双层嵌套的两条细拱」，不是一条粗壁。
    放大 6 倍可清楚看到：外层大拱与内层小拱之间有空隙，
    两者线宽相同（都是 11px / 4.21%）。
    """
    ol, orr = g.x(SHACKLE_OUT_L), g.x(SHACKLE_OUT_R)
    top = g.y(SHACKLE_TOP)
    bottom = g.y(LOCK_TOP) + (g.y(LOCK_BOTTOM) - g.y(LOCK_TOP)) * 0.10
    sw = g.stroke

    cx = (ol + orr) / 2
    rad = (orr - ol) / 2
    cy = top + rad

    outer = [(ol, bottom), (ol, cy)]
    outer += _arc_pts(cx, cy, rad, 180, 360, 18)
    outer += [(orr, bottom)]
    return outer


def shackle_outer_inner(g: Geo):
    """外层拱的内侧轮廓（挖空用），半径减一个线宽。"""
    ol, orr = g.x(SHACKLE_OUT_L), g.x(SHACKLE_OUT_R)
    top = g.y(SHACKLE_TOP)
    bottom = g.y(LOCK_TOP) + (g.y(LOCK_BOTTOM) - g.y(LOCK_TOP)) * 0.10
    sw = g.stroke

    cx = (ol + orr) / 2
    rad = (orr - ol) / 2 - sw
    cy = top + rad + sw

    pts = [(ol + sw, bottom), (ol + sw, cy)]
    pts += _arc_pts(cx, cy, rad, 180, 360, 18)
    pts += [(orr - sw, bottom)]
    return pts


def shackle_inner_ring(g: Geo):
    """锁梁**内层**拱（实心填充），外沿 x 0.3602~0.6398。"""
    il, ir = g.x(SHACKLE_IN_L), g.x(SHACKLE_IN_R)
    top = g.y(SHACKLE_TOP)
    bottom = g.y(LOCK_TOP) + (g.y(LOCK_BOTTOM) - g.y(LOCK_TOP)) * 0.10

    cx = (il + ir) / 2
    rad = (ir - il) / 2
    # 内层拱顶 = 外层拱顶 + 壁厚 + 空隙（实测内层比外层低约一个线宽）
    cy = top + (g.x(SHACKLE_OUT_R) - g.x(SHACKLE_OUT_L)) / 2

    pts = [(il, bottom), (il, cy)]
    pts += _arc_pts(cx, cy, rad, 180, 360, 18)
    pts += [(ir, bottom)]
    return pts


def shackle_inner_ring_hole(g: Geo):
    """内层拱的挖空部分（半径减一个线宽）。"""
    il, ir = g.x(SHACKLE_IN_L), g.x(SHACKLE_IN_R)
    top = g.y(SHACKLE_TOP)
    bottom = g.y(LOCK_TOP) + (g.y(LOCK_BOTTOM) - g.y(LOCK_TOP)) * 0.10
    sw = g.stroke

    cx = (il + ir) / 2
    rad = (ir - il) / 2 - sw
    cy = top + (g.x(SHACKLE_OUT_R) - g.x(SHACKLE_OUT_L)) / 2

    pts = [(il + sw, bottom), (il + sw, cy)]
    pts += _arc_pts(cx, cy, rad, 180, 360, 18)
    pts += [(ir - sw, bottom)]
    return pts


def rounded_rect(g: Geo, inset: float = 0.0):
    x0, y0 = g.x(LOCK_L) + inset, g.y(LOCK_TOP) + inset
    x1, y1 = g.x(LOCK_R) - inset, g.y(LOCK_BOTTOM) - inset
    r = max(0.5, LOCK_RADIUS_NORM * g.box_w - inset)

    pts = []
    pts += _arc_pts(x1 - r, y0 + r, r, 270, 360)   # 右上
    pts += _arc_pts(x1 - r, y1 - r, r, 0, 90)      # 右下
    pts += _arc_pts(x0 + r, y1 - r, r, 90, 180)    # 左下
    pts += _arc_pts(x0 + r, y0 + r, r, 180, 270)   # 左上
    return pts


def auto_margin(size: int) -> float:
    """按图标尺寸选边距，与 Windows 自带文档图标一致。

    实测系统 .txt 图标的内容高度占比：
        16~32px  -> 100%（小图标不留边距，保证可辨识）
        48px+    -> 93.8%（留约 3% 边距，避免视觉过大）

    这个分尺寸策略值得照抄：小图标本来像素就紧张，
    再留边距会导致细节糊成一团。
    """
    return 0.0 if size <= 32 else 0.031


def draw_icon(size: int, ss: int = 8, margin: float | None = None) -> Image.Image:
    if margin is None:
        margin = auto_margin(size)
    canvas = size * ss
    g = Geo(canvas, margin)
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sw = g.stroke

    # ---- 绘制策略：文档内部**全部**填灰，黑色线条画在灰色之上。
    #
    # 关键：镂空处填 FILL（灰）而不是透明。
    # 之前填透明，深色主题下锁的镂空透出背景色，
    # 整个锁看起来是一坨黑块（实测踩过）。
    # 全部用灰/黑两色，两种主题下都稳定。

    # 0) 整个文档区域铺灰
    d.polygon(doc_polygon(g, 0), fill=FILL)

    # 1) 文档轮廓：黑线环（内侧填回灰）
    d.polygon(doc_polygon(g, 0), fill=INK)
    d.polygon(doc_polygon(g, sw), fill=FILL)

    # 2) 锁梁：两层细拱，镂空填灰
    d.polygon(shackle_outer(g), fill=INK)
    d.polygon(shackle_outer_inner(g), fill=FILL)
    d.polygon(shackle_inner_ring(g), fill=INK)
    d.polygon(shackle_inner_ring_hole(g), fill=FILL)

    # 3) 锁体：黑线环，内部填灰
    d.polygon(rounded_rect(g, 0), fill=INK)
    d.polygon(rounded_rect(g, sw), fill=FILL)

    # 4) 钥匙孔：黑色实心圆 + 竖线
    lx0, lx1 = g.x(LOCK_L), g.x(LOCK_R)
    cx = (lx0 + lx1) / 2
    kh_r = g.box_w * 0.048
    kh_cy = g.y(0.668)
    d.ellipse([cx - kh_r, kh_cy - kh_r, cx + kh_r, kh_cy + kh_r], fill=INK)
    tail_w = g.box_w * 0.038
    d.rectangle([cx - tail_w / 2, kh_cy,
                 cx + tail_w / 2, g.y(0.766)], fill=INK)

    return img.resize((size, size), Image.LANCZOS)


def make_ico(path: Path, sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)) -> None:
    frames = [draw_icon(s) for s in sizes]
    frames[-1].save(path, format="ICO",
                    sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])
    print("ICO:", path, f"({len(sizes)} 尺寸)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    preview = draw_icon(256)
    preview.save(OUT_DIR / "etxt-256.png")
    preview.resize((512, 512), Image.LANCZOS).save(OUT_DIR / "_gen_512.png")
    print("预览:", OUT_DIR / "_gen_512.png")

    make_ico(OUT_DIR / "etxt.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





