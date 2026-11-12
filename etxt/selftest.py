"""诊断：验证打包版里的加密功能是否可用。

用法（打包版 exe）：
    etxt.exe --selftest <文件>

会弹一个对话框显示每一步的结果，便于定位打包后失效的模块。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def run_selftest(path: str | None = None) -> int:
    lines: list[str] = []

    def add(tag: str, value) -> None:
        lines.append(f"{tag}: {value}")

    try:
        import platform
        add("python", sys.version.split()[0])
        add("frozen", getattr(sys, "frozen", False))
        add("exe", sys.executable)

        # ---- 关键依赖
        try:
            import cryptography
            add("cryptography", cryptography.__version__)
        except Exception as exc:
            add("cryptography", f"FAIL {exc!r}")

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = b"0" * 32
            nonce = b"0" * 12
            ct = AESGCM(key).encrypt(nonce, b"hello", b"aad")
            pt = AESGCM(key).decrypt(nonce, ct, b"aad")
            add("AESGCM", f"OK ({pt!r})")
        except Exception:
            add("AESGCM", "FAIL\n" + traceback.format_exc())

        try:
            import hashlib
            k = hashlib.scrypt(b"pw", salt=b"0" * 16, n=2 ** 15, r=8, p=1,
                               dklen=32, maxmem=128 * 2 ** 15 * 8 * 2)
            add("scrypt", f"OK ({len(k)} bytes)")
        except Exception:
            add("scrypt", "FAIL\n" + traceback.format_exc())

        try:
            import PIL
            from PIL import Image, ImageDraw, ImageTk
            add("PIL", PIL.__version__)
        except Exception:
            add("PIL", "FAIL\n" + traceback.format_exc())

        # ---- 本工具模块
        from . import crypto as etxt_crypto
        add("etxt.crypto", "OK")

        if path:
            p = Path(path)
            if not p.is_file():
                add("target", f"MISSING {p}")
            else:
                blob = p.read_bytes()
                add("target", f"{p.name} ({len(blob)} bytes)")
                add("is_etxt", etxt_crypto.is_etxt(blob))
                add("has_recovery", etxt_crypto.has_recovery(blob))
                try:
                    # 只验证能否解析头部，不猜密码
                    hdr = etxt_crypto._parse(blob)
                    add("header", f"v{hdr.version} flags={hdr.flags} "
                                  f"body_len={hdr.body_len}")
                except Exception:
                    add("header", "FAIL\n" + traceback.format_exc())

    except Exception:
        add("FATAL", traceback.format_exc())

    text = "\n".join(lines)

    # 同时写日志，便于打包环境里排查
    try:
        import os
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "etxt")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "selftest.log"), "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        pass

    _show("自检结果", text)
    return 0


def _show(title: str, message: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        from . import ui
        ui._apply_win11_chrome(root)
    except Exception:
        pass
    messagebox.showinfo(title, message, parent=root)
    root.destroy()
