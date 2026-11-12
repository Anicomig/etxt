"""单独展示密码框效果。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etxt import ui

DEMO_PW = "demo-2026"


def main() -> int:
    attempts = {"n": 0}

    def submit(pw: str) -> str | None:
        attempts["n"] += 1
        if pw != DEMO_PW:
            return "密码错误，或文件已损坏"
        return None

    result = ui.ask_password_blocking(
        title="解锁加密文本",
        prompt="输入密码以解锁：\n示例.etxt",
        on_submit=submit,
    )
    print("result:", result, "attempts:", attempts["n"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

