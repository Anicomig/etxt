"""数值核对：把参考图与生成图的关键比例逐项对比。

统一方法：都先裁到内容包围盒，再归一化到「图形宽」，
这样即使像素尺寸不同也能公平比较。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

REF = Path(os.environ.get("ETXT_REF_ICON",
         Path(__file__).resolve().parent.parent.parent / "assets" / "_ref.jpg"))
GEN = Path(__file__).resolve().parent.parent.parent / "assets" / "etxt-512.png"


def load_ink(path: Path, y_limit: int | None = None):
    im = Image.open(path).convert("RGBA")
    if y_limit:
        im = im.crop((0, 0, im.width, y_limit))
    W, H = im.size
    px = im.load()

    def ink(x, y):
        r, g, b, a = px[x, y]
        return a > 128 and r < 150

    minx, miny, maxx, maxy = W, H, 0, 0
    for y in range(H):
        for x in range(W):
            if ink(x, y):
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    return ink, minx, miny, maxx, maxy


def metrics(path: Path, label: str, y_limit=None):
    ink, x0, y0, x1, y1 = load_ink(path, y_limit)
    BW, BH = x1 - x0, y1 - y0
    m = {"label": label, "size": (BW, BH), "aspect": BW / BH}

    # 线宽（左边框中段）
    mid_y = (y0 + y1) // 2
    run = best = 0
    for x in range(x0, x0 + BW // 2):
        if ink(x, mid_y):
            run += 1; best = max(best, run)
        elif run:
            break
    m["stroke_pct"] = best / BW * 100

    # 锁梁：4 段行
    for y in range(y0 + int(BH * 0.25), y0 + int(BH * 0.60)):
        segs = []
        run = 0
        for x in range(x0 + int(BW * 0.08), x1 - int(BW * 0.08)):
            if ink(x, y):
                run += 1
            else:
                if run > 0:
                    segs.append((x - run, x - 1)); run = 0
        if run > 0:
            segs.append((x1 - int(BW * 0.08) - run + 1, x1 - int(BW * 0.08)))
        if len(segs) == 4:
            m["shackle_outer"] = ((segs[1][0] - x0) / BW, (segs[2][1] - x0) / BW)
            m["shackle_inner"] = ((segs[1][1] - x0) / BW, (segs[2][0] - x0) / BW)
            m["shackle_wall_pct"] = (segs[1][1] - segs[1][0] + 1) / BW * 100
            break

    # 锁体：宽横边（> 图形宽 40%）
    tops, bots = [], []
    for y in range(y0, y1 + 1):
        segs = []
        run = 0
        for x in range(x0 + int(BW * 0.05), x1 - int(BW * 0.05)):
            if ink(x, y):
                run += 1
            else:
                if run > 0:
                    segs.append((x - run, x - 1)); run = 0
        if run > 0:
            segs.append((x1 - int(BW * 0.05) - run + 1, x1 - int(BW * 0.05)))
        wide = [s for s in segs if (s[1] - s[0]) > BW * 0.40]
        if wide and len(segs) == 1:
            ny = (y - y0) / BH
            if ny < 0.65:
                tops.append(ny)
            else:
                bots.append(ny)
    if tops:
        m["lock_top"] = tops[0]
    if bots:
        m["lock_bottom"] = bots[-1]
    if tops and bots:
        m["lock_h_pct"] = (bots[-1] - tops[0]) * BH / BW * 100

    return m


def main() -> int:
    a = metrics(REF, "参考图", y_limit=480)
    b = metrics(GEN, "生成图")

    keys = [
        ("size", "内容尺寸"),
        ("aspect", "宽高比"),
        ("stroke_pct", "线宽/图形宽 %"),
        ("shackle_wall_pct", "锁梁线宽 %"),
        ("lock_top", "锁体顶 (归一化)"),
        ("lock_bottom", "锁体底 (归一化)"),
    ]

    print(f"{'指标':<22}{'参考图':<22}{'生成图':<22}{'差异'}")
    print("-" * 78)
    for k, name in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, float):
            va_s, vb_s = f"{va:.4f}", f"{vb:.4f}" if vb is not None else "N/A"
            diff = f"{abs(va - vb):.4f}" if vb is not None else "-"
        else:
            va_s = str(va); vb_s = str(vb)
            diff = "-"
        print(f"{name:<22}{va_s:<22}{vb_s:<22}{diff}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
