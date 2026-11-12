"""可靠地枚举 imageres.dll 里的图标资源 ID。

不猜索引，而是用 EnumResourceNames 列出 RT_GROUP_ICON 的所有资源名，
再用 ExtractIconEx 按**资源 ID** 提取。

关键区别：
- SHDefExtractIcon 的负索引 = 资源 ID（但要传 -id）
- 我之前的代码传了 `-index if index > 0 else 0`，对 index=0 时传 0
  会取到第一个图标而不是「资源 ID 0」，导致大部分失败。
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

RT_GROUP_ICON = 14
LOAD_LIBRARY_AS_DATAFILE = 0x00000002

EnumResNameProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMODULE, wintypes.LPCWSTR,
    wintypes.LPWSTR, wintypes.LPARAM)


def list_icon_ids(dll: str) -> list[int]:
    """列出 DLL 里所有图标组的资源 ID（数字型）。"""
    h = kernel32.LoadLibraryExW(dll, None, LOAD_LIBRARY_AS_DATAFILE)
    if not h:
        return []
    ids: list[int] = []
    try:
        def cb(hmod, typ, name, param):
            # 只收数字型 ID（字符串型是命名资源，跳过）
            ptr = ctypes.cast(name, ctypes.c_void_p).value
            if ptr is not None and ptr < 0x10000:
                ids.append(int(ptr))
            return True

        kernel32.EnumResourceNamesW(h, RT_GROUP_ICON, EnumResNameProc(cb), 0)
    finally:
        kernel32.FreeLibrary(h)
    return sorted(ids)


def icon_to_image(hicon, size: int = 64):
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
    if not hbmp:
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, hdc_screen)
        return None

    old = gdi32.SelectObject(hdc, hbmp)
    user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, 3)
    buf = ctypes.create_string_buffer(size * size * 4)
    ctypes.memmove(buf, bits, size * size * 4)
    gdi32.SelectObject(hdc, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(None, hdc_screen)

    img = Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1)
    return img.copy()


def extract_by_id(dll: str, res_id: int, size: int = 64):
    """按资源 ID 提取图标。"""
    h = kernel32.LoadLibraryExW(dll, None, LOAD_LIBRARY_AS_DATAFILE)
    if not h:
        return None
    try:
        large = wintypes.HICON()
        small = wintypes.HICON()
        n = user32.PrivateExtractIconsW(
            dll, res_id, size, size, ctypes.byref(large),
            ctypes.byref(small), 1, 0)
        if n == 0 or not large.value:
            return None
        try:
            return icon_to_image(large, size)
        finally:
            user32.DestroyIcon(large)
    finally:
        kernel32.FreeLibrary(h)


def main() -> int:
    dll = r"C:\Windows\System32\imageres.dll"
    ids = list_icon_ids(dll)
    print(f"imageres.dll 图标资源数: {len(ids)}")
    print("前 30 个 ID:", ids[:30])

    # 渲染所有图标，多页
    out_dir = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick"
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered = []
    for rid in ids:
        img = extract_by_id(dll, rid, 64)
        if img is not None:
            rendered.append((rid, img))
    print("成功渲染:", len(rendered))

    cols = 12
    cell = 90
    rows = (len(rendered) + cols - 1) // cols
    W, H = cols * cell, rows * cell + 30
    canvas = Image.new("RGB", (W, H), "#202020")
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
    except Exception:
        font = ImageFont.load_default()
    d.text((8, 6), "imageres.dll 全部图标（标签 = 资源ID）", fill="white", font=font)

    for i, (rid, img) in enumerate(rendered):
        r, c = divmod(i, cols)
        x = c * cell + 12
        y = r * cell + 28
        canvas.paste(img, (x, y), img)
        d.text((x, y + 66), str(rid), fill="#4cc2ff", font=font)

    out = out_dir / "_imageres_all.png"
    canvas.save(out)
    print("总览图:", out, f"({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
