"""切换 .etxt 文件图标：暗色主题 / 亮色主题。

用法:
    python switch_icon.py dark     用暗色主题版（灰 224）
    python switch_icon.py light    用亮色主题版（灰 208）
    python switch_icon.py status   查看当前用的哪个

背景
----
Windows 的文件关联图标**不支持按主题自动切换** —— 注册表
`DefaultIcon` 只能指向一个固定的 .ico 文件，系统不会根据
深/浅色主题选择不同的图标资源。

所以做法是：生成两套 ico，用户按自己当前的主题手动切换一次。
切换只改注册表一行，不影响任何加密文件与密钥。
"""
from __future__ import annotations

import ctypes
import os
import sys
import winreg
from pathlib import Path

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "etxt-app"
ASSETS = Path(__file__).resolve().parent.parent / "assets"

ICON_KEY = r"Software\Classes\Etxt.EncryptedText\DefaultIcon"

VARIANTS = {
    "dark": ("etxt-dark.ico", 224, "暗色主题（灰 224）"),
    "light": ("etxt-light.ico", 208, "亮色主题（灰 208）"),
}


def notify_shell() -> None:
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def clear_icon_cache() -> int:
    """删除图标缓存文件（需要重启 explorer 才彻底生效）。"""
    cache_dir = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Explorer"
    n = 0
    if cache_dir.is_dir():
        for f in cache_dir.glob("iconcache*"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def current() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ICON_KEY) as k:
            return winreg.QueryValue(k, "")
    except OSError:
        return None


def apply(variant: str) -> int:
    if variant not in VARIANTS:
        print(f"未知主题: {variant}（可选 dark / light）")
        return 1

    fname, gray, desc = VARIANTS[variant]
    src = ASSETS / fname
    if not src.is_file():
        print(f"图标文件不存在: {src}")
        print("请先运行 tools/gen_icon.py 生成")
        return 1

    APP_DIR.mkdir(parents=True, exist_ok=True)
    dst = APP_DIR / fname
    dst.write_bytes(src.read_bytes())

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ICON_KEY) as k:
        winreg.SetValue(k, "", winreg.REG_SZ, str(dst))

    notify_shell()
    cleared = clear_icon_cache()

    print(f"已切换到: {desc}")
    print(f"  图标文件: {dst}")
    print(f"  清缓存: {cleared} 个")
    print()
    print("如资源管理器未立即刷新，重启一下资源管理器：")
    print("  任务管理器 → 找到「Windows 资源管理器」→ 重新启动")
    return 0


def show_status() -> int:
    cur = current()
    print("当前 DefaultIcon:")
    print(" ", cur or "(未设置)")
    print()
    if cur:
        name = Path(cur).name
        for v, (fname, gray, desc) in VARIANTS.items():
            if fname == name:
                print(f"  对应: {desc}")
                break
        else:
            print("  对应: 自定义图标")
    print()
    print("可选:")
    for v, (fname, gray, desc) in VARIANTS.items():
        print(f"  {v:6} -> {desc}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return show_status()
    cmd = sys.argv[1].lower()
    if cmd == "status":
        return show_status()
    return apply(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
