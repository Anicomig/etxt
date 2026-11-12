"""生成演示用 .etxt 文件，并启动内置编辑器窗口供查看效果。

用法:
    python demo_editor.py             # 生成示例 + 打开编辑器
    python demo_editor.py --pw xxx    # 指定口令
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etxt import crypto, store, ui

DEMO_PASSWORD = "demo-2026"

SAMPLE = """通用自定义配置插件+通用设置口

{
模块化子插件，支持其他插件使用
模块化设置界面，支持其他插件使用
}

模块

superpower插件：

能不能写个dsh上的superpower插件，但是否自定义是否使用，可以吗？
设置约束：
三选一胶囊设置选项：【关闭|强制启用|自定义启用】
关闭：关闭superpower（但插件正常加载，新会话无superpower影响，已被superpower影响会话不再强制）
强制启用：与原版superpower一致，所有会话都被强制注入和影响。
自定义启用：在新会话对话框显示一个胶囊【superpower(胶囊按钮)】决定本会话是否强制。

原插件逻辑：
dsh-superpower插件与原superpower效果一致，有完整的功能和强制性。
仅在开始增加判断：
{
新会话
  设置【强制启用|自定义启用（启用）】→ 发挥效果；
  设置【关闭|自定义启用（关闭）】→ 不发挥效果；
旧会话/进行中的会话
  设置【强制启用|自定义启用（启用）】{
    曾经发挥效果→
    持续发挥效果→ 继续发挥效果
  }
  设置【关闭|自定义启用（关闭）】→ 停止强制，已注入提示词与skills不用去除，不发挥效果。
}

---

试着按 Ctrl+F 打开查找栏，
或者选中一段文字再按 Ctrl+F。
"""


def main() -> int:
    here = Path(__file__).resolve().parent
    target = here / "示例.etxt"

    pw = DEMO_PASSWORD
    if "--pw" in sys.argv:
        pw = sys.argv[sys.argv.index("--pw") + 1]

    if not target.exists():
        store.atomic_write(target, crypto.encrypt(SAMPLE.encode("utf-8"), pw))
        print(f"已生成：{target}")
        print(f"大小：{target.stat().st_size} 字节（明文 {len(SAMPLE.encode('utf-8'))} 字节）")
    else:
        # 用最新示例内容刷新，保证演示文本与代码一致
        store.atomic_write(target, crypto.encrypt(SAMPLE.encode("utf-8"), pw))
        print(f"已刷新：{target}  {target.stat().st_size} 字节")

    store.SESSION.put(pw)

    def save(new_text: str) -> str | None:
        p = store.SESSION.get()
        if p is None:
            return "会话口令已过期。"
        try:
            store.atomic_write(target, crypto.encrypt(new_text.encode("utf-8"), p))
        except Exception as exc:
            return str(exc)
        print(f"已加密保存：{target.stat().st_size} 字节")
        return None

    win = ui.EditorWindow(
        title=f"{target.name} — 加密文本",
        subtitle=f"{target}",
        initial_text=SAMPLE,
        on_save=save,
    )
    win.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

