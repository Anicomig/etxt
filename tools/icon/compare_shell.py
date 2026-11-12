"""对比系统 .txt 图标与自定义 .etxt 图标的实际占比。

用 SHGetFileInfo 取系统真实显示的图标（含小图标覆盖层），
再测内容的包围盒占比 —— 这样能客观判断「图标是否偏小」。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from PIL import Image

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001


class SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


def hicon_to_image(hicon, size: int):
    if not hicon:
        return None
    hdc_screen = user32.GetDC(None)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)

    class BIH(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
        ]

    class BI(ctypes.Structure):
        _fields_ = [("bmiHeader", BIH), ("bmiColors", wintypes.DWORD * 3)]

    bi = BI()
    bi.bmiHeader.biSize = ctypes.sizeof(BIH)
    bi.bmiHeader.biWidth = size
    bi.bmiHeader.biHeight = -size
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32

    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                  ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(hdc, hbmp)
    user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, 3)
    buf = ctypes.create_string_buffer(size * size * 4)
    ctypes.memmove(buf, bits, size * size * 4)
    gdi32.SelectObject(hdc, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(None, hdc_screen)
    return Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1).copy()


def shell_icon(path: str, large: bool, size: int):
    """取 Windows 实际会显示的图标。"""
    info = SHFILEINFO()
    flags = SHGFI_ICON | (SHGFI_LARGEICON if large else SHGFI_SMALLICON)
    r = shell32.SHGetFileInfoW(path, 0, ctypes.byref(info),
                               ctypes.sizeof(info), flags)
    if not r or not info.hIcon:
        return None
    try:
        return hicon_to_image(info.hIcon, size)
    finally:
        user32.DestroyIcon(info.hIcon)


def content_box(im: Image.Image):
    """内容包围盒（非透明像素）。"""
    W, H = im.size
    px = im.load()
    minx, miny, maxx, maxy = W, H, 0, 0
    for y in range(H):
        for x in range(W):
            if px[x, y][3] > 20:
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    if maxx < minx:
        return None
    return minx, miny, maxx, maxy


def report(label: str, im: Image.Image | None):
    if im is None:
        print(f"{label}: 取不到图标")
        return None
    box = content_box(im)
    if not box:
        print(f"{label}: 全透明")
        return None
    W, H = im.size
    bw, bh = box[2] - box[0] + 1, box[3] - box[1] + 1
    print(f"{label}:")
    print(f"    画布 {W}x{H}, 内容 {bw}x{bh}")
    print(f"    宽度占比 {bw / W * 100:.1f}%   高度占比 {bh / H * 100:.1f}%")
    return bw / W, bh / H


def main() -> int:
    tmp = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "_cmp"
    tmp.mkdir(parents=True, exist_ok=True)
    txt = tmp / "sample.txt"
    txt.write_text("x", encoding="utf-8")
    etxt = tmp / "sample.etxt"
    etxt.write_bytes(b"x")

    for size, large in ((32, False), (48, True), (256, True)):
        print(f"=== {size}px ===")
        a = report(f"  .txt  (系统)", shell_icon(str(txt), large, size))
        b = report(f"  .etxt (我的)", shell_icon(str(etxt), large, size))
        if a and b:
            print(f"  >>> 宽度差 {(b[0] - a[0]) * 100:+.1f}pp, "
                  f"高度差 {(b[1] - a[1]) * 100:+.1f}pp")
        print()

    # 清理
    for f in tmp.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        tmp.rmdir()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
