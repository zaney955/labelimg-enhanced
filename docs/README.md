# 文档导航

[项目介绍与运行方式](../README.md) · [English README](../README.en.md) · [开发与验证](development.md) · [术语表](../CONTEXT.md) · [版本变更](../CHANGELOG.md)

`CONTEXT.md` 定义领域术语，设计文档描述当前行为与约束，ADR 保留决策原因及历史语境。修改功能时更新所属专题，术语含义变化时同步词条。规则只在所属专题完整维护，其他位置保留链接与必要的数据安全提醒；实施步骤和验证流水账留在 Git 历史中。当前行为以源码、测试和专题设计相互核对，不能把早期 ADR 的迁移计划或一次部署结果当作现状。

## 当前设计

| 阅读目的 | 文档 |
| --- | --- |
| 新增或修改界面前必读：通用设计范式、布局、状态、组件接入与验收 | [UI 设计规范](design/ui-guidelines.md) |
| 全局外观、对话框分区、底部操作区与缩放渲染验证 | [全局界面外观](design/ui-presentation.md) |
| 全局界面缩放、独立画布缩放、快捷键迁移与 DPI 边界 | [全局界面缩放](design/ui-scaling.md) |
| 浅色/深色/系统跟随、强调色预设及扩展接口 | [外观与主题接口](design/themes.md) |
| 功能模块、状态归属、调用关系与架构检查范围 | [模块化架构](design/modular-architecture-refactor.md) |
| 标注事务、Undo/Redo、自动保存、格式选择、外部冲突、候选类别与文件恢复 | [标注历史与文件恢复](design/undo-redo-and-file-recovery.md) |
| 绘制预览、指针命中、框选、标签编辑、标注列表及近重复框提示 | [标注交互](design/annotation-interaction.md) |
| 工作区搜索、筛选、文件选择、状态显示及剪贴板传输 | [工作区与文件列表](design/workspace-file-list.md) |
| 大目录渐进打开、索引完成与后台任务取消 | [目录加载](design/large-directory-loading.md) |
| 图像处理、裁剪、质量分析、显示调整及处理恢复 | [图像工具](design/image-tools.md) |
| 左侧工具栏、顶部命令、状态区、坐标和缩放 | [Canvas 命令布局](design/canvas-tool-rail.md) |
| 顶层菜单归属 | [菜单信息架构](design/menu-information-architecture.md) |
| 无对应图像或空标注文件的扫描、清理与恢复 | [标注文件清理](design/annotation-cleanup.md) |
| 类别框数、图像数、占比及统计图表 | [标注统计](design/annotation-statistics.md) |
| 语言切换、界面文案与快捷键帮助 | [双语界面](design/bilingual-interface.md) |
| 类别显示颜色及会话生命周期 | [会话类别调色板](design/session-label-color-palette.md) |
| 操作图标的几何、颜色与验证 | [图标规范](icon-design-system.md) · [当前 SVG 资源](../resources/icons/) |
| 更新中心、不同安装方式、下载与安装流程 | [应用更新](design/application-updates.md) |

## 决策记录

ADR 按编号保留历史语境，后续记录可补充早期表述。以下导航包含全部决策；历史迁移记录不表示仍有迁移任务待执行。

### 仓库与分发基线

- [0001：独立仓库保留上游历史](adr/0001-independent-repository-with-upstream-history.md)
- [0002：以 upstream v1.8.6 为迁移基线](adr/0002-base-migration-on-upstream-v1.8.6.md)
- [0003：保留产品入口并规范包布局](adr/0003-preserve-user-interface-while-normalizing-package-layout.md)
- [0004：隔离验证后替换 DL 安装](adr/0004-validate-in-isolation-before-replacing-the-dl-installation.md)
- [0005：采用 pyproject、setuptools 与 src 布局](adr/0005-use-pyproject-setuptools-and-src-layout.md)
- [0006：Windows 优先并保留 Linux CI](adr/0006-support-windows-first-with-linux-ci.md)

0001–0004 描述最初迁移背景；当前安装与验证命令以根目录 README 为入口。

### 标注历史与文件事务

- [0007：标注感知的批量文件操作与恢复](adr/0007-make-file-list-batch-operations-annotation-aware-and-recoverable.md)
- [0008：有界文档快照式标注历史](adr/0008-use-bounded-document-snapshots-for-annotation-history.md)
- [0009：按物理资源协调保存](adr/0009-coordinate-annotation-saves-by-physical-resource.md)
- [0010：在每种活跃格式中保留复核状态](adr/0010-preserve-review-state-in-every-active-format.md)
- [0011：在明确时机结束编辑与文件事务](adr/0011-close-edit-and-filesystem-transactions-at-explicit-boundaries.md)
- [0012：复制 Windows 回收站 PIDL 身份](adr/0012-copy-windows-recycle-identities-as-pidls.md)

### 图像工具与命令布局

- [0013：可恢复的图像处理原子替换](adr/0013-commit-image-processing-as-recoverable-atomic-replacement.md)
- [0014：图像工具随核心运行时提供](adr/0014-ship-image-tools-with-the-core-runtime.md)
- [0015：几何变换与标注一同提交](adr/0015-commit-geometry-changing-image-tools-with-annotations.md)
- [0016：左侧栏专用于 Canvas 工具](adr/0016-keep-the-left-rail-dedicated-to-canvas-tools.md)

0007 的整条恢复约束适用于文件操作记录；0013 的显式子集恢复适用于图像处理记录，两者保留各自的原子范围。

### 模块架构

- [0017：内部路径直接迁移，不保留兼容转发](adr/0017-migrate-internal-module-paths-without-compatibility-shims.md)
- [0018：按功能组织模块化单体](adr/0018-organize-the-application-as-a-feature-first-modular-monolith.md)
- [0019：功能包归属与组合入口](adr/0019-assign-capabilities-to-feature-owned-packages.md)
- [0020：单一状态所有者与显式协调](adr/0020-use-single-state-owners-and-explicit-feature-coordination.md)
- [0021：领域模型与用例不依赖 Qt](adr/0021-keep-domain-models-and-use-cases-free-of-qt.md)
- [0022：通过架构测试执行依赖规则](adr/0022-enforce-feature-boundaries-with-architecture-tests.md)
- [0023：在 2.0 中移除 labelimg.app](adr/0023-remove-the-labelimg-app-module-in-version-2.md)

0019/0021 细化了 0018 的组合入口描述；当前组合方式、后来增加的 `updates` 功能包及自动检查的实际覆盖范围见模块化架构文档。0017/0023 的路径迁移已经完成。

### 目录加载与外部同步

- [0024：渐进打开大目录并使用会话索引](adr/0024-open-large-directories-progressively-with-session-only-indexes.md)
- [0025：仅同步当前标注文档](adr/0025-synchronize-only-the-current-annotation-document.md)

0025 替代旧设计中的 no-watcher 规则：当前文档可实时同步，非当前图像只刷新受影响的派生索引，不在后台重建其编辑历史；0024 的渐进加载与会话索引决策继续有效。

### 稳定版更新

- [0026：检查稳定版且不自行修改 Python 安装](adr/0026-check-stable-releases-without-self-modifying-python-installs.md)
- [0027：明确请求安装无签名 Windows 托管更新](adr/0027-install-unsigned-managed-windows-updates-explicitly.md)

0026 约束 Python 安装；0027 补充托管 Windows 安装的显式更新流程。
