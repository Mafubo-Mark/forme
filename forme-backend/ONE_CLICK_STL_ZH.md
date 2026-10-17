# Mac 后台一键启动与 STL 交付

## 一键启动

双击 [start-all.command](start-all.command)。它在一个终端窗口中启动并监管本机 API、视频质检、COLMAP、混元结果工作器、云端任务同步和私有 SSH 隧道。不要关闭该终端窗口；组件异常退出时会自动重启。重复双击不会启动第二套进程。

- 本机面板：`http://127.0.0.1:8001/operator/`
- 云端管理：`https://forme.agents-time.com/admin`
- 日志：`data/service-logs/`，按 `api`、`media`、`colmap`、`hunyuan`、`bridge`、`tunnel` 分开保存。
- 停止：双击 [stop-all.command](stop-all.command)，或在启动窗口按 Ctrl+C。

启动前保留 `.venv/`、`.local-operator-token`、`.cloud-bridge.json` 和 `data/forme-cloud-tunnel-ed25519`；混元密钥文件位于 `/Users/emilia/Downloads/SecretKey.csv` 时才启动混元结果工作器。脚本不会把这些凭据打印到日志。Mac 休眠、关机或终端关闭后，建模端不可用；云端登录、上传和查进度仍由云服务器运行。

曾尝试使用 macOS `launchd` 后台服务，但该服务进程无法读取当前外置工作盘上的项目脚本，因此改为双击终端窗口的监管方式。此方式已在本机实际启动并验收。

## STL 输出

数字试样候选完成后，面板提供：

1. `cover_front.stl`：前片，毫米；
2. `cover_rear.stl`：后片，毫米；
3. `cover_trial_mm.stl`：两片保留装配坐标的组合 STL，方便云端作为单个文件归档；
4. `cover_trial_mm.3mf`：辅助切片包，仍保留以便复核。

云桥接优先回传组合 STL；云端管理员可下载，客户在操作员审查发布前仍看不到模型。组合 STL 含两个网格壳，未做打印床摆放。打印时建议分别导入前、后片 STL，在目标切片软件中分件、定方向和检查支撑、薄壁与尺寸。

每个文件的 SHA-256 记录在 `data/cover_tasks/<任务 ID>/candidate_print_trial/<候选 ID>/build_report.json`。当前演示任务 `d4ca3886da744c19a2adaa212bcfb9d4` 使用同一拍摄素材的历史试样复用；这只是文件链路验证，本次新点云与混元白模尚未重新拟合保护套。`manufacturingApproved=false`，不能当作佩戴适配或打印成品批准。
