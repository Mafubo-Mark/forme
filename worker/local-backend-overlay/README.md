# Mac 本机后端同步文件

本目录保存已经在当前 Mac `forme-backend` 工作目录应用的文件，用于重建或核对。它是覆盖包，**不是完整后端仓库**。将文件复制到原后端目录的相同相对路径后，运行原有依赖安装，再双击 `start-all.command`。

- `start-all.command`、`stop-all.command`、`start-demo.command`、`start-bridge.command`、`start-tunnel.command`：本机启动与停止。
- `scripts/run_all.py`：监管 API、视频质检、COLMAP、混元结果工作器、云桥接与 SSH 隧道。
- `scripts/add_stl_delivery.py`、`scripts/package_cover_candidate.py`：前后片 STL 和组合 STL 的打包、哈希及质量记录。
- `src/forme_backend/api.py`、`production_flow.py`、`cloud_bridge.py`：STL 下载接口、工作流状态和云端 STL 回传。
- `operator/js/app.js`：远程操作面板的 STL 链接及云端分段下载。
- `run-local.sh`：单独开发启动时的本机令牌与工具路径设置。

当前一键运行方式和 STL 限制见 [ONE_CLICK_STL_ZH.md](ONE_CLICK_STL_ZH.md)。`.local-operator-token`、`.cloud-bridge.json`、`SecretKey.csv`、SSH 私钥和 `data/` 均为本机私有文件，不在此目录，也不得提交到 GitHub。远程管理认证配置见 [REMOTE_OPERATOR_ZH.md](../../deploy/REMOTE_OPERATOR_ZH.md)。
