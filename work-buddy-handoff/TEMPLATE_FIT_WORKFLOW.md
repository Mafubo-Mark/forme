# WorkBuddy + 确定性保护套适配流程

## 当前交付

1. `automation/template_library.py register` 把来件整理到 `templates/`，校验 ZIP 路径和大小，生成带哈希的 `catalog.json`。
2. 独立后台 `/operator/` 的“保护套模板库”通过受 Bearer 令牌保护的 `/api/internal/templates` 显示七款；前端用户界面不出现后台模板操作。
3. `automation/fit_template.py` 接受结构化 `fit_spec.json`，仅作平滑、沿高度变化、每个控制量不超过 3 mm 的 XY 形变，重算 STL 法线，输出两片概念网格和 `fit_report.json`。原网格保留不动，输出由相同输入可重现。
4. 适配器强制检查模板哈希、毫米单位、Z 向上、+Y 为后侧、坐标注册证据和概念用途标记。当前参考网格与模板坐标不一致；未注册时拒绝生成。
5. `automation/workbuddy_mcp.py` 提供模板清单、配准预检、受限概念形变，以及 `list_frontend_tasks`、`get_frontend_cover_task`、`prepare_frontend_cover_task` 三个前端订单交接工具。本地协议测试已验证握手与工具调用。旧版项目级 `.workbuddy/mcp.json` 仍保留；**当前国际版 WorkBuddy AI 桌面任务使用 strict MCP 配置，不加载此项目文件**。需从“专家·技能·连接器 → 连接器 → 自定义连接器 → 添加 MCP”注册应用级服务后再验证。

## 前端订单自动交接

独立后台 `/operator/` 中打开一条前端任务，选择模板并点“准备 WorkBuddy 任务”。服务在 `forme-backend/data/cover_tasks/<submission-id>/manifest.json` 生成本地交接清单，保留视频哈希、用户选择、选定视角帧及 COLMAP 原始点云路径。WorkBuddy MCP 连接成功后可列出订单、查看待办和准备交接包；当前国际版应用的 MCP 注册作用于账户，需注意它在其他工作区也可能被调用。

交接包不是生成任务的放行凭证。现在 `build_concept_cover` 已连接本单标尺、人工复核主体点云和操作员配准门禁；缺任一证据时仍拒绝生成。AI 把 `registration.verified` 写成 `true` 不会放行。完整操作及证据格式见 [标尺到保护套数字试样的本地工作流](../forme-backend/COVER_GENERATION_INTEGRATION_ZH.md)。当前形变器和毫米 3MF 只输出审查用数字试样，不能自动宣称佩戴适配。

## 2026-10-06 试验经验接入

`COVER_GENERATION_POLICY.json` 是交接包引用的版本化生成规则。WorkBuddy 每次提出候选前，先记录视频/点云/模板的来源和坐标证据、点云可信区域，以及外部参考是否来自独立实物样本。当前公开参考的三个 STL 来自同一个模拟残肢，不能当三例；它的高上口形状也不能直接套到本项目的低开口保护套，且 GPL 几何没有混入候选。

本次 `market-prior-trial` 仅在可信点云段尝试不超过约 1.12 mm 的平滑修形，保留上口 Z 高度。同源点云截面误差改善可以辅助选迭代方向，不能证明净空或贴合。每个试验须生成 `trial_report.json`、`source_analysis.json` 和前后两片 STL 的哈希，再用 `automation/register_cover_trial.py <trial_dir> <task_dir> <candidate_id>` 登记成每单 `candidate_review.json`。登记会校验文件哈希并在独立后台显示未完成项；它不会批准生产。

当前候选仍须检查上口净空、侧孔薄边、局部壁厚与自交、打印机切片，以及固定件与实物试装。只有操作者复核完这些证据后，才能另行设计生产放行步骤；现有 MCP 建模门禁不因试验记录而解除。

## WorkBuddy 的职责

腾讯 WorkBuddy 可获得这个文件夹的本地访问权限后，读取 `templates/catalog.json`、实拍关键帧、点云和建模报告，提议模板选择、坐标对应关系与低频控制量；它要把结果保存为 JSON 提案，供操作者检查。WorkBuddy 自身不充当生产几何引擎，也不直接改写原 STL。官方文档支持本地文件处理与自定义 MCP/CLI 连接器，但这里没有假设存在可直接调用的 WorkBuddy 云端生成 API。

可给 WorkBuddy 的任务说明：

> 阅读 `templates/catalog.json`、`TEMPLATE_ADAPTATION_TASK.md`、标定点云、实拍关键帧和现有参考网格。优先比较 04 竹影与 05-magnetic；将坐标系、上口、后侧开口和螺栓侧对应关系写成可复核证据。只在高可信表面生成沿高度稀疏分布的 `dx_mm`、`dy_mm`、`radial_x_mm`、`radial_y_mm` 控制点，每项绝对值不超过 3 mm。不能确认配准时保持 `registration.verified=false`，不要执行适配。输出四个视角的审查记录，并标出所有需要重建的卡扣或磁铁孔。

## 规格与运行

```json
{
  "schema_version": 1,
  "template_id": "04",
  "source_sha256": "从 catalog.json 复制",
  "registration": {
    "verified": false,
    "units": "mm",
    "z_up": true,
    "rear_positive_y": true,
    "reference_artifact": "已审核的参考模型绝对路径",
    "evidence": "记录使用的实物标记、坐标变换和残差报告"
  },
  "template_axis_xy_mm": [-3.0, 24.0],
  "controls": [
    {"z_mm": 0, "dx_mm": 0, "dy_mm": 0, "radial_x_mm": 0, "radial_y_mm": 0},
    {"z_mm": 316, "dx_mm": 0, "dy_mm": 0, "radial_x_mm": 0, "radial_y_mm": 0}
  ],
  "approval": "concept_geometry_only"
}
```

实际执行：

```sh
python3 automation/fit_template.py /absolute/path/to/fit_spec.json /absolute/path/to/output
```

WorkBuddy 中以 `/Volumes/extra/workspace1/projects/test4` 为项目打开工作区，确认 `forme-cover-fit` 连接为绿色。先调用 `list_cover_templates` 和 `preflight_reference`；`build_concept_cover` 现在需要 `submission_id`、`candidate_id` 和受限形变 `proposal`，且仅在操作员完成本单标尺、主体点云与配准复核后放行。完整配置和证据门禁见上述工作流文档。

`verified=true` 只能由操作者在对照视频、标靶和网格后填写。形变后的 STL 仍须独立验收：实际内侧净空、壁厚、边界/非流形、自交、两片缝隙、上口和后开口连续性、螺栓避让、固定件尺寸和保持力。原 STL 中的固定件会随主体形变，必须重新建模或实测。先做小段试装样件，再做整件。任何通过软件几何检查的结果都只能标记“概念候选，尚未实物试装验证”。

## 当前阻塞项

现有 `colmap-retune-20261002/smooth-mesh/upper-body-segmented-reference-mm.stl` 的 Z 范围约为 134–366 mm，仅有约 232 mm 高；模板为 0–315 mm。还缺少经实拍标记确认的模板到假肢坐标变换，以及螺栓/固定结构的实测尺寸。根据当前数据自动宣称一套“贴合完成”的保护套会不可靠。下一步先用现有视频与点云做可信区域和坐标注册，再用上述受限适配器迭代；超过限幅的部位改用 Blender 源文件重建，而不是继续拉伸 STL。

另有 `models/test4-cloud-calibrated-mm.ply`，其整云 Z 范围约 −318–67 mm，包含保护套之外的几何和遮挡噪声；不能把整个点云包围盒当成接受腔。七款的机器预检报告位于 `output/template_adaptation/preflight/`，当前全部为 `NEEDS_COORDINATE_REGISTRATION`。
