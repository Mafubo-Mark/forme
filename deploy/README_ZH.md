# 前端云部署／本地后端连接

`dist/` 是独立静态站点，只上传这个目录到云服务器。`operator/`、`data/`、本地密钥文件和后端源码不进入公开网站目录。云服务器用 Nginx 提供 HTTPS 页面，并把同一域名下的 `/api/customer/*`、`/api/uploads/*` 通过 SSH 反向隧道转发到本机 `127.0.0.1:8001`。其他 `/api/*` 和 `/operator/*` 明确返回 404。

1. 在本地后端设置 `FORME_SECURE_CUSTOMER_COOKIE=1` 后运行 `./run-local.sh`。客户密钥存于本机 `.customer-access-key`，权限应为 600；可以在启动前用 `FORME_CUSTOMER_ACCESS_KEY` 指定自己的强随机密钥。
2. 在云服务器部署 `dist/` 到 `/srv/forme/web`，依据 `nginx-forme.conf.example` 配置域名、TLS 证书和静态目录。Nginx 必须允许至少 520 MB 上传，并让 `/api` 与页面保持同一 HTTPS 域名。
3. 本机运行 `deploy/connect-local-backend.sh user@cloud-server`。云服务器 SSH 服务须允许 TCP 远程转发，但转发端口只绑定 `127.0.0.1:18001`，不得开放到公网。
4. 在云服务器验证 `curl -I https://你的域名/operator/` 返回 404，`/api/internal/submissions` 返回 404；再在网站登录、提交一段获授权的视频，确认后台任务列表出现对应记录。

本机电脑关机、断网或 SSH 隧道中断时，云端仍能显示静态页面，但登录与上传不可用。上线前需要持久化启动和监控本地后端及隧道；正式部署还应设置 Nginx 登录限流、日志保留期限、备份和上传资料访问策略。当前服务的 SQLite 和视频文件仍保存在本机，密钥为共享访问密钥，不提供逐用户账户管理。

前端使用相对 `/api/...` 地址，不在浏览器中写本地 IP、开发 Bearer 令牌或任何第三方 API 密钥。模板 3D 文件只是样式预览，来自已登记的模板 STL 简化版，并非已为用户视频生成的适配模型。
