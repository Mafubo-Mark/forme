# 接口与接手

## 本机环境

- 后端：`/Volumes/extra/workspace1/projects/test4/forme-backend`
- 后端 Python：后端 `.venv/bin/python`，已安装 FastAPI 和 Store。
- 几何 Python：`/Volumes/extra/workspace1/apps/drawing-with-gaussians/.venv/bin/python`，含 numpy/scipy/trimesh/pycolmap/plyfile。
- Blender：`/Volumes/extra/workspace1/apps/Blender.app/Contents/MacOS/Blender`；可用 `FORME_BLENDER` 覆盖。
- API：本机 `http://127.0.0.1:8001`；管理接口要求 Bearer 权限。凭据只从本机现有私有配置读取，不输出。
- 一键启动 `forme-backend/start-all.command`：管理 API、媒体、COLMAP、scan 保护套队列、云桥接及管理隧道。不要在已有工作器运行时另起重复消费者。

## MCP

现有 `forme-cover-fit` stdio 服务：`work-buddy-handoff/automation/workbuddy_mcp.py`。

- `list_frontend_tasks {}`：列订单。
- `get_scan_workflow {"submission_id":"实际任务号"}`：状态、复核卡、任务目录和 skill 路径。
- `approve_scan_geometry {"submission_id":"实际任务号","confirmation":{"targetLengthConfirmed":true,"geometryReviewed":true,"notes":"说明真实证据"}}`：批准当前默认建议配方。可在 confirmation.recipe 中覆盖经过复核的配方字段。
- `queue_scan_cover {"submission_id":"实际任务号"}`：幂等排队。

MCP 更新后 WorkBuddy 应重新连接该服务，确保工具列表中出现上述工具。不要因工具未刷新而调用旧 build_concept_cover 冒充新路线。

## API

均以 `/api/internal/submissions/{id}` 为前缀，沿用现有管理员鉴权。

| 方法与路径 | 用途 |
|---|---|
| GET /scan-workflow | 状态、建议配方、复核图片 URL |
| POST /scan-workflow/start | `{captureReviewed:true,targetLengthConfirmed:true}`；合并拍摄通过与点云入队，媒体质量检查未通过则拒绝 |
| POST /scan-workflow/approve | `{targetLengthConfirmed:true,geometryReviewed:true,notes:"至少5字",recipe:{可选覆盖}}` |
| POST /scan-workflow/run | 几何批准后幂等排队 |
| GET /production-flow | 新路线四阶段与 STL 下载链接 |
| GET /print-candidate/package | 新路线返回 STL ZIP；旧路线仍可返回 3MF，按 deliveryFormat 区分 |
| GET /print-candidate/stl/front、rear、combined | 有鉴权且校验哈希的毫米 STL |
| POST /scan-workflow/fit-feedback | `{fitConfirmed:true,notes:"真实试戴反馈"}`；只在用户已提供此候选实物反馈时调用 |

## CLI（不需要在命令中传令牌）

在后端目录运行后端 Python：

```sh
.venv/bin/python scripts/scan_workflow_cli.py --data-dir ./data --submission 实际任务号 status
.venv/bin/python scripts/scan_workflow_cli.py --data-dir ./data --submission 实际任务号 start --confirm-capture-and-target
.venv/bin/python scripts/scan_workflow_cli.py --data-dir ./data --submission 实际任务号 approve --confirmation /本单/已确认的复核.json
.venv/bin/python scripts/scan_workflow_cli.py --data-dir ./data --submission 实际任务号 queue
```

确认文件格式与 API approve 一致。只有确实已核对时才能使用确认开关。

## 状态与恢复

- awaiting_reference：点云正在生成，或当前几何仍待准备／确认。根据 model_job.stage 区分。
- approved：当前源视频、相机、标尺、点云、图片和模板哈希已校验。
- queued/running：scan_worker 消费，不需要常驻 WorkBuddy 才能完成确定性阶段。
- ready：只有最终检查通过才出现。结果目录 `data/cover_tasks/{id}/scan_candidates/{candidateId}`。
- failed：读 error 与 worker.log，修复依据后重新 approve，再 queue。使用新候选号，不覆盖半成品；同配置两次后停止。
- 重启发现 running 时标记中断，不悄悄发布部分结果。

云桥接会读取新路线最终组合 STL，沿用已有 worker artifact 接口回传。云端管理员可通过现有 `/api/internal/*` 代理调用新接口；若服务器按固定路由白名单过滤，须由服务器同事允许 scan-workflow 子路径。新订单的参考准备仍由本机 Agent 完成，后台不会自行启动一套 AI 对话。
