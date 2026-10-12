# 云端 `/admin` 远程操作 Mac 工作流

## 访问路径

管理员登录 `https://my-robot-home.com/admin`，点击“打开本机建模工作流”。云端 `/api/admin/operator/` 代理本机 `/operator/` 页面；页面的 `/api/internal/*` 操作和本机 `/api/uploads*` 读取都先检查云端管理员会话，再由云端服务端加入本机 Bearer 令牌。浏览器看不到该令牌。Mac 离线时远程面板返回 503，云端用户登录、上传、任务和订单查询继续工作。客户首页没有后台入口。远程面板只能操作已由云端工作器桥接导入 Mac 的任务；云端新任务须先在管理平台接受，再由桥接程序领取。

## 现有云服务器升级

这不是重新运行 `cloud/deploy.py` 的步骤；该脚本只供全新、尚无 `/www/forme-service` 的服务器使用。

1. 先备份 `/www/forme-service/config.json`、数据库、私有上传目录和当前 Nginx 配置。升级 `cloud/app.py`、`cloud/requirements.txt`、`dist/` 文件，在云端虚拟环境安装新增依赖 `httpx==0.28.1`。
2. 在 `/www/forme-service/config.json` 中添加独立随机 `local_operator_token`（至少 32 字节随机值）和 `local_operator_url` 值 `http://127.0.0.1:18001`。保留现有数据库、`worker_key` 和其他配置。运行 `FORME_CONFIG=/www/forme-service/config.json python3 cloud/set_admin_password.py`，交互输入新密码，脚本只保存 scrypt 哈希 `admin_password_hash`。管理员用户名仍为 `forme`。不能继续使用旧的 `123456` 密码；新代码在未配置哈希时拒绝管理员登录。不要把明文写进命令历史、GitHub 或聊天。配置文件权限保持 600，所有者为运行 `forme-cloud.service` 的用户。
3. 目标站 Nginx 的 HTTPS server 块需保留 `/api/` 到 `127.0.0.1:18086` 的转发，并加入 `location = /admin { return 302 /admin.html; }`。不要公开 `18001`；云端防火墙和 SSH 守护进程均不应允许公网直接访问隧道端口。执行 `nginx -t` 后重载。重启 `forme-cloud.service`，检查 `/api/health` 版本 `2026.10.12-admin1`。
4. 在服务器 SSH 配置中为专用隧道账号允许 TCP 转发，并将远端监听限制为 `127.0.0.1:18001`。本机 SSH 连接到服务器后运行 `ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:18001:127.0.0.1:8001 <隧道账号>@<服务器域名或 IP>`。此隧道由 Mac 主动建立，不需在 Mac 开入站端口。建议为隧道账号配置专用 SSH 密钥、禁用交互 shell、只允许这一个远端转发。在 Mac 上把 [launchd 示例](com.forme.operator-tunnel.plist.example) 中的账号和主机替换成实际值，保存到 `~/Library/LaunchAgents/com.forme.operator-tunnel.plist`，再运行 `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.operator-tunnel.plist`；launchd 会在断线后重连。
5. 将云端 `local_operator_token` 通过可信的管理员通道写入 Mac 的 `forme-backend/.local-operator-token`，`chmod 600`。它必须与云端字段完全相同；不要与云端 `worker_key` 混用。用 `forme-backend/run-local.sh` 启动本机 API，它会读取稳定令牌且不在终端打印。另按 [工作器说明](CLOUD_MAC_BRIDGE_ZH.md) 运行云端任务桥接、媒体与模型工作器。

## 验收

1. 未登录访问 `/api/admin/operator/` 和 `/api/internal/worker-status` 都应为 401；客户账号不能操作本机。
2. 管理员登录后，`/api/internal/worker-status` 应返回本机状态，面板可列出桥接导入的任务。用一条测试任务执行一次允许回退的操作，确认本机任务状态变化并显示在云端进度。
3. 断开 Mac 隧道：远程面板显示离线；云端客户登录、上传和查进度仍可用。重连后同一任务继续操作，不重复创建任务。
4. 在云端检查 `ss -ltn`：`18001` 只能监听 `127.0.0.1`；从公网对 `18001` 的连接应失败。

本机保护套输出仍以可审查、可切片的数字试样候选为终点；标尺、人眼检查和最终 `ready` 发布由管理员确认。
