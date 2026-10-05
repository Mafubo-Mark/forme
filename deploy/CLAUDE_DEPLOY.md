# 给服务器上 Claude Code 的部署交接

目标：部署此仓库的 `dist/` 为公开用户网站。**不要部署或创建操作后台。** 实际 API 和视频数据继续保存在用户本地电脑运行的 Forme 后端。

## 已有资源和未决输入

- GitHub 仓库：`https://github.com/Mafubo-Mark/forme`，使用最新 `main`。
- 站点静态目录：仓库的 `dist/`。无需 npm 构建。
- 本地后端：`127.0.0.1:8001`，只在用户电脑上监听回环地址。
- 云服务器系统、域名、公网 IP、SSH 用户和证书路径尚须向用户确认；不要猜测或把示例域名当真。
- 网站不能在 SSH 隧道断开或用户电脑关机时完成登录、上传和状态查询；应在部署验收中明确这一限制。

## 建议实施步骤

1. 确认真实域名、TLS 证书、Nginx 版本和 SSH 访问方式。只将 `dist/` 同步到云服务器站点目录，例如 `/srv/forme/web`。
2. 参照 `deploy/nginx-forme.conf.example` 配置 HTTPS，同源代理仅允许 `/api/customer/*` 和 `/api/uploads/*`。把其他 `/api/*`、`/operator` 与 `/operator/*` 明确设为 404。禁止把本地 `FORME_DEV_TOKEN` 或客户密钥写进云端前端代码。
3. 在云服务器 SSH 设置中仅允许将远程转发端口绑定 `127.0.0.1:18001`。用户本地执行 `deploy/connect-local-backend.sh user@server`，建立 `127.0.0.1:18001 → 本机 127.0.0.1:8001` 反向隧道。用专用 SSH 用户／密钥并限制端口转发范围。
4. 本地后端以 `FORME_SECURE_CUSTOMER_COOKIE=1` 重启，确保 HTTPS 登录 Cookie 带 `Secure`。客户共享密钥仅留在本地后端，文件权限 600。
5. 设置 Nginx 最大请求体至少 520 MB，长时间上传超时至少 600 秒，并确认代理不缓冲大视频到云盘（`proxy_request_buffering off`）。按照服务器实际带宽和磁盘空间再调优。
6. 为 Nginx 和 SSH 隧道设置自动重启与故障监控；证书自动续期。域名、路径和证书配置完成后执行 `nginx -t` 并重新加载。

## 必须完成的验收

- 网站首页、登录页、七款样式的缩略图与 3D 旋转预览正常；英文和繁体中文可互换。
- 未登录访问 `/api/customer/submissions` 得到 401；错误密钥无法登录；正确密钥可登录，并获得 HttpOnly、Secure Cookie。
- 登录后上传一段用户授权的视频，选择样式和颜色，点击提交；本地操作后台任务列表出现同一提交 ID、视频文件、样式与颜色。
- 公网 `/operator/`、`/api/internal/submissions`、`/api/model/generate` 返回 404；云端静态目录不含本地数据库、视频、开发令牌或密钥。
- 关闭本地隧道时，页面仍能打开，但 API 明确失败；重新连接后可恢复，无重复提交或虚假成功提示。

**请在实际部署前向用户确认服务器和域名信息。** 若现有云服务器不运行 Nginx，保留同样的 HTTPS、路径白名单、请求体限制与回环端口约束，再给出对应配置。
