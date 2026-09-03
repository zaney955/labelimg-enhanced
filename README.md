# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced 是基于 LabelImg `v1.8.6` 独立维护的目标框标注工具，保留熟悉的 `LabelImg` 界面名称和 `labelImg` 启动命令，并增强专业标注、复核和图像处理工作流。

> 本项目并非 HumanSignal 官方项目。

## 主要功能

- 支持 Pascal VOC、YOLO 和 CreateML，并可在界面中明确选择保存格式。
- 完整的简体中文/英文界面，可即时切换并记住选择。
- 画布与标注列表支持多选、确定性的重叠目标选择，以及双击单个标注框或标签文字修改类别。
- 提示疑似重复框和重叠类别冲突，可定位、编辑、隐藏、删除或在当前会话忽略相关标注。
- 可按文件名或相对路径实时搜索当前图像目录，并提供 `未复核 / 待复核 / 已验证` 状态及标注、复核和保存状态筛选或排序。
- 支持逐图撤销/重做、实时自动保存、外部冲突处理和可恢复文件操作。
- 支持旋转、翻转、裁剪、原始像素倍率缩放和图像调整；画布下方独立状态区左侧显示图像内像素坐标及真实标注框宽高，右侧提供名义 `1%–600%`、可按当前图像精确适应倍率安全扩展的缩放滑块，空间不足时自动换行。`Ctrl+=`/`Ctrl+-` 以 10% 的互逆倍率调节，`Ctrl+1` 恢复原始大小，Ctrl+滚轮围绕光标平滑缩放，Shift+滚轮水平移动，质量检查可发现损坏、模糊、过暗、过曝等问题。

## 环境与安装

- Python 3.14
- Windows 为主要支持平台；Linux 通过无界面测试验证。

在仓库根目录安装并启动：

```powershell
python -m pip install .
labelImg
```

也可以使用 `python -m labelimg`。启动后可从界面打开图像目录、选择标注目录和保存格式。

## 更新

程序默认在启动后异步检查最新稳定版，且最多每 24 小时检查一次；可在“设置 → 自动检查更新”中关闭，也可从“帮助 → 检查更新…”立即检查。发现新版时，Python 环境可复制升级命令；由官方 Inno 安装器安装的 Windows 版本可主动下载并校验更新安装包；便携版只打开发布页。程序不会自行运行 `pip`、静默安装或绕过未保存内容检查。

维护者通过与 `src/labelimg/__init__.py` 版本一致的 annotated tag（例如 `v2.1.0`）触发发布工作流。CI 在 Windows 上验证版本、运行测试、构建 wheel、PyInstaller onedir 和按用户安装的 Inno Setup EXE，再生成 SHA-256 清单和来源证明，并创建待人工发布的 Draft GitHub Release。当前安装包未进行 Windows 代码签名，运行前会明确提示“未知发布者”；SHA-256 只验证相对发布清单的完整性，不能证明发布者身份。

## 开发与验证

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "src"
python tools/run_tests.py
python -m pip wheel . --no-deps --no-build-isolation
python tools/run_tests.py --installed
```

源码采用功能优先的模块化单体结构，术语、设计与决策说明见 [文档导航](docs/README.md)。

## 来源与许可证

本项目派生自 [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) `v1.8.6`（commit `1ab8241`），采用 MIT 许可证。详见 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。
