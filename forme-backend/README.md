# Forme 后端工作流：第一段

> **2026-10-17 主流程更新**：新订单优先使用点云驱动的全高适配、低上口、下段延长和螺栓避让；无需混元。后台已提供三步入口和持久 scan 队列。操作与 Agent 托管见 [点云主流程](SCAN_WORKFLOW_ZH.md)。下文保留旧概念路线资料，其六视角、混元与 3 mm 微调限制不适用于新入口。

当前 Mac 演示链路的**一键启动、停止和 STL 下载**见 [ONE_CLICK_STL_ZH.md](ONE_CLICK_STL_ZH.md)。双击 `start-all.command` 后可在本机面板下载前片、后片及组合 STL；云桥接回传组合 STL，3MF 作为辅助切片文件保留。数字试样仍需人工复核，不能自动放行为可佩戴成品。

云端管理员远程操作模式：将云端私有配置的 `local_operator_token` 写入本机 `.local-operator-token`（权限 600），`run-local.sh` 会读取稳定令牌且不打印。云端通过仅监听服务器回环地址的 SSH 反向隧道访问本机 API。部署细节见 `../forme2/deploy/REMOTE_OPERATOR_ZH.md`。

当前实现了真实视频接收、文件哈希与大小校验、FFprobe 元数据检查、八张人工复核帧、浏览器兼容的视频预览、持久化状态和查询接口。Forme 的 `Create your cover` 页面会实际上传视频并提交颜色、材料、灵感文字和图片；`My Prosthetic` 会显示当前测试会话提交的任务和状态。独立 `/operator/` 操作后台会列出前端任务，打开后能查看用户资源、选择、视频质检、人工复核与多视角选帧进度。人工拍摄复核通过后，可创建独立参考模型任务，由本机 COLMAP 工作器抽帧、恢复相机并生成原始点云。**原始点云没有毫米尺度，也不是可制造假肢模型**；任务会停在标靶定尺度复核。多视角 AI 判断可通过 DeepSeek 官方视觉 API。一次人工确认的选图已通过 `scripts/hunyuan_pro.py` 提交腾讯云国际版混元 3D 3.1，结果、预览和哈希归档在该测试任务下；操作面板可读取，但云端提交尚未接入自动队列。当前仍没有自动识别 200 mm 标靶或 Blender 在线服务；`POST /api/model/generate` 保留 501，不会生成虚假的成功状态。订单、配送、演示登录等页面仍是原始演示逻辑，来源见 `FRONTEND_SOURCE.md`。

这是本机开发版本。前端使用浏览器测试会话 Cookie，操作面板使用开发 Bearer token；服务只应绑定 `127.0.0.1`。上线前须换成正式用户身份验证、后台角色、私有对象存储与正式数据库。上传资料和派生预览留在本机 `data/`（已在 `.gitignore` 中），不得提交到仓库。

操作后台新增“保护套模板库”：`GET /api/internal/templates` 读取 `work-buddy-handoff/templates/catalog.json`，返回七套模板和未识别 STL 数量，必须使用开发 Bearer token。源文件归档、适配预检与 WorkBuddy MCP 接入见 [保护套适配工作流](../work-buddy-handoff/TEMPLATE_FIT_WORKFLOW.md)。目前模板仅登记，面板不显示“已贴合”。

后台现在可为前端任务选择模板并生成本地 WorkBuddy 交接清单。`GET/POST /api/internal/submissions/{id}/cover-task` 使用同一开发令牌；POST 输入 `{"template_id":"04"}`。清单存于 `data/cover_tasks/{id}/manifest.json`，WorkBuddy 的项目 MCP 可读取订单和交接状态。这个步骤只组织输入，不会将原始未定尺度 COLMAP 点云当成毫米模型，也不会自动生成保护套。

2026-10-06 起，交接清单包含版本化的 `COVER_GENERATION_POLICY.json` 及哈希。试验模型由 `work-buddy-handoff/automation/register_cover_trial.py` 校验报告和 STL 哈希后登记为每单 `candidate_review.json`；独立操作后台显示候选与未完成检查。当前实例是低开口、露出高翻边的祥云上身微调候选，仍需上口净空、侧孔薄边、局部壁厚、自交、切片和实物试装复核。新的 WorkBuddy 概念生成入口要求本单标尺、人工复核点云裁剪和操作员配准批准；历史试验记录本身不会解除门禁。完整做法见[标尺到保护套数字试样工作流](COVER_GENERATION_INTEGRATION_ZH.md)。

## 启动

从视频到数字试样候选的阶段、接口、启动方式和目前的人工门禁见[后台生产工作流](PRODUCTION_WORKFLOW_ZH.md)。

需要 Python 3.11+、FFmpeg/FFprobe。本机已有 `uv`、Python 和 FFmpeg，首次安装：

```sh
cd /Volumes/extra/workspace1/projects/test4/forme-backend
UV_CACHE_DIR=/private/tmp/forme-uv-cache /Volumes/extra/workspace1/apps/uv/uv venv --python /Volumes/extra/workspace1/apps/uv/python/cpython-3.11.16-macos-aarch64-none/bin/python3.11 .venv
UV_CACHE_DIR=/private/tmp/forme-uv-cache /Volumes/extra/workspace1/apps/uv/uv pip install -e '.[test]'
./run-local.sh
```

脚本默认生成随机开发令牌并在终端打印。打开 `http://127.0.0.1:8001/create.html` 提交测试任务，再打开独立操作后台 `http://127.0.0.1:8001/operator/` 并填入该令牌。用户站点导航不显示后台入口。后台可查看原视频、预览、灵感图和进度，运行视频质检并抽取最多 18 张多视角候选帧。可手动标定正面、确认六个方向的选图；未选满的方向标为待补拍。另开终端运行 `.venv/bin/python -m forme_backend.worker` 也可批量处理已上传视频。`GET /health` 和静态页面不需要令牌；操作接口需 `Authorization: Bearer <FORME_DEV_TOKEN>`，前端提交接口需本机测试会话 Cookie。

视觉 API：默认直连 DeepSeek 官方，模型 `deepseek-flash`。在启动后端的终端设置 `FORME_DEEPSEEK_API_KEY`，然后重启服务。可设置 `FORME_VISION_PROVIDER=tokenhub` 和 `FORME_TOKENHUB_API_KEY` 使用腾讯云 TokenHub 国际站，默认模型为 `deepseek/deepseek-flash`。`FORME_VISION_MODEL` 可覆盖模型名。不要把 Key 放进前端页面、浏览器或仓库。操作员在后台点“调用视觉 API”时，服务端才会将最多 18 张候选 JPEG 帧（如已标定正面，则该帧也会随每个判断请求发出）以 Base64 发给所选提供方，不会发送原视频。每帧最多一次请求，模型输出方向建议和理由；其置信度为模型自报值，不是实测准确率。请求记录保留模型名、响应 ID 与 token 用量，但不保存完整 API 响应。未配置 Key 时返回 `VISION_API_NOT_CONFIGURED`，人工选图仍可使用；API 失败时显示失败或部分完成状态。真实上口俯视和螺栓侧若缺失，必须补拍；选图确认不等于 200 mm 标靶定尺度或可制造模型验收。[DeepSeek 官方视觉文档](https://api-docs.deepseek.com/guides/vision/)

## 本机参考模型任务

在面板中核对真实拍摄视频与标靶，写复核记录并点击“通过拍摄复核”，再点击“启动 COLMAP 建模任务”。启动按钮只入队；另开终端使用**同一令牌及 data 目录**启动单工作器：

```sh
cd /Volumes/extra/workspace1/projects/test4/forme-backend
FORME_DEV_TOKEN=<启动服务时的令牌> FORME_DATA_DIR="$PWD/data" \
  .venv/bin/python -m forme_backend.model_worker
```

`--once` 只处理一个任务。工作目录是 `data/model_jobs/<job-id>/`，保留抽帧、COLMAP 工程、日志、原始 `fused.ply` 和带 SHA-256 的 `manifest.json`。任务阶段事件出现在面板详情和 `My Prosthetic`。同一数据目录只允许一个模型工作器持有文件锁；取得锁后，重启会重新排队中断的 `running` 任务。不能在未核实标靶和独立局部尺寸前把点云标为毫米模型，也不能把旧项目的 141.22 mm/COLMAP 单位直接套到新用户视频。

## 混元 3D 单次人工测试

已确认的方向图片打包后，`scripts/hunyuan_pro.py` 可按 `check → submit → poll → archive` 运行腾讯云国际版混元 3D 3.1 专业接口。它读取项目外的 `SecretId/SecretKey` CSV，不把密钥写进任务文件；`submit` 只执行一次，并用任务记录阻止重复提交。专业接口目前将正面作为主图，左、右、背面作为辅助图；上视图和螺栓图保留作生成后检查。单次生成需按腾讯云计费规则消耗额度，并将四张图片上传到所选区域，操作前应取得该组图片的明确授权。[提交接口](https://intl.cloud.tencent.com/zh/document/product/1284/75540)

本次任务的原始 GLB、预览图、输入哈希和查询记录保存在 `data/cover_tasks/<submission-id>/hunyuan_inputs/`。`scripts/align_hunyuan_candidate.py` 的旧探索性对齐使用了截面未确认的 120/80 mm 记录，因此其比例和距离只能用于几何差异检查。用户已说明实物不可复测；`scripts/build_ruler_only_assessment.py --submission-id <id>` 从同一视频的 200 mm 标定尺和两套 COLMAP 重建生成 `ruler_only_assessment.json`，明确区分比例一致性和局部曲面误差。旧的 10.3 mm 模板缺口比较跨越不同截面，已撤回。操作面板显示标尺推算与其限制；模板须与点云在同高度、同方向注册后才能比较内腔。混元模型里的鞋和合成螺栓必须排除，不能把点云到模型的最近距离当作贴合净空。标尺可支持可视化设计候选，无法单独核准佩戴或打印成品。

`scripts/build_ruler_template_concept.py` 以原版祥云前后片和标尺点云外轮廓生成仅供造型审查的 GLB；`scripts/render_ruler_template_concept.py` 在 Blender 中输出四个视角和 `.blend` 场景。输出位于任务的 `ruler_only_template01_concept/`，后台通过鉴权媒体路由显示图片和 GLB。生成器限制纹样缩放，报告保留剩余外轮廓缺口；不生成适配 STL、不解除 `build_concept_cover` 门禁。

`scripts/audit_pointcloud.py --submission-id <id>` 复查原视频和复用点云哈希、标尺两套重建结果、有限坐标与每 10 mm 截面的角度采样，写入 `pointcloud_qa.json`。本次任务 32 个截面中只有 20 个覆盖全部 24 个角度分箱；下部与上口缺角。即使覆盖充分，角度采样也不是局部表面精度或佩戴间隙的证明。

## 状态与下一段

`initiated → uploading → uploaded → validating → needs_capture_review → accepted / needs_recapture`。不可解码、视频时长或分辨率不合要求时为 `rejected`；媒体处理工具不可用时为 `validation_failed`，保留原上传供排障。当前仅支持一个工作器实例；重启会重新排队未完成的 `validating` 任务。八张复核帧只是供人工看标靶和视角，绝不自动判定几何质量。

下一段接入标靶自动检测、混元任务自动队列、可信区域注册和 Blender 模板重设计；生成的任何 mesh 均需保存来源、毫米尺度变换和质量报告。只有经过对应实物尺寸及坐标注册复核的模型版本可以继续保护壳模板适配。
