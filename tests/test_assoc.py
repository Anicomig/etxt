"""assoc 层测试：健康检查与右键菜单注册。

注意：这些测试会真实读写 HKCU 注册表。
用 fixture 在结束后恢复原有状态。
"""
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="需要 Windows 注册表")


@pytest.fixture
def clean_assoc():
    """每个测试前重新安装到**当前测试进程**，结束后恢复到真实部署的 exe。

    为什么结束后要特殊处理
    ----------------------
    测试跑在源码模式（pythonw.exe），`assoc.install()` 会把关联写成
    源码模式。如果测试结束后直接留在这个状态，用户真实使用的打包版
    关联就被破坏了（实测踩过：跑完 pytest 后双击 .etxt 变成了
    依赖 Python 环境）。

    所以 teardown 时优先恢复到 `etxt-app\\etxt.exe`（如果存在）。
    """
    import os
    from pathlib import Path

    from etxt import assoc

    deployed = Path(os.environ.get("LOCALAPPDATA", "")) / "etxt-app" / "etxt.exe"
    # 恢复时要带上自定义图标，否则 DefaultIcon 会退回 exe 内嵌图标
    deployed_icon = deployed.parent / "etxt-dark.ico"

    assoc.uninstall()
    assoc.install()
    yield
    # 结束后恢复到打包版，避免污染真实关联
    try:
        assoc.uninstall()
        if deployed.is_file():
            icon = deployed_icon if deployed_icon.is_file() else None
            assoc.install(deployed, icon)
        else:
            assoc.install()
    except Exception:
        pass


def test_ctx_exts_cover_txt_and_md():
    from etxt import assoc

    assert ".txt" in assoc.CTX_EXTS
    assert ".md" in assoc.CTX_EXTS


def test_verb_key_uses_system_file_associations():
    from etxt import assoc

    key = assoc._verb_key(".md")
    assert key.startswith("SystemFileAssociations")
    assert ".md" in key
    assert assoc.VERB_NAME in key


def test_install_then_healthy(clean_assoc):
    from etxt import assoc

    assoc.install()
    assert assoc.check_health() == []


def test_install_creates_both_context_menus(clean_assoc):
    """安装后 .txt 和 .md 的右键菜单都必须存在。"""
    import winreg

    from etxt import assoc

    assoc.install()
    for ext in assoc.CTX_EXTS:
        key = rf"Software\Classes\{assoc._verb_key(ext)}\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            cmd = winreg.QueryValue(k, "")
        assert cmd, f"{ext} 的右键命令为空"
        assert "--encrypt" in cmd


def test_health_detects_missing_md_menu(clean_assoc):
    import winreg

    from etxt import assoc

    assoc.install()
    assert assoc.check_health() == []

    assoc._delete_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes",
                       assoc._verb_key(".md"))
    missing = assoc.check_health()
    assert any(".md" in m for m in missing)


def test_health_without_exe_skips_path_check(clean_assoc):
    """不传 exe 时只校验结构，不校验路径指向。

    原因：源码模式下当前进程是 pythonw.exe，而注册表可能（正确地）
    指向打包好的 etxt.exe，用当前进程比对会误报「旧路径」。
    """
    from etxt import assoc

    assoc.install()
    assert assoc.check_health() == []


def test_health_detects_stale_exe_path(clean_assoc):
    """传入明确的 exe 时，路径不匹配应被检出。"""
    import winreg

    from etxt import assoc

    assoc.install()
    with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\Etxt.EncryptedText\shell\open\command") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, r'"C:\old\etxt.exe" "%1"')

    # 传一个肯定不匹配的路径
    missing = assoc.check_health(r"C:\some\other\etxt.exe")
    assert any("旧路径" in m for m in missing)


def test_ensure_installed_repairs(clean_assoc):
    import winreg

    from etxt import assoc

    assoc.install()
    # 破坏三处
    assoc._delete_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes",
                       assoc._verb_key(".md"))
    assoc._delete_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes",
                       r"Etxt.EncryptedText\DefaultIcon")
    with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\Etxt.EncryptedText\shell\open\command") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, r'"C:\old\etxt.exe" "%1"')

    assert assoc.check_health(), "破坏后应检测到问题"
    assert assoc.ensure_installed() is True
    assert assoc.check_health() == [], "修复后应健康"

def test_uninstall_removes_everything(clean_assoc):
    import winreg

    from etxt import assoc

    assoc.install()
    assoc.uninstall()

    for ext in assoc.CTX_EXTS:
        key = rf"Software\Classes\{assoc._verb_key(ext)}"
        with pytest.raises(OSError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, key)

    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       r"Software\Classes\Etxt.EncryptedText")


def test_uninstall_cleans_legacy_key(clean_assoc):
    """旧版挂在 txtfile\\shell 下的菜单要被清掉。"""
    import winreg

    from etxt import assoc

    # 手工造一个旧键
    legacy = r"Software\Classes\txtfile\shell\EtxtEncrypt\command"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, legacy) as k:
        winreg.SetValue(k, "", winreg.REG_SZ, "old")

    assoc.uninstall()
    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       r"Software\Classes\txtfile\shell\EtxtEncrypt")


def test_points_to_ignores_path_resolve():
    """points_to 不应因 Path.resolve 的盘符映射而误判。"""
    from etxt import assoc

    cmd = assoc.current_command()
    if not cmd:
        pytest.skip("尚未安装关联")
    # 从命令里抽出 exe 路径
    import re
    m = re.search(r'"([^"]+\.exe)"', cmd, re.I)
    if not m:
        pytest.skip("命令格式不含 exe")
    assert assoc.points_to(m.group(1))


# ---------------------------------------------------------------- 右键「新建」菜单
def test_shell_new_registered_under_extension(clean_assoc):
    """回归：ShellNew 必须挂在**扩展名键**下，不是 ProgId 下。

    踩过的坑：写在 Etxt.EncryptedText\\ShellNew 时，
    右键「新建」子菜单里根本不出现这一项。
    正确的挂载点是 .etxt\\ShellNew（参照系统里 .zip / .rar 的做法）。
    """
    import winreg

    # 正确位置存在
    with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\.etxt\ShellNew") as k:
        cmd = winreg.QueryValueEx(k, "Command")[0]
        menu = winreg.QueryValueEx(k, "MenuText")[0]
    assert "--shell-new" in cmd
    assert menu == "加密文本文档"

    # ProgId 下不应存在
    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       r"Software\Classes\Etxt.EncryptedText\ShellNew")


def test_shell_new_has_no_nullfile(clean_assoc):
    """不能有 NullFile —— 那会生成 0 字节的坏文件。"""
    import winreg

    with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\.etxt\ShellNew") as k:
        with pytest.raises(OSError):
            winreg.QueryValueEx(k, "NullFile")


def test_health_detects_missing_shell_new(clean_assoc):
    """健康检查要能发现新建菜单缺失。"""
    import winreg

    from etxt import assoc

    winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                     r"Software\Classes\.etxt\ShellNew")
    missing = assoc.check_health()
    assert "新建菜单缺失" in missing


def test_uninstall_removes_shell_new(clean_assoc):
    """卸载要清掉新建菜单。"""
    import winreg

    from etxt import assoc

    assoc.uninstall()
    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                       r"Software\Classes\.etxt\ShellNew")
