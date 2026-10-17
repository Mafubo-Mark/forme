# 假肢外侧保护壳：Work Buddy 交接包

这是在同一台 Mac 上可直接使用的独立素材目录。原始项目文件仍保留在 `../`，这里是交接副本。**目标是假肢接受腔外侧的保护壳，不是接触残肢皮肤的内衬。**

## 先看什么

1. `evidence/original_video/IMG_3761.MOV`：44 秒原始环绕视频，是外形、上口和螺栓位置的首要视觉证据。`evidence/video_coverage_contact_sheet.jpg` 方便快速浏览。`evidence/key_frames/` 有六张重点帧。
2. `blender/base_scene.blend`：可编辑的 Blender 5.2 场景，含灰色 Hunyuan 假肢参考模型、旧保护壳、控制网格、螺栓切割器。场景已按顶部开口 120 mm 的解释缩放为毫米，但精度未经试装确认。
3. `models/test4-cloud-calibrated-mm.ply`：按视频中的 200 mm 标靶校准的点云；`models/hunyuan31-v2-aligned-mm.stl` 是放缩并对齐到该点云坐标系的生成模型。适合探索性轮廓比较。
4. `baselines/auto_seed/`：当前无装饰的 C 形保护壳基线，含 STL、四视角图和拓扑指标。它是自动迭代起点，不是成品。
5. `automation/`：确定性 Blender 建模器、参数文件、可选的 DeepSeek 自动看图循环。任务说明见 [WORK_BUDDY_TASK.md](WORK_BUDDY_TASK.md)。

若使用**合作伙伴现成模板自动适配**的新路线，请直接交给 Work Buddy 阅读 [TEMPLATE_ADAPTATION_TASK.md](TEMPLATE_ADAPTATION_TASK.md)。合作伙伴模板放入 `templates/`；当前交接包中尚无这些文件。

`MANIFEST.json` 列出静态素材的相对路径、文件大小和 SHA-256；`output/handoff_smoke/` 是从交接包自身成功运行 Blender 后生成的验收样例。

## 目录要点

| 路径 | 用途 | 注意 |
| --- | --- | --- |
| `models/hunyuan31-v2-original.stl` | 原始约 150 万三角面生成模型 | STL 无物理单位，含鞋和下部幻觉几何。 |
| `models/hunyuan31-v2-aligned-mm.stl` | 已对齐毫米点云的完整模型 | 与 `blender/base_scene.blend` 的本地坐标**不同**。 |
| `models/test4-cloud-calibrated-mm.ply` | 标定后的参考点云 | 有缺口和噪声，不是完整真值。 |
| `models/fused-raw-reconstruction.ply` | 原始稠密重建点云 | 未直接与 Blender 场景对齐。 |
| `baselines/legacy_cover/` | 早期视觉设计、STL、验证数据 | 3 mm 壁厚、标称 8 mm 偏移；未验证配合。 |
| `baselines/auto_seed/` | 无装饰、螺栓避让的自动循环起点 | 单一封闭网格，约 313 mm 高。 |
| `reports/` | 既有比对数据和失败诊断 | 过去 DeepSeek 自由写 Python 的两轮尝试均失败。 |

## 本机运行

Work Buddy 可以自行读取图片和结果，修改 `automation/seed_spec.json` 的**副本**，按下式调用确定性建模器，循环检查 `front.png`、`rear.png`、`bolt_side.png`、`three_quarter.png` 和 `metrics.json`：

```sh
/Volumes/extra/workspace1/apps/Blender.app/Contents/MacOS/Blender -b \
  /Volumes/extra/workspace1/projects/test4/work-buddy-handoff/blender/base_scene.blend \
  --python /Volumes/extra/workspace1/projects/test4/work-buddy-handoff/automation/build_iteration.py -- \
  /Volumes/extra/workspace1/projects/test4/work-buddy-handoff/automation/seed_spec.json \
  /Volumes/extra/workspace1/projects/test4/work-buddy-handoff/output/iteration_00
```

如果改用 DeepSeek 自动循环，执行 `python3 /Volumes/extra/workspace1/projects/test4/work-buddy-handoff/automation/agent_loop.py`。未设置 `DEEPSEEK_API_KEY` 时，交互式终端会隐式提示输入；密钥不会保存，也不会传给 Blender。Work Buddy 若自身能看图并改参数，可直接运行上面的 Blender 命令，无需 DeepSeek 密钥。

## 界限

用户已给出的尺寸线索：顶部开口最宽处约 **120 mm**，筒身正面左右外径约 **80 mm**。两者在既有报告中有测量位置和解释的不确定性。螺栓头尺寸尚未测量；不要凭渲染图宣称螺栓避让、间隙和固定方式已适合实物。用户不希望为了完成视觉设计反复手量尺寸，但最终可制造结论仍需实物验证。
