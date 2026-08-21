# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced 是基于 LabelImg `v1.8.6` 独立维护的目标框标注工具，保留熟悉的 `LabelImg` 界面名称和 `labelImg` 启动命令，并增强专业标注、复核和图像处理工作流。

> 本项目并非 HumanSignal 官方项目。

## 主要功能

- 支持 Pascal VOC、YOLO 和 CreateML，并可在界面中明确选择保存格式。
- 完整的简体中文/英文界面，可即时切换并记住选择。
- 画布与标注列表支持多选、确定性的重叠目标选择，以及双击单个标注框或标签文字修改类别。
- 提示疑似重复框和重叠类别冲突，可定位、编辑、隐藏、删除或在当前会话忽略相关标注。
- 提供 `未复核 / 待复核 / 已验证` 状态，并可按标注、复核和保存状态筛选或排序文件。
- 支持逐图撤销/重做、实时自动保存、外部冲突处理和可恢复文件操作。
- 支持旋转、翻转、裁剪、缩放和图像调整；质量检查可发现损坏、模糊、过暗、过曝等问题。

## 环境与安装

- Python 3.14
- Windows 为主要支持平台；Linux 通过无界面测试验证。

在仓库根目录安装并启动：

```powershell
python -m pip install .
labelImg
```

也可以使用 `python -m labelimg`。启动后可从界面打开图像目录、选择标注目录和保存格式。

## 开发与验证

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "src"
python tools/run_tests.py
python -m pip wheel . --no-deps --no-build-isolation
python tools/run_tests.py --installed
```

源码采用功能优先的模块化单体结构，设计说明见 [docs/design](docs/design)。

## 来源与许可证

本项目派生自 [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) `v1.8.6`（commit `1ab8241`），采用 MIT 许可证。详见 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。
