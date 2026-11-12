"""按**真实索引**生成图标演示文件（索引已通过枚举图肉眼确认）。

每个候选注册独立扩展名 + ProgId + DefaultIcon，
资源管理器里能并排看到不同图标。
"""
from __future__ import annotations

import ctypes
import os
import sys
import winreg
from pathlib import Path

BASE = r"Software\Classes"
EXT_BASE = ".etxtico"
PROGID_BASE = "EtxtIconPick"

IMAGERES = r"C:\Windows\System32\imageres.dll"

# (编号, 说明, dll 路径, 索引)
# 索引来自 _imageres_part1/2.png 肉眼确认
PICKS = [
    ("00", "当前默认", None, None),
    ("01", "黄色挂锁", IMAGERES, 54),
    ("02", "金色钥匙", IMAGERES, 77),
    ("03", "蓝色盾牌", IMAGERES, 73),
    ("04", "绿色盾牌勾", IMAGERES, 101),
    ("05", "文档+锁", IMAGERES, 184),
    ("06", "硬盘+挂锁", IMAGERES, 210),
    ("07", "硬盘+挂锁(细)", IMAGERES, 211),
    ("08", "硬盘+挂锁(实)", IMAGERES, 216),
    ("09", "文件夹+锁", IMAGERES, 321),
    ("10", "文档+钥匙", IMAGERES, 300),
    ("11", "纯文档", IMAGERES, 0),
    ("12", "文件夹(黄)", IMAGERES, 2),
    ("13", "锁+勾", IMAGERES, 101),
    ("14", "云+锁", IMAGERES, 217),
    ("15", "蓝色文档", IMAGERES, 337),
]


def demo_dir() -> Path:
    d = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-pick"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _del_tree(path: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _del_tree(path + "\\" + sub)
    except OSError:
        pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def clean() -> None:
    for i in range(len(PICKS)):
        for p in (rf"{BASE}\{PROGID_BASE}{i}\DefaultIcon",
                  rf"{BASE}\{PROGID_BASE}{i}",
                  rf"{BASE}\{EXT_BASE}{i}"):
            _del_tree(p)
    d = demo_dir()
    if d.is_dir():
        for f in d.iterdir():
            try:
                if f.is_file() and f.suffix.startswith(EXT_BASE):
                    f.unlink()
            except OSError:
                pass
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def icon_ref(dll: str, idx: int) -> str:
    """构造 DefaultIcon 值。

    ExtractIconEx 的索引从 0 开始；注册表里正数表示资源 ID，
    负数表示「第 N 个图标」。所以用负索引最稳妥：
        "imageres.dll,-54" 表示第 54 个图标
    """
    return f'"{dll}",{-idx}' if idx > 0 else f'"{dll}",0'


def build() -> Path:
    clean()
    d = demo_dir()

    for i, (num, desc, dll, idx) in enumerate(PICKS):
        ext = f"{EXT_BASE}{i}"
        progid = f"{PROGID_BASE}{i}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{BASE}\{ext}") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, progid)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"{BASE}\{progid}") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, f"图标候选 {num} {desc}")

        if dll is None:
            ref = f'"{Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "etxt.exe"}",0'
        else:
            ref = icon_ref(dll, idx)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              rf"{BASE}\{progid}\DefaultIcon") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, ref)

        safe = desc.replace("/", "-").replace("\\", "-").replace(":", "-")
        (d / f"{num} {safe}{ext}").write_text("图标演示，可删除", encoding="utf-8")

    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    return d


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        clean()
        print("已清理")
        return 0

    d = build()
    print("目录:", d)
    print()
    for num, desc, dll, idx in PICKS:
        ref = "(exe)" if dll is None else f"{Path(dll).name},-{idx}"
        print(f"  {num}  {desc:14} {ref}")
    print()
    print("打开目录按编号对照。告诉我编号即可应用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

