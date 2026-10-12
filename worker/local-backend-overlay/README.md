# Mac 本机后端远程管理适配

这两份文件对应 Mac `forme-backend` 的 `operator/js/app.js` 与 `run-local.sh`。当前 Mac 工作目录已应用；在另一台 Mac 重建服务时，先备份原文件，再将本目录中的文件复制到相同相对路径。`operator/js/app.js` 在 `/api/admin/operator/` 下使用云端管理员 Cookie，不把本机 Bearer 令牌交给浏览器；本地 `/operator/` 仍使用开发令牌。`run-local.sh` 从私有 `.local-operator-token` 读取稳定令牌，供云端代理使用。

`.local-operator-token` 必须写入本机 `forme-backend/.gitignore`，权限设为 600，内容与云端私有配置的 `local_operator_token` 一致。不得将其放进本仓库、网站静态目录或聊天。更多配置与验收见 [远程管理说明](../../deploy/REMOTE_OPERATOR_ZH.md)。
