"""精确提取参考图几何（排除水印与底部文字）。

已确认：图形纵向 120~470，底部 610 是水印文字，忽略。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

SRC = Path(os.environ.get("ETXT_REF_ICON",
         Path(__file__).resolve().parent.parent.parent / "assets" / "_ref.jpg"))
OUT = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick" / "_geom.json"

INK = 90
Y_MAX = 480   # 只统计到这里（排除底部水印）


def main() -> int:
    im = Image.open(SRC).convert("L")
    W, H = im.size
    px = im.load()

    def ink(x, y):
        return px[x, y] < INK

    # ---- 包围盒（限 Y_MAX 内）
    minx, miny, maxx, maxy = W, H, 0, 0
    for y in range(Y_MAX):
        for x in range(W):
            if ink(x, y):
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)

    bw, bh = maxx - minx, maxy - miny
    g = {
        "image": [W, H],
        "bbox": [minx, miny, maxx, maxy],
        "size": [bw, bh],
        "aspect": round(bw / bh, 4),
    }

    def norm_x(x): return round((x - minx) / bw, 4)
    def norm_y(y): return round((y - miny) / bh, 4)

    # ---- 每行左右边界
    rows = {}
    for y in range(miny, maxy + 1):
        xs = [x for x in range(minx, maxx + 1) if ink(x, y)]
        if xs:
            rows[y] = (min(xs), max(xs))

    # ---- 找折角：右边界从「斜线增长」变「恒定」的转折点
    # 折角起点 = 右边界首次达到最大值的行
    right_max = max(r for _, r in rows.values())
    fold_y = None
    for y in sorted(rows):
        if rows[y][1] >= right_max - 1:
            fold_y = y
            break

    # 折角水平起点 = 该行左边界的水平投影（文档顶部横线的右端）
    # 实际折角顶点：顶部横线的右端点
    top_y = miny
    top_right = rows[top_y][1]

    g["fold"] = {
        "corner_y": fold_y,
        "corner_y_norm": norm_y(fold_y) if fold_y else None,
        "top_line_right_x": top_right,
        "top_line_right_x_norm": norm_x(top_right),
        "right_edge_x": right_max,
        "right_edge_x_norm": norm_x(right_max),
        # 折角斜边的水平投影长度 / 垂直投影长度
        "chamfer_dx_norm": round((right_max - top_right) / bw, 4),
        "chamfer_dy_norm": norm_y(fold_y) if fold_y else None,
    }

    # ---- 线条粗细（多行采样取中位数，更稳）
    def h_run(y):
        best = run = 0
        for x in range(minx, maxx + 1):
            if ink(x, y):
                run += 1; best = max(best, run)
            else:
                run = 0
        return best

    # 文档左右竖边：取中段若干行，测第一条连续段长度
    def first_run(y):
        run = 0
        for x in range(minx, maxx + 1):
            if ink(x, y):
                run += 1
                if run > 0 and x + 1 <= maxx and not ink(x + 1, y):
                    return run
            elif run:
                return run
        return run

    samples = [first_run(y) for y in range(miny + bh // 4, miny + 3 * bh // 4, 7)]
    samples = [s for s in samples if 0 < s < 40]
    samples.sort()
    g["stroke"] = {
        "samples": samples[:20],
        "median": samples[len(samples) // 2] if samples else None,
        "median_norm": round(samples[len(samples) // 2] / bw, 4) if samples else None,
    }

    # ---- 挂锁：在文档内部找「宽块」行（锁体）
    # 锁体特征：该行有 3 段连续 ink（左边框、锁体左、锁体右、右边框）或跨度居中
    lock_rows = {}
    for y in range(miny, maxy + 1):
        if y not in rows:
            continue
        l, r = rows[y]
        # 收集所有连续段
        segs = []
        run_start = None
        for x in range(l, r + 2):
            if x <= r and ink(x, y):
                if run_start is None:
                    run_start = x
            else:
                if run_start is not None:
                    segs.append((run_start, x - 1))
                    run_start = None
        if len(segs) >= 3:
            lock_rows[y] = segs

    g["lock_candidate_rows"] = len(lock_rows)
    if lock_rows:
        ys = sorted(lock_rows)
        g["lock_y_range"] = [ys[0], ys[-1]]
        g["lock_y_range_norm"] = [norm_y(ys[0]), norm_y(ys[-1])]
        # 取中间行看锁体的 x 范围
        mid = ys[len(ys) // 2]
        segs = lock_rows[mid]
        g["lock_mid_row"] = {
            "y": mid,
            "y_norm": norm_y(mid),
            "segments": [[norm_x(a), norm_x(b)] for a, b in segs],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(g, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
