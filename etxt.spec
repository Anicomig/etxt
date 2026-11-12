# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（目录模式 onedir）。

为什么用 onedir 而不是 onefile
------------------------------
onefile 会在启动时把自身解压到 `%TEMP%\\_MEIxxxxxx`。本机实测：
在低完整性标签的目录下运行 onefile 版，会报
`Could not create temporary directory!` —— 因为沙箱限制了下层进程
创建目录的权限。

onedir 模式把依赖摊在 exe 旁边，启动时不解压任何东西，
因此在受限环境里也能跑，且**冷启动更快**。

代价：产物是一个文件夹而不是单个文件。分发时打包成 zip 即可。

要点
----
- `console=False`：GUI 程序，双击不弹控制台
- 显式 hiddenimports：cryptography / PIL 有大量动态导入
- 排除测试与科学计算模块，减小体积
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules("cryptography.hazmat.backends")
hiddenimports += collect_submodules("cryptography.hazmat.primitives")
hiddenimports += [
    "etxt",
    "etxt.__main__",
    "etxt.app",
    "etxt.authdialog",
    "etxt.assoc",
    "etxt.crypto",
    "etxt.savedlg",
    "etxt.master",
    "etxt.selftest",
    "etxt.settings",
    "etxt.store",
    "etxt.ui",
    "PIL._tkinter_finder",
]

a = Analysis(
    ["run_etxt.pyw"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "numpy",
        "matplotlib",
        "scipy",
        "pandas",
        "IPython",
        "notebook",
        "PIL.ImageQt",
        "PIL.ImageShow",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="etxt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 关键：GUI 程序，不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="etxt",
)





