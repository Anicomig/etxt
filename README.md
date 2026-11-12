# etxt

> 一个 Windows 下的加密文本工具：把 `.txt` / `.md` 变成双击要密码的 `.etxt` 文件。

[![Tests](https://img.shields.io/badge/tests-153%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.14-blue)]()
[![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)]()
[![Crypto](https://img.shields.io/badge/AES--256--GCM%20%2B%20scrypt-ok-success)]()

---

## 目录

- [为什么做这个](#为什么做这个)
- [特性](#特性)
- [快速开始](#快速开始)
- [三种新建方式](#三种新建方式)
- [密码与恢复码](#密码与恢复码)
- [加密格式](#加密格式)
- [命令行](#命令行)
- [文件位置](#文件位置)
- [技术栈](#技术栈)
- [构建](#构建)
- [安全模型](#安全模型)
- [已知限制](#已知限制)
- [测试](#测试)
- [项目结构](#项目结构)
- [开发](#开发)
- [版本](#版本)
- [许可](#许可)
- [致谢](#致谢)

---

## 为什么做这个

想把敏感笔记存成普通文本文件，但不想让它们以明文躺在硬盘上。市面上的方案都有问题：

| 方案 | 问题 |
|---|---|
| 系统记事本 + 手动加密 | 编辑时要解密成临时明文，记事本会把明文写进 `TabState\*.bin` |
| Typora / 富文本编辑器 | 同样泄漏：`draftsRecover\` 里有明文快照 |
| 7-Zip 加密压缩包 | 每次都要解压 → 编辑 → 重新压缩，无法直接编辑 |
| BitLocker / EFS | 保护整个磁盘，不解决「单个文件拷走后被看」的问题 |

`etxt` 的做法：**双击 → 输密码 → 在自带的暗色编辑器里改 → 关闭时自动加密回写**。全程没有明文落盘。

---

## 特性

### 加密

- **AES-256-GCM** 认证加密，防篡改
- **信封加密**：随机主密钥（DEK）加密正文，DEK 分别用密码和恢复码各封装一份
- **改密码不重加密正文**，只重写 176 字节的信封头
- **scrypt** 密钥派生（`n=2¹⁵, r=8, p=1`，约 82 ms/次）
- 原子写回：先写临时文件再 `os.replace`，断电不会留下半截文件

### 密码体系

- **通用密码**：一个密码管所有文件，之后加密只需确认一次
- **独立密码**：某个文件可以用单独的密码，不影响其他文件
- **恢复码**：16 位随机字母数字（形如 `aB3x-K9mP-2qW7-nR5t`），忘记密码时的唯一退路
- 通用凭据本地保管，**不存明文密码**

### 编辑器

- Win11 风格暗色主题，PIL 4 倍超采样抗锯齿圆角
- 查找 / 替换（`Ctrl+F` / `Ctrl+H`）
- 缩放（`Ctrl+=` / `Ctrl+-` / `Ctrl+0`）、自动换行（`Ctrl+Shift+W`）
- 撤销 / 重做、剪切 / 复制 / 粘贴 / 全选
- 窗口尺寸、缩放、换行状态自动记忆
- 支持 `.md` 作为纯文本编辑（不渲染）

### 系统集成

- `.etxt` 文件关联，双击直接打开
- `.txt` / `.md` 右键菜单「加密为 etxt」
- 右键 **新建 → 加密文本文档**
- 自定义图标（暗色 / 亮色两套，可切换）
- 全部注册表操作限于 `HKCU`，**不需要管理员权限**

---

## 快速开始

### 安装

```bat
:: 关联文件类型 + 右键菜单
etxt.exe --install

:: 检查关联健康状态
etxt.exe --status
```

### 新建一个加密文件

双击 `etxt.exe`，或右键空白处 → **新建 → 加密文本文档**。

流程：

1. 选择保存位置（默认「文档」，可自定义）
2. 设置密码（至少 6 位，会显示强度）
3. **抄下恢复码**（只显示这一次）
4. 勾选「我已妥善保存」→ 完成

### 加密已有文件

右键任意 `.txt` / `.md` → **加密为 etxt**。

首次会设置通用密码；之后每次只需输入密码确认，用同一个密码和恢复码加密。

---

## 三种新建方式

| 方式 | 触发 | 密码来源 |
|---|---|---|
| 双击 exe | 双击程序 | 首次设置 / 确认通用密码 |
| 右键新建 | 新建 → 加密文本文档 | 确认通用密码 |
| 另存为加密 | 编辑器内「文件 → 另存为加密文件」 | 确认通用密码 |

三种方式都支持在确认密码时点「**使用独立密码**」，给当前文件设单独的密码。

---

## 密码与恢复码

### 通用密码：一个密码管所有文件

第一次加密时设置密码和恢复码，它们就成为**通用密码**和**通用恢复码**：

| 场景 | 弹窗 | 恢复码展示 |
|---|---|---|
| 第一次加密 | 「设置密码」 | ✅ 显示 + 强制确认 |
| 之后每次加密 | 「确认密码」 | ❌ 不显示 |
| 使用独立密码 | 「设置独立密码」 | ❌ 不显示 |

**为什么加密时弹「输入密码」而不是「设置密码」**：这样每次都能确认自己输对了，不会因为手滑把文件加密成打不开的样子。

### 独立密码

勾选「使用独立密码」时：

- 该文件用独立密码，**通用密码打不开它**
- 但**通用恢复码仍然能打开**（恢复码始终只有一个）

因为恢复码由通用密码加密保管，所以用独立密码前必须先输入一次通用密码。

### 忘记密码怎么办

双击文件 → 点「**忘记密码?**」→ 输入 16 位恢复码 → 设置新密码。

> **恢复码输入规则**：大小写敏感；连字符、空格、下划线等**所有非字母数字字符都会被忽略**，所以直接粘贴 `aB3x-K9mP-2qW7-nR5t` 或 `aB3xK9mP2qW7nR5t` 都可以。

**没有恢复码就找不回。** 这是可恢复方案的固有代价，不是实现缺陷。

---

## 加密格式

### 文件结构（ETXT2）

```
偏移    长度    内容
─────────────────────────────────────────────
0       6       magic "ETXT2\0"
6       1       version = 2
7       1       flags (bit0 = 含恢复码)
8       16      salt_pw      密码派生盐
24      16      salt_rc      恢复码派生盐
40      12      nonce_body   正文 GCM nonce
52      12      nonce_wrap_pw  密码封装 nonce
64      12      nonce_wrap_rc  恢复码封装 nonce
76      4       body_len     正文密文长度
80      48      wrapped_pw   被密码密钥封装的 DEK
128     48      wrapped_rc   被恢复码密钥封装的 DEK
176     N       body         正文密文
─────────────────────────────────────────────
HEADER_LEN = 176
```

### 信封加密

```
随机主密钥 DEK (32 字节)
    ├── 用「密码派生密钥」封装一份 → 存进文件 (wrapped_pw)
    ├── 用「恢复码派生密钥」封装一份 → 存进文件 (wrapped_rc)
    └── 用来加密正文 (AES-256-GCM)
```

好处：

- **改密码不重加密正文**，只重写那 32 字节的封装块
- **编辑保存保留恢复通道**：只替换正文密文，信封头原样不动
- 密码和恢复码是**两条独立通道**，任一个都能解开

### 通用凭据存储

`%APPDATA%\etxt\master.json`：

```json
{
  "version": 1,
  "salt_pw": "<hex>",
  "nonce_verifier": "<hex>",
  "verifier": "<hex>",           // 用密码密钥加密的固定串，用于验证密码
  "nonce_recovery": "<hex>",
  "recovery": "<hex>"            // 用密码密钥加密的恢复码
}
```

**没有明文密码，也没有明文恢复码。** 拿到这个文件仍需暴力破解。

---

## 命令行

```bat
etxt.exe                       :: 新建（同双击）
etxt.exe <file.etxt>           :: 打开
etxt.exe --install             :: 安装关联与右键菜单
etxt.exe --uninstall           :: 移除全部注册表项
etxt.exe --status              :: 检查关联健康
etxt.exe --selftest            :: 环境自检
etxt.exe --new [<path>]        :: 新建（可指定路径）
etxt.exe --shell-new <path>    :: 供「右键新建」调用
etxt.exe --encrypt <file…>     :: 加密普通文本（支持多文件）
etxt.exe --change <file.etxt>  :: 修改密码
```

---

## 文件位置

程序与配置分开放置，**都在 AppData 下**：

### 程序目录

```
C:\Users\Anicomig\AppData\Local\etxt-app\
├── etxt.exe           主程序（约 3.8 MB）
├── etxt-dark.ico      暗色主题图标（灰 224）
├── etxt-light.ico     亮色主题图标（灰 208）
└── _internal\         PyInstaller 运行时（onedir）
```

### 配置目录

```
C:\Users\Anicomig\AppData\Roaming\etxt\
├── master.json        通用密码与恢复码（加密存储）
└── settings.json      窗口尺寸 / 缩放 / 换行状态
```

> **为什么分开**：`Local` 是「可重建的机器本地数据」（程序本体），`Roaming` 是「用户数据」（配置）。重装程序不会丢配置，清理配置不影响程序。

### 切换图标主题

Windows 的文件图标**不支持按主题自动切换**（注册表只能指向一个 ico），需要手动切换：

```bat
python tools\switch_icon.py dark      :: 暗色主题（默认）
python tools\switch_icon.py light     :: 亮色主题
python tools\switch_icon.py status    :: 查看当前
```

切换只改注册表一行，不影响任何加密文件与密钥。

---

## 技术栈

| 层 | 选择 | 说明 |
|---|---|---|
| 语言 | Python 3.14 | 单文件工具，无需运行时环境（打包后） |
| 加密 | `cryptography` 48.0 | AES-256-GCM + scrypt |
| GUI | `tkinter` + `Pillow` 12.2 | 标准库 + 图像处理（抗锯齿圆角） |
| 打包 | PyInstaller | **onedir** 模式（onefile 在受限目录下会失败） |
| 注册表 | `winreg` | 仅 `HKCU`，无需管理员 |
| 测试 | `pytest` | 153 个测试 |

### 为什么用 tkinter 而不是 Qt

- 打包体积小得多（onedir 52 MB vs Qt 的 150 MB+）
- 无需额外授权（Qt 商业版收费）
- 单文件工具不需要复杂 UI 框架

代价是 tkinter 的圆角/抗锯齿支持差，所以用 PIL 4 倍超采样生成圆角图片，再用 `create_image` 贴到 Canvas 上。

### 为什么用 onedir 而不是 onefile

PyInstaller 的 onefile 模式会在运行时解压到 `%TEMP%`。在受限完整性级别的目录（如 DSH 工作区）下会失败：

```
Could not create temporary directory!
```

onedir 直接读取同级 `_internal\`，没有解压步骤，启动也更快。

---

## 构建

### 从源码运行

```bat
python run_etxt.pyw
```

### 打包

```bat
python -m PyInstaller --noconfirm --clean etxt.spec ^
    --distpath dist --workpath build
```

产物在 `dist\etxt\`，把整个目录拷到 `%LOCALAPPDATA%\etxt-app\` 即可。

### 重新生成图标

```bat
python tools\gen_icon.py
```

图标几何参数全部来自对参考图的**像素级实测**，见 `tools/gen_icon.py` 顶部注释。

---

## 安全模型

### 防护目标

| 威胁 | 是否防护 |
|---|---|
| 文件被拷走后直接查看 | ✅ |
| 云同步 / 网盘备份泄露 | ✅ |
| 硬盘丢失 / 送修 | ✅ |
| 他人借用电脑随手翻看 | ✅ |
| 暴力破解密码 | ⚠️ 取决于密码强度 |
| 同机恶意进程读内存 | ❌ 不防护 |
| 键盘记录器 | ❌ 不防护 |
| 已解锁状态下的屏幕截图 | ❌ 不防护 |

### 密码强度

最低 6 位，按长度分级：

| 长度 | 强度 |
|---|---|
| < 6 | 太短（不可用） |
| 6–9 | 一般 |
| 10–13 | 较强 |
| ≥ 14 | 很强 |

> 6 位是下限，不是推荐值。密码只用于派生密钥，**忘记后只能靠恢复码**，建议 12 位以上。

恢复码是 16 位随机字符（约 95 bit 熵），强度远高于任何人工密码，**务必备份**。

### 会话缓存

解锁后密码在内存中保留 **15 分钟**（每次成功解锁会续期），避免连续编辑多个文件时反复输入。威胁模型不含「同机进程读内存」，所以不做额外的内存加密（做了也只是象征性）。

---

## 已知限制

- **仅 Windows**：依赖 `winreg`、DWM、`SHFileOperationW`
- **单文件 < 1 MB**：正文一次性读入内存，大文件会卡顿
- **`.md` 不渲染**：作为纯文本编辑
- **恢复码不能跨文件独立**：所有文件共用一个通用恢复码（这是「一个恢复码」便利性的代价）
- **图标不随主题自动切换**：需手动运行切换脚本
- **无文件历史版本**：每次保存覆盖原文件（但有原子写保护）

---

## 测试

```bat
python -m pytest . -q
```

```
153 passed
```

测试覆盖：

| 文件 | 内容 |
|---|---|
| `test_crypto.py` | 加密格式、往返、篡改检测、旧版兼容 |
| `test_master.py` | 通用凭据、独立密码、恢复码回归 |
| `test_authflow.py` | 认证流程、加密调用链 |
| `test_assoc.py` | 注册表关联、右键菜单、新建菜单 |
| `test_savedlg.py` | 保存对话框、文件名冲突 |
| `test_dialog_layout.py` | 长文本自适应、恢复码展示策略 |
| `test_store.py` / `test_settings.py` | 原子写、配置持久化 |
| `test_roundtrip.py` | 端到端往返 |
| `test_focus.py` | 窗口焦点行为 |

---

## 项目结构

```
etxt/
├── etxt/                  核心源码
│   ├── crypto.py          加密格式（信封 + 恢复码）
│   ├── master.py          通用密码与恢复码保管
│   ├── store.py           原子写回 + 会话口令缓存
│   ├── settings.py        窗口状态持久化
│   ├── authdialog.py      统一认证对话框
│   ├── savedlg.py         保存位置选择
│   ├── ui.py              编辑器 + 控件（暗色主题）
│   ├── app.py             主流程
│   ├── assoc.py           文件关联 + 右键菜单 + 新建菜单
│   ├── selftest.py        环境自检
│   └── __main__.py        命令行入口
├── tests/                 153 个测试
├── tools/                 生成与演示脚本
│   ├── gen_icon.py        图标生成器
│   ├── switch_icon.py     图标主题切换
│   ├── demo_*.py          各界面演示
│   └── icon/              图标辅助脚本
├── assets/                图标成品
├── docs/                  调研与设计文档
├── etxt.spec              PyInstaller 配置
└── README.md
```

---

## 许可

个人项目，未指定开源许可。

## 致谢

- 加密实现基于 [`cryptography`](https://cryptography.io/)
- 圆角渲染基于 [`Pillow`](https://python-pillow.org/)
- 图标几何参照公开的单色 SIM 卡锁图标设计

---

## 开发

### 环境

```bat
pip install cryptography pillow pytest pyinstaller
```

### 常用命令

```bat
:: 跑测试
python -m pytest . -q

:: 生成图标
python tools\gen_icon.py

:: 切换图标主题
python tools\switch_icon.py dark

:: 界面演示（不碰真实配置）
python tools\demo_gui.py
```

### 源码目录

```
etxt/                     项目根
├── etxt/                 包（与项目同名，Python 惯例）
│   ├── crypto.py         加密格式，纯逻辑
│   ├── master.py         通用凭据
│   ├── store.py          原子写 + 会话缓存
│   ├── settings.py       窗口状态
│   ├── authdialog.py     认证对话框
│   ├── savedlg.py        保存位置选择
│   ├── ui.py             编辑器与控件
│   ├── app.py            主流程
│   ├── assoc.py          注册表集成
│   └── __main__.py       命令行入口
├── tests/                pytest 测试
├── tools/                生成脚本与演示
├── assets/               图标成品
├── docs/                 调研与设计文档
├── run_etxt.pyw          源码启动器
└── etxt.spec             PyInstaller 配置
```

### 代码约定

- **纯逻辑与 UI 分离**：`crypto.py` / `store.py` / `settings.py` / `master.py` 不导入 tkinter，可脱离 GUI 单测
- **原子写**：所有落盘走 `store.atomic_write`（临时文件 + `os.replace`）
- **注册表只碰 HKCU**：不申请管理员权限
- **失败要显式**：宁可弹错误框，也不要静默产出坏文件

### 踩过的坑

写在这里避免重复犯错：

| 坑 | 现象 | 原因 |
|---|---|---|
| 系统记事本泄漏明文 | `TabState\*.bin` 里能翻到内容 | 记事本会持久化未保存的编辑状态 |
| `.md` 右键菜单不生效 | 菜单里没有这一项 | `.md` 的 ProgId 是 `JeffBox.Markdown` 不是 `txtfile`，要用 `SystemFileAssociations` |
| ShellNew 不出现 | 新建菜单里没有 | `ShellNew` 必须挂**扩展名键**下（`.etxt\ShellNew`），不是 ProgId 下 |
| 图标深色主题不可见 | 图标像消失 | 近黑色线条在 RGB(25,25,25) 背景上对比度为 1 |
| 两个 StringVar 不同步 | 改名后按钮永久变灰 | 校验读的是另一个变量 |
| 长文本裁掉按钮 | 底部按钮显示不全 | 固定 `geometry` 不随内容长高 |
| `Path.resolve()` 改写路径 | 关联指向不存在的路径 | Windows 盘符映射，改用 `os.path.abspath` |
| onefile 打包在受限目录失败 | `Could not create temporary directory!` | 需解压到 TEMP，改用 onedir |
| 图标偏小 | 比系统 .txt 图标小一圈 | 宽高约束算错，宽度被压到 68%；应同时约束宽高取小者 |

---

## 版本

| 版本 | 变更 |
|---|---|
| 1.0 | 初版：信封加密、恢复码、暗色编辑器、文件关联 |
| 1.1 | 通用密码 / 独立密码；加密时改为确认密码；恢复码只在首次展示 |
| 1.2 | 自定义图标（深浅两套）；右键「新建」菜单；对话框自适应高度 |
