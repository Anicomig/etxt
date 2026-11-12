"""`.etxt` 文件关联的安装 / 卸载。

只用 HKCU（当前用户），**不需要管理员权限**。

注册结构
--------
::

    HKCU\\Software\\Classes\\.etxt
        (Default) = "Etxt.EncryptedText"
    HKCU\\Software\\Classes\\Etxt.EncryptedText
        (Default) = "加密文本文件"
        FriendlyTypeName = "加密文本文件"
        DefaultIcon\\ (Default) = "<exe路径>,0"
        shell\\open\\command\\ (Default) = '"<exe路径>" "%1"'

为什么不用 UserChoice
---------------------
Win10/11 对 `.txt` 这类**已有默认程序**的扩展名，改 UserChoice 需要写
一个微软未公开算法的 Hash 值，程序化设置既脆弱又会被系统重置。
`.etxt` 是全新扩展名，没有既有 UserChoice，只要在 HKCU 的
Software\\Classes 下声明 ProgId 即可生效，稳定得多。

改完必须调 SHChangeNotify 通知外壳刷新，否则要重启资源管理器才认。
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

PROGID = "Etxt.EncryptedText"
EXT = ".etxt"
FRIENDLY_NAME = "加密文本文件"

# 右键菜单：挂在 SystemFileAssociations 下
#
# 为什么不用 txtfile\shell：
#   实测 .md 的 ProgId 是 JeffBox.Markdown，不是 txtfile，
#   挂在 txtfile\shell 下的菜单对 .md 完全不生效。
#   SystemFileAssociations 按扩展名生效，与该扩展名当前关联到哪个
#   程序无关，因此能同时覆盖 .txt 和 .md。
#
# 实测（Shell COM 枚举真实右键菜单）：两个扩展名都出现了菜单项。
CTX_EXTS = (".txt", ".md")
VERB_NAME = "EtxtEncrypt"
VERB_LABEL = "加密为 etxt"

# 旧版曾挂在 txtfile\shell 下，升级时要清理掉，避免出现两个同名菜单
_LEGACY_VERB_KEY = r"txtfile\shell\EtxtEncrypt"

_SHCNE_ASSOCCHANGED = 0x08000000
_SHCNF_IDLIST = 0x0000


class AssocError(Exception):
    """注册表操作失败。"""


def _winreg():
    import winreg  # 延迟导入，便于非 Windows 平台 import 本模块不炸
    return winreg


def _classes_root():
    return _winreg().HKEY_CURRENT_USER, r"Software\Classes"


def current_command() -> str:
    """读当前 `.etxt` 的打开命令（未关联时返回空串）。"""
    try:
        wr = _winreg()
        hkcu, base = _classes_root()
        with wr.OpenKey(hkcu, rf"{base}\{PROGID}\shell\open\command") as k:
            return wr.QueryValue(k, "")
    except OSError:
        return ""


def is_installed() -> bool:
    """是否已把 `.etxt` 关联到某个程序。"""
    try:
        wr = _winreg()
        hkcu, base = _classes_root()
        with wr.OpenKey(hkcu, rf"{base}\{EXT}") as k:
            progid = wr.QueryValue(k, "")
    except OSError:
        return False
    return bool(progid) and bool(current_command())


def points_to(exe: Path | str) -> bool:
    """当前关联是否指向给定的 exe。"""
    target = str(_abs_nofollow(exe))
    return _path_in(current_command(), target)


def _abs_nofollow(path: Path | str) -> Path:
    """绝对化路径，但**不做 resolve()**。

    为什么不能用 Path.resolve()：本机实测它会沿着盘符映射改写路径，
    把 `C:\\Users\\...\\pythonw.exe` 解析成不存在的
    `F:\\Program Files\\Python\\...`，导致写进注册表的打开命令指向
    一个打不开的路径。用 os.path.abspath 只做规范化，不解析链接。
    """
    import os
    return Path(os.path.abspath(str(path)))


def _current_exe() -> Path:
    """当前可执行体（打包后是 exe 自身，源码模式是 pythonw.exe）。"""
    import os

    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    d = os.path.dirname(os.path.abspath(sys.executable))
    for cand in ("pythonw.exe", "python.exe"):
        p = os.path.join(d, cand)
        if os.path.isfile(p):
            return Path(p)
    return Path(sys.executable)


def _path_in(text: str, target: str) -> bool:
    """判断命令行里是否引用了 target 路径（大小写不敏感）。"""
    return target.lower() in text.lower()


def _looks_like_frozen_exe(exe_path: Path) -> bool:
    """判断目标 exe 是否 PyInstaller 打包产物。

    不能只看 `sys.frozen`：用源码版给打包版装关联时，当前进程
    frozen=False，但目标 exe 已经是打包好的 GUI 程序，
    此时命令里**不能**再带 run_etxt.pyw 脚本参数。

    判定依据：文件名不是 python / pythonw 就当作打包产物。
    """
    stem = exe_path.stem.lower()
    return stem not in ("python", "pythonw", "python3")


def _build_command(exe_path: Path) -> str:
    """构造打开命令。

    打包成 exe 时：``"<exe>" "%1"``
    源码运行时： ``"<pythonw.exe>" "<run_etxt.pyw>" "%1"``
        —— 只给 pythonw.exe 传 %1 是不行的，解释器会把它当成脚本路径。
    """
    if getattr(sys, "frozen", False) or _looks_like_frozen_exe(exe_path):
        return f'"{exe_path}" "%1"'

    launcher = _abs_nofollow(
        Path(__file__).resolve().parent.parent / "run_etxt.pyw")
    if not launcher.is_file():
        # 退回到 -m 方式（无控制台靠 pythonw）
        return f'"{exe_path}" -m etxt "%1"'
    return f'"{exe_path}" "{launcher}" "%1"'


def _write_shell_new(hkcu, base: str, exe_path: Path) -> None:
    """在右键「新建」菜单里注册「加密文本文档」。

    关键：`ShellNew` 必须挂在**扩展名键**下（`.etxt\\ShellNew`），
    不是 ProgId 下。实测参照系统里能新建的扩展名：

        .zip\\ShellNew   FileName = ...\\zipnew.dat
        .rar\\ShellNew   FileName = ...\\rarnew.dat

    写在 ProgId 下（`Etxt.EncryptedText\\ShellNew`）**不会出现**在
    新建菜单里 —— 这是踩过的坑。

    实现方式选择
    ------------
    1. `NullFile`  建 0 字节文件 → 对加密格式是坏文件，双击报「损坏」
    2. `FileName`  复制模板文件 → 需要预置一个合法 .etxt 模板，
                   但模板必须用某个密码加密，通用密码变了就失效
    3. `Command`   先建空文件，再执行命令 → 程序接管并写入合法密文 ✓

    采用 Command：Shell 会先创建一个 0 字节的 `.etxt`，
    再把路径作为 %1 传给 `--shell-new`，由程序用当前通用密码加密后写回。
    """
    wr = _winreg()
    key = rf"{base}\{EXT}\ShellNew"
    try:
        with wr.CreateKey(hkcu, key) as k:
            # 新建项在菜单里的显示名（不设则用 ProgId 的 FriendlyTypeName）
            wr.SetValueEx(k, "MenuText", 0, wr.REG_SZ, "加密文本文档")
            # Shell 先建 0 字节文件，再把路径传给 --shell-new
            wr.SetValueEx(k, "Command", 0, wr.REG_SZ,
                          f'"{exe_path}" --shell-new "%1"')
            # 防御：清掉可能残留的 NullFile（会生成坏文件）
            try:
                wr.DeleteValue(k, "NullFile")
            except OSError:
                pass
    except OSError:
        pass

    # 清理旧版误写在 ProgId 下的 ShellNew
    _delete_tree(hkcu, base, rf"{PROGID}\ShellNew")


def _delete_shell_new(hkcu, base: str) -> None:
    """移除「新建」菜单项（两处都清，兼容旧版）。"""
    _delete_tree(hkcu, base, rf"{EXT}\ShellNew")
    _delete_tree(hkcu, base, rf"{PROGID}\ShellNew")


def _verb_key(ext: str) -> str:
    """某个扩展名的右键菜单注册路径。"""
    return rf"SystemFileAssociations\{ext}\shell\{VERB_NAME}"


def _write_context_menu(exe_path: Path, hkcu, base: str) -> None:
    """给 .txt / .md 注册「加密为 etxt」右键菜单。"""
    wr = _winreg()
    for ext in CTX_EXTS:
        key = _verb_key(ext)
        with wr.CreateKey(hkcu, rf"{base}\{key}") as k:
            wr.SetValue(k, "", wr.REG_SZ, VERB_LABEL)
            wr.SetValueEx(k, "Icon", 0, wr.REG_SZ, f'"{exe_path}",0')
            # 多选时也能用（批量加密）
            wr.SetValueEx(k, "MultiSelectModel", 0, wr.REG_SZ, "Player")
        with wr.CreateKey(hkcu, rf"{base}\{key}\command") as k:
            wr.SetValue(k, "", wr.REG_SZ, f'"{exe_path}" --encrypt "%1"')


def _delete_tree(hkcu, base: str, path: str) -> None:
    """递归删除注册表子树（忽略不存在的）。"""
    wr = _winreg()
    full = rf"{base}\{path}"
    try:
        with wr.OpenKey(hkcu, full) as k:
            while True:
                try:
                    sub = wr.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(hkcu, base, path + "\\" + sub)
    except OSError:
        pass
    try:
        wr.DeleteKey(hkcu, full)
    except OSError:
        pass


def check_health(exe: Path | str | None = None) -> list[str]:
    """检查关联是否完整，返回缺失项列表（空列表 = 健康）。

    `exe` 省略时**不校验路径指向**，只校验结构完整性。

    为什么不默认用当前进程的 exe：源码模式下当前进程是 pythonw.exe，
    而注册表里可能（正确地）指向打包好的 etxt.exe。用当前进程比对
    会误报「指向旧路径」。只有调用方明确知道目标 exe 时才校验路径。

    检查项：
      1. .etxt 扩展名指向我们的 ProgId
      2. 打开命令存在（传了 exe 时还要求指向它）
      3. .txt 右键菜单存在（传了 exe 时还要求指向它）
      4. .md  右键菜单存在（传了 exe 时还要求指向它）
      5. ProgId 的 DefaultIcon 存在
    """
    wr = _winreg()
    hkcu, base = _classes_root()

    target = _abs_nofollow(exe) if exe is not None else None
    missing: list[str] = []

    # 1. 扩展名映射
    try:
        with wr.OpenKey(hkcu, rf"{base}\{EXT}") as k:
            progid = wr.QueryValue(k, "")
        if progid != PROGID:
            missing.append(f"{EXT} 未指向 {PROGID}")
    except OSError:
        missing.append(f"{EXT} 未注册")

    # 2. 打开命令
    cmd = current_command()
    if not cmd:
        missing.append("打开命令缺失")
    elif target is not None and not _path_in(cmd, str(target)):
        missing.append("打开命令指向旧路径")

    # 3+4. 右键菜单
    for ext in CTX_EXTS:
        try:
            with wr.OpenKey(hkcu, rf"{base}\{_verb_key(ext)}\command") as k:
                vcmd = wr.QueryValue(k, "")
            if not vcmd:
                missing.append(f"{ext} 右键菜单命令为空")
            elif target is not None and not _path_in(vcmd, str(target)):
                missing.append(f"{ext} 右键菜单指向旧路径")
        except OSError:
            missing.append(f"{ext} 右键菜单缺失")

    # 5. 图标
    try:
        with wr.OpenKey(hkcu, rf"{base}\{PROGID}\DefaultIcon") as k:
            if not wr.QueryValue(k, ""):
                missing.append("图标未设置")
    except OSError:
        missing.append("图标未设置")

    # 6. 右键「新建」菜单（挂在扩展名键下）
    #    注意：Command 是**命名值**，不是默认值，
    #    必须用 QueryValueEx 读，用 QueryValue(k, "Command") 会读不到。
    try:
        with wr.OpenKey(hkcu, rf"{base}\{EXT}\ShellNew") as k:
            sn_cmd = wr.QueryValueEx(k, "Command")[0]
        if not sn_cmd:
            missing.append("新建菜单命令缺失")
        elif target is not None and not _path_in(sn_cmd, str(target)):
            missing.append("新建菜单指向旧路径")
    except OSError:
        missing.append("新建菜单缺失")

    return missing


def ensure_installed(exe: Path | str | None = None) -> bool:
    """不健康就静默重装。返回 True 表示现在是健康的。

    双击 exe 时调用：用户不该看到「已关联」这类提示，
    但关联被破坏（程序挪了位置、注册表被清理）时必须能自动修好。

    传入 `exe` 时会同时校验路径指向 —— 程序被挪到别处时能自动纠正。
    """
    if not check_health(exe):
        return True
    try:
        install(exe)
    except AssocError:
        return False
    return not check_health(exe)

def install(exe: Path | str | None = None,
            icon: Path | str | None = None) -> str:
    """把 `.etxt` 关联到指定 exe（默认当前进程）。

    返回人类可读的结果描述。已关联到同一 exe 时直接返回提示，不重复写。
    """
    wr = _winreg()
    hkcu, base = _classes_root()

    if exe is None:
        exe = sys.executable
        # 打包后 sys.executable 就是 exe 本身；
        # 源码运行时是 python.exe，需要换成同目录的 pythonw.exe 以免弹控制台。
        if not getattr(sys, "frozen", False):
            import os
            d = os.path.dirname(os.path.abspath(exe))
            for cand in ("pythonw.exe", "python.exe"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    exe = p
                    break
    exe_path = _abs_nofollow(exe)
    if not exe_path.is_file():
        raise AssocError(f"找不到可执行文件：{exe_path}")

    if points_to(exe_path):
        return f"已关联（无需重复安装）\n\n{exe_path}"

    try:
        # ---- 扩展名 -> ProgId
        with wr.CreateKey(hkcu, rf"{base}\{EXT}") as k:
            wr.SetValue(k, "", wr.REG_SZ, PROGID)
            wr.SetValueEx(k, "Content Type", 0, wr.REG_SZ, "text/plain")
            wr.SetValueEx(k, "PerceivedType", 0, wr.REG_SZ, "text")

        # ---- ProgId 描述
        with wr.CreateKey(hkcu, rf"{base}\{PROGID}") as k:
            wr.SetValue(k, "", wr.REG_SZ, FRIENDLY_NAME)
            wr.SetValueEx(k, "FriendlyTypeName", 0, wr.REG_SZ, FRIENDLY_NAME)

        # ---- 图标
        icon_ref = f'"{icon}",0' if icon else f'"{exe_path}",0'
        with wr.CreateKey(hkcu, rf"{base}\{PROGID}\DefaultIcon") as k:
            wr.SetValue(k, "", wr.REG_SZ, icon_ref)

        # ---- 打开命令
        command = _build_command(exe_path)
        with wr.CreateKey(hkcu,
                          rf"{base}\{PROGID}\shell\open\command") as k:
            wr.SetValue(k, "", wr.REG_SZ, command)

        # ---- 右键菜单里显示「打开」
        with wr.CreateKey(hkcu,
                          rf"{base}\{PROGID}\shell\open") as k:
            wr.SetValueEx(k, "FriendlyAppName", 0, wr.REG_SZ, "加密文本")

        # ---- .txt / .md 的右键「加密为 etxt」
        _write_context_menu(exe_path, hkcu, base)

        # ---- 右键「新建」菜单里的「加密文本文档」
        _write_shell_new(hkcu, base, exe_path)

        # ---- 清理旧版挂在 txtfile\shell 下的菜单，避免重复
        _delete_tree(hkcu, base, _LEGACY_VERB_KEY)

    except OSError as exc:
        raise AssocError(f"写注册表失败：{exc}") from None

    notify_shell()
    return f"已关联 .etxt 文件\n\n{exe_path}"


def uninstall() -> str:
    """移除 `.etxt` 关联与右键菜单。"""
    wr = _winreg()
    hkcu, base = _classes_root()

    try:
        # ShellNew 是 PROGID 的子键，会被 _delete_tree 一起删掉，
        # 但显式调用更清晰，也便于将来独立控制
        _delete_shell_new(hkcu, base)
        _delete_tree(hkcu, base, PROGID)
        # 两处右键菜单
        for ext in CTX_EXTS:
            _delete_tree(hkcu, base, _verb_key(ext))
        # 旧版遗留
        _delete_tree(hkcu, base, _LEGACY_VERB_KEY)
        # 扩展名映射
        try:
            with wr.OpenKey(hkcu, rf"{base}\{EXT}") as k:
                wr.DeleteValue(k, "")
        except OSError:
            pass
        _delete_tree(hkcu, base, EXT)
    except OSError as exc:
        raise AssocError(f"清理注册表失败：{exc}") from None

    notify_shell()
    return "已取消 .etxt 关联与右键菜单"


def notify_shell() -> None:
    """通知外壳「文件关联变了」，否则要重启资源管理器才生效。"""
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(
            _SHCNE_ASSOCCHANGED, _SHCNF_IDLIST, None, None)
    except Exception:
        pass
