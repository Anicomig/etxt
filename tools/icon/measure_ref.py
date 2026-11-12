"""测量参考图几何参数，自动识别并避开 Shutterstock 水印区域。

水印特征：
- 中部横跨的 "shutterstock" 半透明文字
- 底部 "www.shutterstock.com · 2829171547"

这些是浅灰色（不是纯黑），可以用「深色阈值」区分：
图形线条是近黑（<80），水印是浅灰（约 150-200）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

SRC = Path(os.environ.get("ETXT_REF_ICON",
         Path(__file__).resolve().parent.parent.parent / "assets" / "_ref.jpg"))
OUT = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick" / "_measure.json"

# 图形线条是近黑；水印是浅灰。用严格阈值把水印排除掉。
INK_TH = 90


def main() -> int:
    im = Image.open(SRC).convert("L")
    W, H = im.size
    px = im.load()

    def ink(x, y):
        return px[x, y] < INK_TH

    info = {"size": [W, H], "ink_threshold": INK_TH}

    # ---- 直方图：确认阈值选得对（看有多少像素落在 90~200 之间 = 水印）
    hist = im.histogram()
    info["hist_buckets"] = {
        "0-50 (纯黑线条)": sum(hist[0:51]),
        "51-90 (线条边缘)": sum(hist[51:91]),
        "91-200 (水印灰)": sum(hist[91:201]),
        "201-255 (白底)": sum(hist[201:]),
    }

    # ---- 只统计「ink」像素的包围盒
    minx, miny, maxx, maxy = W, H, 0, 0
    for y in range(H):
        for x in range(W):
            if ink(x, y):
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    info["ink_bbox"] = [minx, miny, maxx, maxy]
    info["ink_bbox_norm"] = [
        round(minx / W, 4), round(miny / H, 4),
        round(maxx / W, 4), round(maxy / H, 4),
    ]

    bw = maxx - minx
    bh = maxy - miny
    info["ink_size"] = [bw, bh]

    # ---- 每行 ink 区间（找文档轮廓与折角）
    rows = {}
    for y in range(miny, maxy + 1):
        xs = [x for x in range(minx, maxx + 1) if ink(x, y)]
        if xs:
            rows[y] = (min(xs), max(xs))

    # 右边界随 y 变化：折角处会从斜线转为垂直
    info["right_profile"] = {
        round((y - miny) / bh, 3): round((rows[y][1] - minx) / bw, 3)
        for y in sorted(rows)[::15] if y in rows
    }
    info["left_profile"] = {
        round((y - miny) / bh, 3): round((rows[y][0] - minx) / bw, 3)
        for y in sorted(rows)[::15] if y in rows
    }

    # ---- 每列 ink 区间（找上边界与折角）
    cols = {}
    for x in range(minx, maxx + 1):
        ys = [y for y in range(miny, maxy + 1) if ink(x, y)]
        if ys:
            cols[x] = (min(ys), max(ys))
    info["top_profile"] = {
        round((x - minx) / bw, 3): round((cols[x][0] - miny) / bh, 3)
        for x in sorted(cols)[::15] if x in cols
    }

    # ---- 线条粗细
    def run_len_h(y):
        best = run = 0
        for x in range(minx, maxx + 1):
            if ink(x, y):
                run += 1; best = max(best, run)
            else:
                run = 0
        return best

    def run_len_v(x):
        best = run = 0
        for y in range(miny, maxy + 1):
            if ink(x, y):
                run += 1; best = max(best, run)
            else:
                run = 0
        return best

    # 取文档左边框中段（x 附近）测横线粗细
    mid_y = miny + bh // 2
    info["stroke_h_at_mid"] = run_len_h(mid_y)
    mid_x = minx + bw // 2
    info["stroke_v_at_mid"] = run_len_v(mid_x)

    # ---- 找挂锁区域：在文档内部，从下往上扫，找连续的宽块（锁体）
    # 锁体特征：该行的 ink 跨度明显小于文档宽度，且位于中下部
    inner_rows = {}
    for y in range(miny, maxy + 1):
        if y not in rows:
            continue
        l, r = rows[y]
        span = r - l
        # 只保留「内部元素」：跨度远小于文档宽度
        if 0 < span < bw * 0.75:
            inner_rows[y] = (l, r, span)
    info["inner_rows_count"] = len(inner_rows)
    if inner_rows:
        ys = sorted(inner_rows)
        info["inner_y_range_norm"] = [
            round((ys[0] - miny) / bh, 3),
            round((ys[-1] - miny) / bh, 3),
        ]
        info["inner_rows_sample"] = {
            round((y - miny) / bh, 3): [
                round((inner_rows[y][0] - minx) / bw, 3),
                round((inner_rows[y][1] - minx) / bw, 3),
            ]
            for y in ys[::max(1, len(ys) // 25)]
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in info.items()
                      if k in ("size", "hist_buckets", "ink_bbox",
                               "ink_bbox_norm", "ink_size",
                               "stroke_h_at_mid", "stroke_v_at_mid",
                               "inner_rows_count", "inner_y_range_norm")},
                     indent=2, ensure_ascii=False))
    print("\n完整数据:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
