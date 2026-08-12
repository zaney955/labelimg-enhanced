# LabelImg Enhanced

[简体中文](README.md) | [English](README.en.md)

LabelImg Enhanced 是基于 LabelImg `v1.8.6` 独立维护的目标框标注工具。项目保留原版 `LabelImg` 界面名称和 `labelImg` 启动命令，同时规范 Python 包结构并持续维护面向专业标注工作流的增强功能。

> 这是独立维护的衍生项目，并非 HumanSignal 官方项目。

## 主要增强

- 完整的简体中文和英文界面，可在“设置 → 语言”中即时切换并记住选择。
- 首次启动时，`zh-*` 系统区域使用简体中文，其他系统区域使用英文。
- 标签框使用标签自身颜色呈现选中和悬停反馈。
- 普通单击、Ctrl 切换多选、右键和拖动共用同一个确定性重叠目标解析器，不会轮换目标。
- 标签列表和文件列表提供类似 Windows 文件资源管理器的多选交互。
- 独立的 `未复核 / 待复核 / 已验证` 图像复核状态。
- 按标注、复核和持久化状态筛选/排序文件，并保留隐藏选择。
- 图像菜单支持当前图快速旋转/翻转、批量等比缩放、亮度/对比度/Gamma/自动对比度/灰度调整，并将图像与标注作为可恢复原子操作处理。
- 本地图像质量检查可分析损坏、低分辨率、宽高比异常、模糊、过暗和过曝，结果提供独立徽标、问题/严重度筛选和非模态明细面板，不会修改图像。
- 支持逐图撤销/重做、实时自动保存、外部冲突处理和可恢复文件操作。
- 候选标签仅从当前标注目录中已保存的 Pascal VOC、YOLO 或 CreateML 文档派生。

## 语言

“设置 → 语言”提供“简体中文”和“English”。切换后当前窗口立即更新，无需重启；选择会持久化到 LabelImg 设置中。

翻译覆盖所有应用自有界面文案，包括菜单、工具栏、面板、状态栏、提示、校验错误、确认框、恢复和冲突流程。用户标签、文件名与路径、Pascal VOC/YOLO/CreateML 格式名以及操作系统原始诊断保持原样。

## 环境

- Python 3.14
- PyQt5 5.15
- lxml 6
- Windows 为主要支持平台；Linux 通过无界面测试验证。

## 安装

从源码安装：

```powershell
python -m pip install .
labelImg
```

也可以使用模块入口：

```powershell
python -m labelimg
```

## 开发与验证

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "src"
python tools/run_tests.py
python -m pip wheel . --no-deps --no-build-isolation
python tools/run_tests.py --installed
```

源码采用功能优先的模块化单体：`annotations`、`canvas`、`files`、`image_tools` 分别拥有自身的领域、应用、基础设施和界面代码，`workbench` 只负责桌面壳与跨功能组合。根包仅保留版本和模块入口；AST 架构测试会阻止旧式平铺模块、Qt 反向渗透和跨边界依赖回归。完整设计与迁移映射见 [模块化架构设计](docs/design/modular-architecture-refactor.md)。

双语目录使用稳定消息 ID；测试会校验中英文键和格式参数完全一致，并阻止界面代码重新引入硬编码应用文案。设计说明见 [双语界面设计](docs/design/bilingual-interface.md)。

## 来源与许可证

本项目基于 [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) 的 `v1.8.6`（commit `1ab8241`），保留完整上游 Git 历史，并使用 MIT 许可证。详细来源见 [NOTICE.md](NOTICE.md)。
