"""真实界面测试：长文本触发后窗口是否真的变高。

用法：
    python demo_longtext.py save    保存对话框 + 长状态文字
    python demo_longtext.py auth    认证对话框 + 长错误文字
    python demo_longtext.py auto    自动播放：短 -> 长 -> 短，每步截图
"""

import sys
import tempfile
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etxt import authdialog, savedlg, ui

LONG = ("这是一段很长的错误提示，用来模拟真实场景里因为密码错误、文件损坏、"
        "权限不足等原因而出现的多行说明文字。它会把对话框底部的内容往下推，"
        "如果窗口不跟着长高，最下面的按钮就会被窗口边缘裁掉一部分，"
        "虽然还能点击但显示不完整，影响观感。再补一些字确保换行到三行以上。")


def demo_save() -> None:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "taken.etxt").write_bytes(b"x")
    root = tk.Tk()
    root.withdraw()
    dlg = savedlg.SaveLocationDialog(root, initial_dir=tmp,
                                     initial_name="taken.etxt")
    dlg.update()

    def step1():
        print("STEP1 short:", dlg.winfo_height())
        dlg._status_var.set(LONG)
        dlg.update()
        dlg.after(400, step2)

    def step2():
        print("STEP2 long :", dlg.winfo_height())
        dlg._grow_to_fit()
        dlg.update()
        dlg.after(400, step3)

    def step3():
        print("STEP3 grown:", dlg.winfo_height())
        print("reqheight  :", dlg.winfo_reqheight())
        btn_bottom = dlg._ok.winfo_y() + dlg._ok.winfo_height()
        print("btn_bottom :", btn_bottom, "win_h:", dlg.winfo_height())
        print("OK" if btn_bottom <= dlg.winfo_height() else "CLIPPED")

    dlg.after(300, step1)
    root.mainloop()


def demo_auth() -> None:
    root = tk.Tk()
    root.withdraw()
    dlg = authdialog.AuthDialog(root, "unlock", filename="示例.etxt",
                                on_verify_password=lambda pw: "错误")
    dlg.update()

    def step1():
        print("STEP1 short:", dlg.winfo_height())
        dlg._error_var.set(LONG)
        dlg.update()
        dlg.after(400, step2)

    def step2():
        print("STEP2 long :", dlg.winfo_height())
        dlg.update()
        dlg.after(400, step3)

    def step3():
        print("STEP3 grown:", dlg.winfo_height())
        print("reqheight  :", dlg.winfo_reqheight())
        print("OK" if dlg.winfo_reqheight() <= dlg.winfo_height() else "CLIPPED")

    dlg.after(300, step1)
    root.mainloop()


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "save"
    if which == "save":
        demo_save()
    elif which == "auth":
        demo_auth()
    else:
        demo_save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

