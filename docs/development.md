# 开发与验证

以下 PowerShell 命令均在仓库根目录执行，使用 Python 3.14。运行环境与依赖以 [pyproject.toml](../pyproject.toml) 为准；源码入口为 [`workbench.bootstrap`](../src/labelimg/workbench/bootstrap.py)，不要直接修改已安装的 `site-packages`。

## 源码与定向测试

首次准备开发环境可运行 `python -m pip install .`。源码全量测试：

```powershell
python tools/run_tests.py
```

[运行器](../tools/run_tests.py)递归发现 `tests/**/test_*.py`，逐文件启动独立 Python 进程并输出具体测试方法，设置源码 `PYTHONPATH`，默认使用 `QT_QPA_PLATFORM=offscreen` 和 `.test-state/test-config`。每个文件默认最多运行 900 秒，超时会作为该文件的明确失败继续汇总；可用 `--timeout-seconds` 调整。可用 `LABELIMG_CONFIG_DIR` 指定其他测试配置目录；不要指向真实用户设置。最终汇总区分失败文件与全部通过。

CI 使用 `--shard-index` 与 `--shard-count` 将排序后的测试文件稳定、无重叠地分片；普通本地全量测试保持默认单分片。定向检查应通过 unittest discovery，并显式隔离环境，例如：

```powershell
$env:PYTHONPATH = "$PWD/src"
$env:QT_QPA_PLATFORM = "offscreen"
$env:LABELIMG_CONFIG_DIR = "$PWD/.test-state/focused-config"
python -B -m unittest discover -s tests/workbench -p test_bootstrap.py
```

定向 Qt 测试也应逐文件启动进程。以上环境变量仅用于当前终端；后续运行真实程序前清除或使用新终端。纯文档改动检查链接、命令/API 和规范一致性；代码、界面和打包改动按 [UI 验收规则](design/ui-guidelines.md#新增功能流程与验收)及所属专题选择必要验证。

彩色边框修复的真实图像验收通过 `LABELIMG_RED_FRAME_SAMPLES` 显式指定 JPG/JPEG 样本目录，逐张检查检测结果；不依赖某位开发者的下载目录或固定样本数量。未提供可访问目录时仅跳过该项验收，合成图像回归仍正常执行。

## 构建并隔离验证 wheel

每次使用新目录，避免旧 wheel 或旧安装内容混入：

```powershell
$checkRoot = Join-Path $PWD (".test-state/wheel-check-" + [guid]::NewGuid().ToString("N"))
python -m pip wheel . --no-deps --no-cache-dir --wheel-dir "$checkRoot/wheels"
$wheel = Get-ChildItem -LiteralPath "$checkRoot/wheels" -Filter "*.whl" | Select-Object -ExpandProperty FullName
python -m pip install --no-deps --no-cache-dir --target "$checkRoot/package" $wheel
python tools/run_tests.py --package-root "$checkRoot/package"
```

这些命令在当前 Python 已具备运行依赖的前提下，仅把项目 wheel 安装到隔离目录。检查每条命令成功后再继续；构建失败不能继续使用旧产物。无缓存选项避免依赖用户级缓存目录的写权限；离线构建且当前环境已有 `setuptools>=70` 时可另加 `--no-build-isolation`，否则保留默认构建隔离。`--package-root` 必须指向包含 `labelimg/__init__.py` 的目录。

wheel 内容测试默认查找 `dist/` 中与当前 `labelimg.__version__` 对应的 wheel，忽略旧版本。验证其他构建目录时，在运行测试前设置 `$env:LABELIMG_TEST_WHEEL = $wheel`；显式指定的文件不存在或版本不符时测试失败。源码树没有当前 wheel 时会跳过内容检查，CI 与发布流程在构建后另行运行该检查，覆盖入口、资源和全部 Python 模块清单。

`python tools/run_tests.py --installed` 则移除子进程的 `PYTHONPATH`，检查**当前解释器实际安装的包**；它不会安装刚构建的 wheel。只有明确将已验证 wheel 安装到目标环境并重启应用后，才能报告部署完成。构建、解包或隔离测试通过不代表用户环境已更新。

## 界面渲染与性能

渲染脚本直接导入源码，先设置 `PYTHONPATH`：

```powershell
$env:PYTHONPATH = "$PWD/src"
python -B tools/render_ui_gallery.py --output .test-state/ui-zh-dark --language zh_CN --scale 1.5 --mode dark --accent teal
python -B tools/render_label_selection.py --output .test-state/labels-en --language en --scale 1.25
python -B tools/render_status_bar.py --output .test-state/footer-en-dark-150 --language en --mode dark --scale 1.5
python -B tools/render_ui_scaling.py --output .test-state/zoom-en-dark --language en --mode dark --dpr 1.5 --levels 75 100 125 150 200
python -B tools/render_ui_scaling.py --output .test-state/zoom-native --native --language zh_CN --levels 100 150 200
```

图库支持 `--focus` 和 `--panels-only` 子集；覆盖范围以脚本和生成的 JSON 清单为准。中英文、主题、缩放及实际桌面的验证边界见[全局界面外观](design/ui-presentation.md#双语与验证)。脚本使用临时图像和标注；不要为验证修改用户数据。

底栏工具 `render_status_bar.py` 的 `--scale` 对应 Qt 系统 DPR（1、1.25、1.5），`--ui-scale` 对应应用界面比例（75、100、125、150、200）。分别组合 `--language en/zh_CN` 与 `--mode light/dark`；PNG 和 `manifest.json` 记录空态、窄窗口、悬停、加载/停止/失败、焦点与大坐标读数，并执行缩放滑块、预设菜单、放大镜和任务按钮交互。几何检查失败会返回非零退出码；它不会修改 Windows 的实际显示缩放设置。

在 Windows 添加 `--native` 可显示临时测试窗口，并实际打开、截图和关闭状态详情对话框及比例菜单；默认 offscreen 通过隔离的对话框调用检查完整消息。原生窗口检查与系统 DPR 模拟应分别记录。

大目录计时使用 `python tools/benchmark_directory_loading.py --count 10000`，与确定性正确性测试分开。目标与测量条件见[目录加载](design/large-directory-loading.md#performance-budget)。

## CI 与发布

[CI](../.github/workflows/ci.yml)仅响应分支推送、拉取请求和手动触发，在 Windows/Linux 的 Python 3.14 上将源码全量测试分成四片并行执行；同一 ref 的新运行会取消旧运行。全部分片通过后单独构建并检查 wheel。版本标签不会重复触发普通 CI。[发布工作流](../.github/workflows/release.yml)要求 tagged commit 位于 `main` 且已经有成功的 main push CI，再使用版本匹配的 annotated tag 构建 Windows 分发并创建草稿 Release，不重复执行源码全量测试；具体发布门槛与产物见[应用更新](design/application-updates.md#release-builds)。
