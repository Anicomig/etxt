"""主流程编排：打开 / 新建 / 改密码。

流程
----
打开已有文件：
    读字节 → 校验 ETXT2（兼容 ETXT1）
        → 取会话口令（有则复用）→ 解密
        → 失败或无缓存：弹统一认证框（可「忘记密码」走恢复码重置）
        → 进入编辑器（内容只在内存）→ Ctrl+S 重新加密原子写回

新建文件：
    弹统一认证框的 setup 视图（输两遍密码 + 展示恢复码）
        → 空编辑器 → Ctrl+S 创建

改密码：
    弹统一认证框的 change 视图 → crypto.rewrap 只重写信封头
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import crypto, store, ui


# ---------------------------------------------------------------- 内部
def _try_unlock(blob: bytes, password: str) -> tuple[bytes | None, bytes | None, str | None]:
    """返回 (明文, dek, 错误)。兼容旧版 ETXT1（无 dek）。"""
    try:
        if crypto.is_legacy(blob):
            return crypto.decrypt_legacy(blob, password), None, None
        unlocked = crypto.unlock(blob, password)
        return unlocked.plaintext, unlocked.dek, None
    except crypto.WrongPassword:
        return None, None, "密码错误，或文件已损坏"
    except crypto.NotEtxtFile as exc:
        return None, None, str(exc)


def _decode(data: bytes) -> tuple[str, str]:
    """把字节解码成文本，返回 (文本, 编码说明)。"""
    try:
        return data.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gbk"), "GBK（已转换）"
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace"), "UTF-8（含无法解码字符）"


def _error(title: str, message: str) -> None:
    ui.show_error(title, message)


# ---------------------------------------------------------------- 打开
def looks_like_text(data: bytes) -> bool:
    """判断一段字节是否是可读文本（用于「改名文件」引导）。

    实测：纯文本/CRLF/空文件 → True；二进制/PNG头/密文 → False。
    """
    if not data:
        return True
    if b"\x00" in data[:4096]:
        return False
    try:
        data[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            data[:8192].decode("gbk")
            return True
        except UnicodeDecodeError:
            return False


def open_etxt(path: Path) -> int:
    """打开一个加密文件进行编辑。返回进程退出码。"""
    path = Path(path)

    try:
        blob = store.read_etxt(path)
    except store.StoreError as exc:
        _error("无法打开", str(exc))
        return 1

    # ---- 不是加密格式：区分「改名文件」和「真二进制」
    if not (crypto.is_etxt(blob) or crypto.is_legacy(blob)):
        if looks_like_text(blob):
            return _handle_renamed_plain(path, blob)
        _error(
            "不是加密文件",
            f"这个文件既不是加密格式，也不是文本：\n{path.name}\n\n"
            "可能选错了文件。",
        )
        return 1

    password: str | None = None
    dek: bytes | None = None
    plaintext: bytes | None = None

    # ---- 1) 先用会话缓存的口令试
    cached = store.SESSION.get()
    if cached is not None:
        plaintext, dek, _err = _try_unlock(blob, cached)
        if plaintext is not None:
            password = cached
            store.SESSION.touch()
        else:
            store.SESSION.clear()

    # ---- 2) 需要用户介入：统一认证框
    if plaintext is None:
        state: dict = {"blob": blob, "dek": None}

        def verify_pw(pw: str) -> str | None:
            pt, dk, err = _try_unlock(state["blob"], pw)
            if err:
                return err
            state["plaintext"] = pt
            state["dek"] = dk
            state["password"] = pw
            return None

        def verify_code(code: str) -> str | None:
            if crypto.is_legacy(state["blob"]):
                return "旧版文件没有恢复码，只能使用密码"
            try:
                unlocked = crypto.unlock_with_recovery(state["blob"], code)
            except crypto.WrongPassword:
                return "恢复码错误"
            except crypto.NoRecovery:
                return "这个文件没有设置恢复码"
            except crypto.EtxtError as exc:
                return str(exc)
            state["dek"] = unlocked.dek
            state["plaintext"] = unlocked.plaintext
            return None

        def apply_reset(old: str, new: str, code: str | None) -> str | None:
            """用恢复码重置密码：只重写信封头。"""
            if crypto.is_legacy(state["blob"]):
                return "旧版文件无法重置密码，请用密码打开后另存为新文件"
            if not code:
                return "缺少恢复码"
            dk = state.get("dek")
            if dk is None:
                return "恢复码校验失败，请重试"
            try:
                new_blob = crypto.rewrap(
                    state["blob"], dk,
                    new_password=new,
                    new_recovery_code=code,
                )
                store.atomic_write(path, new_blob)
            except (store.StoreError, OSError) as exc:
                return str(exc)
            state["blob"] = new_blob
            state["password"] = new
            store.SESSION.put(new)
            return None

        from . import authdialog
        res = authdialog.ask_unlock(
            filename=path.name,
            verify=verify_pw,
            verify_recovery=verify_code,
            apply_reset=apply_reset,
        )
        if res is None:
            return 0  # 用户取消
        if "password" in res:
            password = res["password"]
            store.SESSION.put(password)
        elif "new_password" in res:
            password = res["new_password"]
            store.SESSION.put(password)

        plaintext = state.get("plaintext")
        dek = state.get("dek")
        if plaintext is None:
            _error("打开失败", "无法解密文件内容")
            return 1

    text, encoding_note = _decode(plaintext)

    def save(new_text: str) -> str | None:
        pw = store.SESSION.get()
        if pw is None:
            return "会话口令已过期，请重新打开文件。"
        try:
            old = path.read_bytes()
            # 优先走「保留信封」路径，让恢复码继续有效
            new_blob = _encrypt_body_with_same_dek(old, pw, new_text)
            if new_blob is None:
                new_blob = crypto.encrypt(new_text.encode("utf-8"), pw)
            store.atomic_write(path, new_blob)
        except (store.StoreError, OSError) as exc:
            return str(exc)
        return None

    win = ui.EditorWindow(
        title=f"{path.name} — 加密文本",
        subtitle=f"{path}    {encoding_note}",
        initial_text=text,
        on_save=save,
        file_path=path,
    )
    win.mainloop()
    return 0


# ---------------------------------------------------------------- 新建
def create_etxt(path: Path | None = None, *,
                from_shell_new: bool = False) -> int:
    """新建加密文件。

    `path` 为 None 时先弹「保存位置选择」对话框
    （默认 Documents，可自定义）。

    `from_shell_new`
        右键「新建 → 加密文本文档」时由 ShellNew 调用。
        这种情况下 Shell 会**先创建一个 0 字节空文件**再把路径传进来，
        所以「文件已存在」不能当成错误 —— 只要确认它是空文件就覆盖。

        不能把 0 字节文件留给用户：`.etxt` 是加密格式，
        0 字节不是合法密文，双击会报「文件损坏」。
    """
    if path is None:
        from . import savedlg
        path = savedlg.ask_save_location()
        if path is None:
            return 0

    path = Path(path)

    if path.exists():
        if from_shell_new and path.stat().st_size == 0:
            # ShellNew 预建的空文件，直接接管
            pass
        else:
            _error("文件已存在", f"目标已存在，不会覆盖：\n{path}")
            return 1

    creds = _ask_credentials_for_encrypt(path.name)
    if creds is None:
        return 0
    pw, code = creds.password, creds.recovery_code
    store.SESSION.put(pw)

    # 立刻写一个空文件，确保用户关掉编辑器也有文件存在
    try:
        store.atomic_write(path, crypto.encrypt(b"", pw, recovery_code=code))
    except (store.StoreError, OSError) as exc:
        _error("创建失败", str(exc))
        return 1

    return _open_editor(path, "", "UTF-8")


def _open_editor(path: Path, text: str, encoding_note: str) -> int:
    """打开编辑器。

    保存时必须**保留恢复码通道**：如果直接 `crypto.encrypt(...)` 重建，
    恢复块会变成全 0，用户之前抄下的恢复码就失效了。

    正确做法：用 `rewrap` 只换正文密文。但 rewrap 只重写信封、不动正文，
    所以需要：
      1. 用会话口令解开旧文件拿到 dek
      2. 用 dek 加密新正文
      3. 把新正文替换进旧信封（信封头原样保留）
    这样恢复块和密码块都不变，恢复码继续有效。
    """
    def save(new_text: str) -> str | None:
        pw = store.SESSION.get()
        if pw is None:
            return "会话口令已过期，请重新打开文件。"
        try:
            old = path.read_bytes()
            new_body = _encrypt_body_with_same_dek(old, pw, new_text)
            if new_body is None:
                # 旧文件解不开（例如会话过期），退回完整重建
                store.atomic_write(
                    path, crypto.encrypt(new_text.encode("utf-8"), pw))
            else:
                store.atomic_write(path, new_body)
        except (store.StoreError, OSError) as exc:
            return str(exc)
        return None

    win = ui.EditorWindow(
        title=f"{path.name} — 加密文本",
        subtitle=f"{path}    {encoding_note}",
        initial_text=text,
        on_save=save,
        file_path=path,
    )
    win.mainloop()
    return 0


def _encrypt_body_with_same_dek(old_blob: bytes, password: str,
                                new_text: str) -> bytes | None:
    """用旧信封里的 DEK 加密新正文，保留原信封头（含恢复块）。

    返回 None 表示旧文件无法解开（旧版格式 / 密码不匹配）。
    """
    if crypto.is_legacy(old_blob):
        return None
    try:
        unlocked = crypto.unlock(old_blob, password)
    except crypto.EtxtError:
        return None

    import os
    import struct
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    hdr = crypto._parse(old_blob)
    body = new_text.encode("utf-8")
    nonce = os.urandom(crypto.NONCE_LEN)
    ct = AESGCM(unlocked.dek).encrypt(nonce, body, crypto._AAD_BODY)

    out = bytearray()
    out += crypto.MAGIC
    out += bytes([crypto.VERSION, hdr.flags])
    out += hdr.salt_pw
    out += hdr.salt_rc
    out += nonce                                  # 新的正文 nonce
    out += hdr.nonce_wrap_pw
    out += hdr.nonce_wrap_rc
    out += struct.pack("<I", len(ct) - crypto.TAG_LEN)
    out += hdr.wrapped_pw
    out += hdr.wrapped_rc
    out += ct
    return bytes(out)


# ---------------------------------------------------------------- 改密码
def change_password(path: Path) -> int:
    """打开改密码对话框。"""
    path = Path(path)
    try:
        blob = store.read_etxt(path)
    except store.StoreError as exc:
        _error("无法打开", str(exc))
        return 1

    if crypto.is_legacy(blob):
        _error("旧版文件", "旧版 ETXT1 文件不支持改密码。\n"
                          "请先用密码打开，另存为新文件。")
        return 1

    def apply(old: str, new: str, code: str | None) -> str | None:
        try:
            unlocked = crypto.unlock(blob, old)
        except crypto.WrongPassword:
            return "当前密码错误"
        except crypto.EtxtError as exc:
            return str(exc)
        # 保留原有的恢复码通道
        keep_code = None
        if crypto.has_recovery(blob):
            # 无法从文件反推恢复码，只能要求用户重新提供或保持不变。
            # 这里选择：保留原恢复封装块不动。
            pass
        try:
            new_blob = crypto.rewrap(blob, unlocked.dek,
                                     new_password=new,
                                     new_recovery_code=None)
            # 如果原文件有恢复通道，保留原恢复块（rewrap 会清掉，
            # 所以这里显式把原恢复块拼回去）
            if crypto.has_recovery(blob):
                new_blob = _keep_recovery_block(blob, new_blob)
            store.atomic_write(path, new_blob)
        except (store.StoreError, OSError) as exc:
            return str(exc)
        store.SESSION.put(new)
        return None

    from . import authdialog
    res = authdialog.ask_change(filename=path.name, apply_change=apply)
    if res is None:
        return 0
    ui.show_info("密码已修改", "新密码已生效，旧密码不再可用。\n\n"
                              "恢复码保持不变。")
    return 0


def _keep_recovery_block(old_blob: bytes, new_blob: bytes) -> bytes:
    """把旧文件的恢复封装块拼到新信封上。

    rewrap(new_recovery_code=None) 会写入全 0 的恢复块；
    这里用旧文件的 salt_rc / nonce_wrap_rc / wrapped_rc 覆盖回去，
    并把 flags 的恢复位设回 1。

    前提：DEK 没变（rewrap 保证），所以旧恢复块仍然能解开同一个 DEK。
    """
    out = bytearray(new_blob)
    out[crypto.OFF_FLAGS] = crypto.FLAG_HAS_RECOVERY
    out[crypto.OFF_SALT_RC:crypto.OFF_SALT_RC + crypto.SALT_LEN] = \
        old_blob[crypto.OFF_SALT_RC:crypto.OFF_SALT_RC + crypto.SALT_LEN]
    out[crypto.OFF_NONCE_WRAP_RC:
        crypto.OFF_NONCE_WRAP_RC + crypto.NONCE_LEN] = \
        old_blob[crypto.OFF_NONCE_WRAP_RC:
                 crypto.OFF_NONCE_WRAP_RC + crypto.NONCE_LEN]
    out[crypto.OFF_WRAPPED_RC:
        crypto.OFF_WRAPPED_RC + crypto.WRAP_LEN] = \
        old_blob[crypto.OFF_WRAPPED_RC:
                 crypto.OFF_WRAPPED_RC + crypto.WRAP_LEN]
    return bytes(out)


# ---------------------------------------------------------------- 加密普通文件
def _atomic_encrypt_to(target: Path, raw: bytes, password: str,
                       code: str) -> None:
    """加密并原子写回。失败时目标文件不变。"""
    store.atomic_write(target, crypto.encrypt(raw, password, recovery_code=code))


# ---------------------------------------------------------------- 凭据获取
@dataclass(frozen=True)
class EncryptCreds:
    """加密用的凭据，外加「恢复码是否需要展示」。

    `first_time=True` 表示这是**首次设置通用密码**——恢复码刚生成，
    必须让用户抄下来。之后的加密恢复码不变，不再重复展示。
    """

    password: str
    recovery_code: str
    first_time: bool = False


def _ask_credentials_for_encrypt(filename: str) -> EncryptCreds | None:
    """加密前获取密码与恢复码。

    三种情况：
    1. **首次加密**（还没设置通用密码）
       → 弹「设置密码」+ 生成恢复码 → 存为通用凭据
       → `first_time=True`（调用方要展示恢复码）
    2. **已有通用密码**
       → 弹「确认密码」（输入框，不是设置框）
       → 验证通过后用通用密码 + 通用恢复码加密
       → 用户可点「使用独立密码」改为单独设密码
       → `first_time=False`（恢复码早就抄过了）
    3. **用户选了独立密码**
       → 弹「设置独立密码」，恢复码仍用通用的那个

    返回 None 表示用户取消。
    """
    from . import authdialog, master

    # ---- 情况 1：首次加密，设置通用密码
    if not master.is_configured():
        res = authdialog.ask_setup(filename=filename)
        if res is None:
            return None
        pw = res["password"]
        code = res["recovery_code"]
        # 存为通用凭据，之后加密不再需要重新设置
        master.configure(pw, code)
        store.SESSION.put(pw)
        return EncryptCreds(pw, code, first_time=True)

    # ---- 情况 2/3：已有通用密码，先确认
    holder: dict = {}

    def verify(pw: str) -> str | None:
        m = master.verify(pw)
        if m is None:
            return "密码错误"
        holder["master"] = m
        return None

    def supply_code() -> str:
        """给「独立密码」流程提供通用恢复码。

        调用时机：用户在 setup 视图输完密码、点「下一步」时。
        此时用户必然已经在 confirm 视图里验证过通用密码
        （`_switch_to_setup` 强制要求），所以 holder 有值。
        """
        m = holder.get("master")
        if m is not None:
            return m.recovery_code
        # 兜底：会话缓存
        c = store.SESSION.get()
        mm = master.verify(c) if c else None
        return mm.recovery_code if mm else ""

    res = authdialog.ask_confirm_master(
        filename=filename,
        verify=verify,
        fixed_recovery_code=supply_code,
    )
    if res is None:
        return None

    # `res` 的两种形态：
    #   1. {"master_password": ...}                        → 用通用密码
    #   2. {"password", "recovery_code", "independent": True}
    #      → 用户点了「使用独立密码」并在同一对话框里完成 setup
    if res.get("independent") or "password" in res:
        code = res.get("recovery_code") or ""
        if not code:
            _error("无法加密",
                   "没有取得通用恢复码。\n\n"
                   "独立密码的文件仍使用同一个恢复码，"
                   "所以需要先用通用密码验证一次。")
            return None
        # 独立密码：恢复码是早就存在的那一个，不再重复展示
        return EncryptCreds(res["password"], code, first_time=False)

    # 通用密码分支
    m = holder.get("master")
    if m is None:
        m = master.verify(res.get("master_password", ""))
    if m is None:
        _error("加密失败", "无法取得通用凭据")
        return None
    return EncryptCreds(m.password, m.recovery_code, first_time=False)


def encrypt_plain_file(src: Path, *, delete_original: bool = False,
                       in_place: bool = False,
                       ask_delete: bool = True) -> int:
    """把普通文本文件加密成 .etxt（不自动打开）。

    参数
    ----
    in_place
        True  → 原地加密，写回**同一路径**（用于「改名后双击」）
        False → 生成同名 `.etxt`，原文件保留（用于右键菜单）
    delete_original
        仅 `in_place=False` 时有意义：加密后删除原明文文件
    ask_delete
        是否弹「加密完成」对话框让用户勾选删除原文件。
        `in_place=True` 时无残留明文，强制不显示复选。

    返回进程退出码。调用方若需要「加密后打开」，自行再调 open_etxt。
    """
    src = Path(src)
    if not src.is_file():
        _error("文件不存在", f"找不到：\n{src}")
        return 1

    try:
        raw = src.read_bytes()
    except OSError as exc:
        _error("读取失败", str(exc))
        return 1

    dst = src if in_place else src.with_suffix(".etxt")

    creds = _ask_credentials_for_encrypt(dst.name)
    if creds is None:
        return 0
    pw, code = creds.password, creds.recovery_code
    first_time = creds.first_time

    try:
        _atomic_encrypt_to(dst, raw, pw, code)
    except (store.StoreError, OSError) as exc:
        _error("加密失败", str(exc))
        return 1

    store.SESSION.put(pw)

    # 原地加密：文件已是目标，无残留明文，不显示删除复选
    if in_place:
        if ask_delete:
            ui.show_encrypt_result(target=dst, recovery_code=code, source=None,
                                   show_recovery=first_time)
        return 0

    # 生成新文件：原明文还在，弹提示让用户决定是否删除
    if delete_original:
        try:
            src.unlink()
        except OSError:
            pass
        if ask_delete:
            ui.show_encrypt_result(target=dst, recovery_code=code, source=None,
                                   show_recovery=first_time)
    else:
        if ask_delete:
            should_delete = ui.show_encrypt_result(
                target=dst, recovery_code=code, source=src,
                show_recovery=first_time)
            if should_delete:
                try:
                    src.unlink()
                except OSError:
                    pass
    return 0


def encrypt_plain_files(files: list[Path]) -> int:
    """批量加密（拖拽多个文件 / 多选右键）。

    按用户决策 D5：**共用一次密码设置**，一个密码管这一批。
    逐个加密，失败的单独报告，不整体回滚。
    """
    paths = [Path(f) for f in files]
    if not paths:
        return 1

    # 过滤掉不存在的
    valid: list[Path] = []
    skipped: list[str] = []
    for p in paths:
        if p.is_file():
            valid.append(p)
        else:
            skipped.append(f"{p}（不存在）")

    if not valid:
        _error("没有可加密的文件", "\n".join(skipped) or "未选择文件")
        return 1

    # 整批共用一套凭据（首次设置 or 确认通用密码）
    creds = _ask_credentials_for_encrypt(f"{len(valid)} 个文件")
    if creds is None:
        return 0
    pw, code = creds.password, creds.recovery_code
    first_time = creds.first_time

    done: list[Path] = []
    failed: list[str] = []

    for p in valid:
        try:
            raw = p.read_bytes()
            dst = p.with_suffix(".etxt")
            _atomic_encrypt_to(dst, raw, pw, code)
            done.append(dst)
        except (OSError, store.StoreError) as exc:
            failed.append(f"{p.name}：{exc}")

    # 汇总提示
    lines = [f"成功 {len(done)} 个，失败 {len(failed)} 个", ""]
    if done:
        lines.append("已加密：")
        lines += [f"  {d.name}" for d in done]
    if failed:
        lines.append("")
        lines.append("失败：")
        lines += [f"  {f}" for f in failed]
    if skipped:
        lines.append("")
        lines.append("已跳过：")
        lines += [f"  {s}" for s in skipped]

    lines += ["", f"恢复码：{crypto.format_recovery_code(code)}",
              "请立即抄下，这批文件共用这个恢复码。"]

    ui.show_info("批量加密完成", "\n".join(lines))
    return 0 if not failed else 1


# ---------------------------------------------------------------- 改名文件引导
def _handle_renamed_plain(path: Path, blob: bytes) -> int:
    """用户把 笔记.txt 改名成 笔记.etxt 后双击。

    弹「这个文件还没有加密」，让用户选择：
      - 加密后打开 → 设置密码 → 原地加密 → 打开编辑器
      - 取消 → 什么都不做
    """
    if not ui.ask_encrypt_renamed(path.name):
        return 0
    rc = encrypt_plain_file(path, in_place=True)
    if rc != 0:
        return rc
    # 原地加密成功后接着打开
    return open_etxt(path)


# ---------------------------------------------------------------- 另存为加密
def save_as_encrypted(source_path: Path | None, text: str) -> int:
    """把当前编辑内容另存为一个新的加密文件。

    用于编辑器「文件 → 另存为加密文件…」。
    """
    from . import savedlg

    initial_name = "新建加密文本.etxt"
    initial_dir = None
    if source_path is not None:
        sp = Path(source_path)
        initial_name = sp.stem + ".etxt"
        initial_dir = sp.parent

    target = savedlg.ask_save_location(
        title="另存为加密文件",
        initial_name=initial_name,
        initial_dir=initial_dir)
    if target is None:
        return 0

    creds = _ask_credentials_for_encrypt(target.name)
    if creds is None:
        return 0
    pw, code = creds.password, creds.recovery_code
    first_time = creds.first_time
    try:
        _atomic_encrypt_to(target, text.encode("utf-8"), pw, code)
    except (store.StoreError, OSError) as exc:
        _error("保存失败", str(exc))
        return 1

    store.SESSION.put(pw)
    ui.show_encrypt_result(target=target, recovery_code=code, source=None,
                           show_recovery=first_time)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        ui.show_error("用法", "请把 .etxt 文件拖到本程序上，或双击打开。")
        return 1
    return open_etxt(Path(argv[0]))


if __name__ == "__main__":
    raise SystemExit(main())


