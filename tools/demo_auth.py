"""图形界面演示：依次展示四种认证视图。

用法:
    python demo_auth.py unlock    # 解锁 + 忘记密码
    python demo_auth.py setup     # 首次设置 + 恢复码
    python demo_auth.py change    # 修改密码
    python demo_auth.py all       # 依次展示（每关一个弹下一个）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etxt import authdialog, crypto

DEMO_PW = "demo-2026"
DEMO_CODE = "aB3xK9mP2qW7nR5t"


def show_unlock() -> None:
    def verify(pw: str) -> str | None:
        return None if pw == DEMO_PW else "密码错误，或文件已损坏"

    def verify_code(code: str) -> str | None:
        return None if code == crypto.normalize_recovery_code(DEMO_CODE) else "恢复码错误"

    def reset(old: str, new: str, code: str | None) -> str | None:
        return None

    res = authdialog.ask_unlock(
        filename="示例.etxt", verify=verify,
        verify_recovery=verify_code, apply_reset=reset)
    print("unlock result:", res)


def show_setup() -> None:
    res = authdialog.ask_setup(filename="新建加密文本.etxt")
    print("setup result:", res)


def show_change() -> None:
    def apply(old: str, new: str, code: str | None) -> str | None:
        if old != DEMO_PW:
            return "当前密码错误"
        return None

    res = authdialog.ask_change(filename="示例.etxt", apply_change=apply)
    print("change result:", res)


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "unlock"
    if which == "unlock":
        show_unlock()
    elif which == "setup":
        show_setup()
    elif which == "change":
        show_change()
    elif which == "all":
        show_unlock()
        show_setup()
        show_change()
    else:
        print("unknown:", which)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

