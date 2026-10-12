# 给服务器 Claude Code：接通 `forme.agents-time.com` 与这台 Mac

这是当前站点的执行清单。请在云服务器上操作，保留已有数据库、上传目录、管理员密码哈希和其他配置。**不要在聊天、提交或日志中输出任何密钥。**

## 已验证事实（2026-10-13）

- `https://forme.agents-time.com/api/health` 返回 `2026.10.12-admin1`。
- `/admin` 返回 302，未登录访问 `/api/worker/jobs` 与 `/api/admin/operator/` 都返回 401。
- 新域名的管理员登录请求能够通过来源检查；错误密码返回 401。
- Mac `127.0.0.1:8001` 已能启动媒体、COLMAP、混元工作器。Mac 尚未收到云端工作器密钥，也尚未建立 SSH 反向隧道。
- 一个真实演示账号已经在新站创建，原始 139,517,016 字节视频上传经过 Cloudflare 时返回 502。演示会改用小于 100 MB 的压缩副本；请同时检查 Cloudflare 上传限制与源站 Nginx 日志。云端应用本身允许最高 512 MiB，不代表 CDN 能通过同样大小的单请求。

## 请在服务器完成

1. 确认运行服务的私有配置（通常 `/www/forme-service/config.json`）有 `worker_key`、`local_operator_token`、`local_operator_url: "http://127.0.0.1:18001"`，并把 `https://forme.agents-time.com` 加入 `origins`；保持文件权限 600。缺失的两个令牌分别生成独立的 48 字节随机值。**不要更换已有有效密钥，除非两端一起更新。**
2. 建立普通非 root 账号 `forme_tunnel`，允许 SSH 公钥登录及反向 TCP 转发，只允许云服务器回环地址 `127.0.0.1:18001` 监听；公网防火墙不开放 18001。把下列 Mac 公钥加入此账号的 `authorized_keys`：

   ```text
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKuiGXDvgH/XtAXQcBnMiyvr9IrwVbtfF0/E054yQyCm forme-mac-tunnel-2026-10-13
   ```

3. 通过服务器本地脚本从私有配置生成一次性的 `/home/forme_tunnel/forme-bridge-bootstrap.json`，内容只包括 `base_url: "https://forme.agents-time.com"`、`worker_key`、`local_operator_token`。文件归 `forme_tunnel` 所有，权限 600；不要放到网站目录。Mac 会用 SSH 拉取，拉取后自动删除。建议用 Python 读取并写入，避免 `jq`、shell 展开或终端打印令牌。
4. 告诉 Mac 侧操作者 **SSH 源站 IP/主机名、端口、用户名 `forme_tunnel`、服务器 SSH 主机密钥指纹**，均为非秘密信息。`forme.agents-time.com` 经过 Cloudflare 代理，SSH 通常不能直接连这个网页域名；请提供源站 SSH 地址或专用 SSH 域名。
5. 确认服务器 SSH 允许 `forme_tunnel` 做 `-R 127.0.0.1:18001:127.0.0.1:8001`。Mac 建立隧道后，在服务器执行 `curl -fsS http://127.0.0.1:18001/health`，并用 `ss -ltn` 确认 18001 只绑定回环。不能将该端口直接暴露公网。
6. 让管理员在 `https://forme.agents-time.com/admin` 登录。演示任务提交后先改为 `accepted` / `queued`，Mac 工作器才会领取。远程操作入口是管理平台中的“打开本机建模工作流”。

## Mac 侧接下来执行

在 `/Volumes/extra/workspace1/projects/test4/forme-backend`：

```sh
.venv/bin/python scripts/pair_cloud.py --host <服务器 SSH 源站地址> --user forme_tunnel --port 22
FORME_CLOUD_CONFIG="$PWD/.cloud-bridge.json" FORME_DATA_DIR="$PWD/data" .venv/bin/python -m forme_backend.cloud_bridge --once
ssh -i data/forme-cloud-tunnel-ed25519 -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -R 127.0.0.1:18001:127.0.0.1:8001 forme_tunnel@<服务器 SSH 源站地址>
```

配对会把两个令牌分别写入 Mac 的私有文件，权限 600；Mac API 要重启才能使用新的 `local_operator_token`。验收完成后让桥接、API、媒体、COLMAP、混元以及 SSH 隧道都以可重启的系统服务运行。不要把演示时临时终端进程当作常驻服务。

## 端到端验收

1. 新站客户账号能登录、上传并提交任务；管理员设为 `accepted` 后，Mac 桥接按相同提交 ID 导入，并核对视频 SHA-256。
2. `--once` 重跑不生成重复任务；云端客户页显示本机接收及后续质检进度。
3. 管理员在新站 `/admin` 打开本机面板，能看到同一 ID、视频资源和阶段；未登录与客户登录不能操作本机。
4. Mac 生成并回传 3MF 数字试样候选后，云端管理员可见；在人工切片与审核前不将状态设为 `ready`。
5. 关闭 Mac：新站登录、上传、查进度仍可用；Mac 恢复后队列继续处理。

当前保护套流程的完成终点是**可审查、可切片的数字试样候选**。实物佩戴适配、上缘间隙与切片结果仍需单独确认。
