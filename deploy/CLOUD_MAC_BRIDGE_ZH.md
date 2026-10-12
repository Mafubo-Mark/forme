# 云端与 Mac 建模工作流连接

## 当前实现与边界

云端仍负责 24 小时登录、视频上传、设计记录和进度查询。后台任务桥接由 Mac 向云端 HTTPS 发起出站请求；管理员远程操作本机工作流另通过仅绑定云端回环地址的 SSH 反向隧道，见 [远程管理说明](REMOTE_OPERATOR_ZH.md)。云端 MySQL 的 `worker_jobs` 保存待领取任务；管理员在云端将提交状态设为 `accepted` 后进入队列。Mac 下载视频并核对字节数与 SHA-256，按原云端 ID 导入本机 `forme-backend` 的 SQLite 和私有文件目录。断线重试不会另建一份提交。

导入后，本机原有 `worker.py` 进行 FFprobe/FFmpeg 媒体质检；操作员仍在本机 `/operator/` 核对标尺、视角和上口，再批准拍摄。COLMAP、混元、标尺、点云与保护套的既有门禁保持不变。桥接程序每 30 秒把阶段回写云端。只有本机产生具有 `candidate_print_trial` 审查记录的 3MF 数字试样候选时，桥接程序才上传该文件；云端保持 `modeling` 状态。管理员检查切片与质量后，才能手动将状态改为 `ready` 并报价。客户在 `ready` 前看不到候选模型下载链接。

## 云服务器部署

1. 使用 **Python 3.11 或更高版本**。锁定的 SQLAlchemy 2.1.4 不支持 Python 3.9。部署新站时，`cloud/deploy.py` 会生成 48 字节随机工作器密钥，写在 `/www/forme-service/config.json` 的 `worker_key` 字段；该文件权限为 600，绝对不要放到网站目录、GitHub 或聊天中。现有服务升级时需要保留已有配置，手动添加随机 `worker_key`，并部署更新后的 `cloud/app.py`；`Base.metadata.create_all` 会新增 `worker_jobs` 表。先备份数据库与配置，再重启服务。
2. 验证 `curl -fsS http://127.0.0.1:18086/api/health` 返回版本 `2026.10.12-admin1`，且未携带工作器密钥的 `/api/worker/jobs` 返回 401；用云端管理平台将一个已提交的设计标为 `accepted`，不要直接标为 `ready`。
3. 云端只通过同域 `/api/worker/*` 对外提供工作器接口，需 HTTPS 和工作器 Bearer 密钥。不要把密钥交给浏览器。建议在云端 Nginx 对 `/api/worker/` 单独做源 IP 限制（若 Mac 出口 IP 固定）、访问日志脱敏与请求速率限制。

## Mac 设置与运行

本机桥接代码位于 `forme-backend/src/forme_backend/cloud_bridge.py`，交付副本在本仓库 `worker/cloud_bridge.py`。更新 Mac 时，把交付副本复制到本机 `forme-backend/src/forme_backend/cloud_bridge.py`。使用本机项目现有的 `.venv`。通过可信的管理员通道取得云端工作器密钥，写到本机 `.cloud-bridge.json`，内容形如 `{"base_url":"https://my-robot-home.com","worker_key":"<随机密钥>"}`，并运行 `chmod 600 .cloud-bridge.json`。不要提交、发送或把密钥放进浏览器。运行示例：

```sh
cd /Volumes/extra/workspace1/projects/test4/forme-backend
export FORME_CLOUD_CONFIG="$PWD/.cloud-bridge.json"
export FORME_DATA_DIR="$PWD/data"
.venv/bin/python -m forme_backend.cloud_bridge --once
.venv/bin/python -m forme_backend.cloud_bridge
```

`--once` 只做一轮领取和同步，适合验收；最后一行持续运行。它与本机 `run-local.sh`、媒体和模型工作器是不同进程。Mac 关机时云端提交留在队列，客户仍能登录和查询。桥接服务重启会重新读取云端 `monitoring` 任务和本机相同 ID 的记录。生产运行可使用 [launchd 示例](com.forme.cloud-bridge.plist.example)：确认其中路径后复制到 `~/Library/LaunchAgents/com.forme.cloud-bridge.plist`，运行 `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.cloud-bridge.plist`。该 plist 只包含私有配置文件路径，不包含密钥。

## 接口契约

所有接口要求 `Authorization: Bearer <worker_key>`：

| 接口 | 用途 |
| --- | --- |
| `POST /api/worker/claim` | 原子领取最早的已批准任务，返回任务清单和 15 分钟租约令牌 |
| `GET /api/worker/jobs/{id}/video` | 下载私有原视频；本机必须核对大小和 SHA-256 |
| `POST /api/worker/jobs/{id}/heartbeat` | 下载或导入时间较长时续租，另需 `X-Job-Token` |
| `POST /api/worker/jobs/{id}/imported` | 导入后用 `X-Job-Token` 确认，任务进入持续监控列表 |
| `GET /api/worker/jobs` | 重启后列出需要同步的已导入任务 |
| `POST /api/worker/jobs/{id}/requeue` | 本机记录丢失时重新排队并按原视频哈希导入 |
| `POST /api/worker/jobs/{id}/progress` | 回写有限的阶段和备注，禁止由工作器设置 `ready` |
| `PUT /api/worker/jobs/{id}/artifact` | 以 SHA-256 校验上传 GLB/STL/3MF 候选，仍需人工审核 |

若领取后 15 分钟内未确认导入，租约过期，任务会被重新领取。本机按相同 ID 和视频哈希导入，避免重复提交。重试仍失败时应查看云端 `worker_jobs` 状态和本机桥接日志。云端重启不清空数据库任务；视频与任务数据库必须一起备份。

## 验收步骤

1. Mac 桥接关闭时，云端注册、登录、上传和查进度仍可用；新设计经管理员批准后排队。
2. 在 Mac 运行 `--once`，确认本机 `/operator/` 出现相同 ID 的设计，原视频哈希一致，云端显示本机已接收且等待人工复核。
3. 再运行 `--once`，确认没有新增第二份本机提交。模拟 Mac 断网后恢复，进度能继续回写。
4. 本机质检失败应回写补拍/停止；本机点云到了 `scale_review`，云端应显示需标尺复核，不显示已完成。
5. 本机产出经过数字试样门禁的 3MF 后，确认云端管理员可下载，客户在管理员明确设为 `ready` 前不可下载或下单。

此连接只传任务和经门禁产生的候选文件，不声称自动完成标尺确认、佩戴适配或付款。
