"""生成图标演示：把候选图标应用到测试文件上，供用户挑选。

做法：为每个候选图标建一个临时扩展名（.etxtdemo1 / .etxtdemo2 ...），
各自注册不同的 DefaultIcon，然后在同一个文件夹里放几个空文件。
这样资源管理器里能并排看到所有候选图标。

不碰真实的 .etxt 关联，也不碰任何加密文件。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import winreg
from pathlib import Path

BASE = r"Software\Classes"
DEMO_EXT = ".etxtdemo"

# 候选图标： (编号, 显示名, 图标来源)
CANDIDATES = [
    ("exe", "当前（exe 内嵌）",
     str(Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "etxt.exe") + ",0"),
    ("sys_lock", "系统·锁（imageres 1043）",
     r"C:\Windows\System32\imageres.dll,-1043"),
    ("sys_doc", "系统·文档（shell32 70）",
     r"C:\Windows\System32\shell32.dll,-70"),
    ("sys_shield", "系统·盾牌（imageres 78）",
     r"C:\Windows\System32\imageres.dll,-78"),
    ("sys_key", "系统·钥匙（imageres 83）",
     r"C:\Windows\System32\imageres.dll,-83"),
    ("sys_safe", "系统·保险箱（imageres 112）",
     r"C:\Windows\System32\imageres.dll,-112"),
    ("sys_note", "系统·记事本",
     r"C:\Windows\System32\notepad.exe,0"),
    ("sys_zip", "系统·压缩包（imageres 40）",
     r"C:\Windows\System32\imageres.dll,-40"),
    ("sys_folder_lock", "系统·加密文件夹（imageres 1045）",
     r"C:\Windows\System32\imageres.dll,-1045"),
]


def demo_dir() -> Path:
    d = Path(os.environ["LOCALAPPDATA"]) / "etxt-app" / "icon-demo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def register(idx: int, icon: str) -> str:
    """为第 idx 个候选注册一个演示扩展名。"""
    ext = f"{DEMO_EXT}{idx}"
    progid = f"EtxtIconDemo{idx}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{BASE}\{ext}") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, progid)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{BASE}\{progid}") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, f"图标演示 {idx}")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          rf"{BASE}\{progid}\DefaultIcon") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, icon)
    return ext


def unregister_all() -> None:
    for idx, _name, _icon in CANDIDATES:
        ext = f"{DEMO_EXT}{idx}"
        progid = f"EtxtIconDemo{idx}"
        for path in (rf"{BASE}\{progid}\DefaultIcon",
                     rf"{BASE}\{progid}",
                     rf"{BASE}\{ext}"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass


def build() -> Path:
    """生成演示文件。返回演示目录。"""
    unregister_all()
    d = demo_dir()
    # 清空旧文件
    for f in d.iterdir():
        try:
            if f.is_file():
                f.unlink()
        except OSError:
            pass

    for idx, (key, name, icon) in enumerate(CANDIDATES):
        ext = register(idx, icon)
        fname = f"{idx:02d} {name}{ext}"
        # 文件名不能含某些字符，替换掉
        fname = fname.replace("/", "-").replace("\\", "-")
        (d / fname).write_text("演示文件，可以删除", encoding="utf-8")

    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    return d


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        unregister_all()
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        d = demo_dir()
        if d.is_dir():
            for f in d.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
        print("已清理演示")
        return 0

    d = build()
    print("演示目录:", d)
    print()
    for idx, (key, name, icon) in enumerate(CANDIDATES):
        print(f"  {idx:02d}  {name}")
        print(f"      {icon}")
    print()
    print("请打开该目录查看图标效果。")
    print("选好后告诉我编号，我把 .etxt 改成那个图标。")
    print("清理: python demo_icons.py clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
