# 标尺到保护套数字试样的本地工作流

> **2026-10-17 主流程更新**：新订单优先使用点云驱动的全高适配、低上口、下段延长和螺栓避让；无需混元。后台已提供三步入口和持久 scan 队列。操作与 Agent 托管见 [点云主流程](SCAN_WORKFLOW_ZH.md)。下文保留旧概念路线资料，其六视角、混元与 3 mm 微调限制不适用于新入口。

## 当前入口

操作面板 `/operator/` 的同一订单中完成：视频质检 → 六视角确认 → COLMAP → 标尺 → 主体点云裁剪 → 模板配准 → WorkBuddy 形变提案 → 概念保护套 → 网格与切片审查。保护套生成只产出数字试样候选，不代表贴合或可以直接交付佩戴。

## 标尺怎么判定

1. 视频中使用**已知两圆心间距为 200 mm** 的标靶。该物理长度必须由原标靶的制作规格确认；单凭视频无法证明打印时没有缩放。
2. COLMAP 完成后，操作面板加载建模帧。点“建议同心圆标点”，程序用找圆加中央黑点连通域给出两个圆心。它在本次历史标注的 29 帧中找到完整双圆的 16 帧；这些帧的圆心相对人工标注中位最大误差约 0.56 像素。其余帧仍需手工标注或跳过。
3. **每帧人工核对 A/B 是同一枚物理标靶**；圆心建议本身不直接放行。至少确认 3 个不同相机位置，最好选择视角跨度明显的帧。
4. 服务端按本单 COLMAP 相机求两圆心的三维交会。必须有至少 3 张共同内点，检查重投影误差和相机夹角，得到 `mmPerColmapUnit = 200 / 三维圆心距离`。标定结果绑定源视频与 COLMAP 模型哈希。
5. 这得到的是**全局候选尺度**。局部点云噪声、遮挡、标靶自身缩放和保护套内腔间隙仍需单独审查；失败时停止概念生成。

## 主体点云裁剪

先把当前 COLMAP `fused.ply` 中的假肢主体裁成独立 PLY，排除鞋、床、地面与标靶。操作员在点云查看器中复核裁剪，再运行：

```sh
GEOMETRY_PYTHON=/Volumes/extra/workspace1/apps/drawing-with-gaussians/.venv/bin/python
$GEOMETRY_PYTHON scripts/review_subject_crop.py \
  --task-root data/cover_tasks/<submission-id> \
  --raw-cloud data/model_jobs/<model-job-id>/dense/fused.ply \
  --subject-crop /absolute/path/to/reviewed-subject-crop.ply \
  --source-video data/uploads/<upload-id>/source.video \
  --notes '已在三维查看器逐段确认主体点云；已排除背景、标靶和鞋。' \
  --operator-confirmed
```

脚本检查裁剪点是当前原始点云的子集抽样、记录哈希和复核说明，写入本单 `pointcloud_qa.json`。这不是自动表面精度证明。若局部缺点或上口区域不清晰，应补拍或仅做外观概念，不得用缺失区域推断内腔贴合。

## 模板配准与形变

WorkBuddy 可以结合混元白模与已定尺度点云提出模板轴线、坐标变换和沿高度的形变控制点；混元模型没有可信毫米单位，只能用于外观和缺失区域提示。控制点最终必须在模板毫米坐标系中表达。

操作员准备至少 3 张不同方向的点云/模板叠图，放入本单 `data/cover_tasks/<submission-id>/`；在面板的“标尺、点云、配准与概念保护套”输入 JSON：

```json
{
  "cloudToTemplateTransform": [[141.2, 0, 0, 0], [0, 141.2, 0, 0], [0, 0, 141.2, 0], [0, 0, 0, 1]],
  "overlayPaths": ["overlay_front.png", "overlay_side.png", "overlay_back.png"],
  "notes": "已检查上口、主体轴线、左右及前后方向；三方向叠图与可信点云区域一致。"
}
```

以上矩阵只是格式示例，不能直接复制到真实订单。前三列长度必须与本单标尺所得 `mmPerColmapUnit` 在 2% 内一致，三轴正交且不得镜像。叠图必须由真实点云和实际模板配准输出；服务端锁定相关文件哈希。审批作用范围仅为概念形变。

WorkBuddy 形变提案 JSON 包含 `template_axis_xy_mm` 和 `controls`。控制点是按高度排序的 `{z_mm,dx_mm,dy_mm,radial_x_mm,radial_y_mm}`；每点总位移不超过 3 mm。顶部最后 30 mm 两个控制点必须为零，保留已确定的低开口，不扭曲上缘。面板粘贴提案并填候选编号，然后点击“生成概念保护套”；或者让 WorkBuddy 调用 `build_concept_cover` 并传 `submission_id`、`candidate_id`、`proposal`。WorkBuddy 无法自批配准。

生成器验证模板来源哈希、标尺、点云裁剪、配准叠图、形变边界后输出前后两片 STL 和审查记录。随后在面板点击“打包试样候选”，拓扑通过后才生成毫米 3MF。还要在目标切片软件中检查局部壁厚、自交、侧孔薄边、固定件和打印配置。由于没有实物测量，不能把试样候选标成佩戴适配完成。

## 当前实测状态

历史视频的同心圆建议与人工标注做过离线对比；现有 14 项后端测试通过。用临时模拟证据实际跑通了模板 04 的双片形变和毫米 3MF 打包，输出检查为单组件、闭合且法向一致；模拟数据已删除。新的保护套审批门禁和输出路径已接入面板及 WorkBuddy MCP，但**尚未拿一条具备操作员复核主体裁剪和三方向配准叠图的新订单跑完该新路径**。历史订单的 `pointcloud_qa.json` 明确写着 `subjectCropIsVerifiedSegmentation=false`，因此不会被这个新门禁误放行。下一次完整验收需要真实提交、裁剪、叠图、提案以及切片复核。
