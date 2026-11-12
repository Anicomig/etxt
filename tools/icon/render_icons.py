"""把候选图标渲染成一张对比图，便于挑选。

用 SHDefExtractIconW 按索引提取 DLL 里的图标（ExtractAssociatedIcon
只能拿第一个，拿不到指定索引）。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-demo" / "icons-preview.png"

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


def extract_icon(path: str, index: int, size: int = 64):
    """从 DLL/EXE 提取指定索引的图标，返回 PIL Image 或 None。"""
    hicon = wintypes.HICON()
    # 负索引表示按资源 ID 取
    n = shell32.SHDefExtractIconW(path, -index if index > 0 else 0,
                                  0, ctypes.byref(hicon), None, size)
    if n != 0 or not hicon.value:
        return None
    try:
        # 用 GetIconInfo + 位图转换太麻烦，改走 GDI 绘制到 DIB
        hdc_screen = user32.GetDC(None)
        hdc = gdi32.CreateCompatibleDC(hdc_screen)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                        ("bmiColors", wintypes.DWORD * 3)]

        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = size
        bi.bmiHeader.biHeight = -size   # 负值 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0

        buf = ctypes.create_string_buffer(size * size * 4)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                      ctypes.byref(bits), None, 0)
        if not hbmp:
            gdi32.DeleteDC(hdc)
            user32.ReleaseDC(None, hdc_screen)
            return None
        old = gdi32.SelectObject(hdc, hbmp)
        user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, 3)
        ctypes.memmove(buf, bits, size * size * 4)
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, hdc_screen)

        img = Image.frombuffer("RGBA", (size, size), buf,
                               "raw", "BGRA", 0, 1)
        return img.copy()
    finally:
        user32.DestroyIcon(hicon)


CANDIDATES = [
    ("00 当前 exe", str(Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "etxt.exe"), 0),
    ("01 锁 1043", r"C:\Windows\System32\imageres.dll", 1043),
    ("02 文档 70", r"C:\Windows\System32\shell32.dll", 70),
    ("03 盾牌 78", r"C:\Windows\System32\imageres.dll", 78),
    ("04 钥匙 83", r"C:\Windows\System32\imageres.dll", 83),
    ("05 保险箱 112", r"C:\Windows\System32\imageres.dll", 112),
    ("06 记事本", r"C:\Windows\System32\notepad.exe", 0),
    ("07 压缩 40", r"C:\Windows\System32\imageres.dll", 40),
    ("08 加密夹 1045", r"C:\Windows\System32\imageres.dll", 1045),
    ("09 锁 1041", r"C:\Windows\System32\imageres.dll", 1041),
    ("10 锁 48", r"C:\Windows\System32\imageres.dll", 48),
    ("11 文档 1", r"C:\Windows\System32\imageres.dll", 1),
]


def main() -> int:
    cols = 4
    cell = 130
    rows = (len(CANDIDATES) + cols - 1) // cols
    W, H = cols * cell, rows * (cell + 20) + 40
    canvas = Image.new("RGB", (W, H), "#1f1f1f")
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        font = ImageFont.load_default()

    d.text((10, 10), "etxt 图标候选（选编号告诉我就行）", fill="#ffffff", font=font)

    missing = []
    for i, (label, src, idx) in enumerate(CANDIDATES):
        r, c = divmod(i, cols)
        x = c * cell + 12
        y = r * (cell + 20) + 40
        img = extract_icon(src, idx, 64)
        if img is None:
            d.rectangle([x, y, x + 64, y + 64], outline="#ff6666")
            d.text((x + 4, y + 24), "N/A", fill="#ff6666", font=font)
            missing.append(label)
        else:
            canvas.paste(img, (x, y), img)
        d.text((x, y + 70), label, fill="#cccccc", font=font)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print("预览图:", OUT)
    if missing:
        print("提取失败:", missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
