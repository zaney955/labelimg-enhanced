# LabelImg Enhanced

LabelImg Enhanced 是基于 LabelImg `v1.8.6` 独立维护的目标框标注工具。项目保留原版 `LabelImg` 界面名称和 `labelImg` 启动命令，同时规范 Python 包结构并持续维护定制标注流程。

> This is an independently maintained derivative and is not an official HumanSignal project.

## 主要增强

- 标签框选中后使用标签自身颜色的实线边框和半透明填充。
- 按住 Ctrl 可在画布中框选多个完整包含的标注框。
- Ctrl+单击可多选；在重叠区域连续 Ctrl+单击时，每次只巡回选中一个重叠框。
- 标签列表支持类似 Windows 文件资源管理器的普通单击、Ctrl 多选和 Shift 连续选择。
- 删除、复制和跨图粘贴只作用于当前选中的标注框。
- 候选标签使用自适应五列彩色胶囊布局。
- 包含文件状态、自然排序、实时保存和图像删除导航等工作流改进。

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

## 来源与许可证

本项目基于 [HumanSignal/labelImg](https://github.com/HumanSignal/labelImg) 的 `v1.8.6`（commit `1ab8241`），保留完整上游 Git 历史，并使用 MIT 许可证。详细来源见 [NOTICE.md](NOTICE.md)。
