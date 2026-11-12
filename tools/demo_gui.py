"""真实 GUI 演示脚本：用于人工/自动化点击测试。

用法：
    python demo_gui.py save      保存位置弹窗
    python demo_gui.py renamed   改名引导
    python demo_gui.py result    加密完成提示（含删除复选）
    python demo_gui.py auth      认证对话框（解锁）
    python demo_gui.py setup     设置密码 + 恢复码
    python demo_gui.py editor    编辑器
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etxt import authdialog, crypto, savedlg, ui


def show_save() -> None:
    p = savedlg.ask_save_location()
    print("save result:", p)


def show_renamed() -> None:
    ok = ui.ask_encrypt_renamed("笔记.etxt")
    print("renamed result:", ok)


def show_result() -> None:
    tmp = Path(tempfile.mkdtemp())
    target = tmp / "笔记.etxt"
    target.write_bytes(b"x")
    src = tmp / "笔记.txt"
    src.write_text("plain", encoding="utf-8")
    code = crypto.generate_recovery_code()
    delete = ui.show_encrypt_result(target=target, recovery_code=code,
                                    source=src)
    print("delete source:", delete)


def show_auth() -> None:
    res = authdialog.ask_unlock(
        filename="示例.etxt",
        verify=lambda pw: None if pw == "demo-2026" else "密码错误",
        verify_recovery=lambda c: None,
        apply_reset=lambda o, n, c: None,
    )
    print("auth result:", res)


def show_setup() -> None:
    res = authdialog.ask_setup(filename="新建.etxt")
    print("setup result:", res)


def show_editor() -> None:
    def save(t: str) -> str | None:
        return None

    win = ui.EditorWindow(
        title="示例.etxt — 加密文本",
        subtitle="示例.etxt    UTF-8",
        initial_text="# 标题\n\n这是一段示例内容。\n\n可以按 Ctrl+F 查找。\n",
        on_save=save,
    )
    win.mainloop()


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "save"
    {
        "save": show_save,
        "renamed": show_renamed,
        "result": show_result,
        "auth": show_auth,
        "setup": show_setup,
        "editor": show_editor,
    }.get(which, show_save)()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

