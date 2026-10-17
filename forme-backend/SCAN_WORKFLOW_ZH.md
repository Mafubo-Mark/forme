# 点云保护套主流程与 Agent 托管

更新：2026-10-17。主流程版本 scanfit-v5-20261017。

## 操作员现在怎么做

1. 在 `/operator/` 或云端 `/admin` 的 Mac 工作流页选择真实任务，查看视频和复核帧；勾选“已检查视频纹理、环绕覆盖和标尺实际长度”，点击“开始点云重建”。
2. 点云完成后点击“复制 Agent 接手指令”，交给本机 WorkBuddy／其他 Agent。Agent 准备本单尺度、竖直坐标、上缘、下缘和螺栓复核卡。页面会显示建议参数及至少三张证据图；核对后填写一句记录，点击“确认几何并生成 STL”。
3. 本机队列连续执行全高适配、上缘裁切、下段延长、螺栓开孔、封闭性／两片干涉／孔道及截面检查，产出前片／后片／组合 STL、局部试配件、预览与 ZIP。下载后用实际设备配置切片、试配。

无需在主流程逐一选六张混元图、提交混元、粘贴形变 JSON、手动调用多次打包。原工具放在高级区供历史任务使用。当前仅开放验证过的 06 通风模板；其他模板需独立适配注册，不静默替换用户样式。

## 自动到哪里，谁负责哪些判断

- 已自动：持久任务队列；确定性拟合与布尔处理；检查与打包；重启中断记录；源视频／相机／点云／标尺／图片／模板哈希校验；云桥接回传组合 STL。
- Agent 可托管：取任务、检查输入、启动 COLMAP、标尺标注辅助、分割、姿态与孔位估计、证据准备、调用生成器、检查结果和处理失败。
- 必须有实际依据：标尺实长、无法从视频辨清的方向／边缘、真实打印与试戴。用户已有确认可继续使用，未知信息不能由模型编造。
- 托管不是一个后台付费 AI 守护进程：WorkBuddy 需要接到任务并在本机工作；几何确认后的确定性队列不依赖 WorkBuddy 持续在线。

## 成功反馈怎样保存

用户已报告新纹理视频最近交付的 V5 试戴效果很好，已在该原始目录登记 physical_fit_feedback.json，绑定该前后片的 SHA256。原 STL 保持原样。

通用生成器回放产生新的文件哈希，即使同源数据也不会自动继承“已试戴”。本轮回放验证的是软件链路能跑完，不是又完成一次实体试戴。

## Skill 和跨 Agent 入口

主入口：`../work-buddy-handoff/skills/forme-scan-workflow/SKILL.md`。

- WorkBuddy 已有 forme-cover-fit MCP 时重新连接一次，读取新工具 get_scan_workflow / approve_scan_geometry / queue_scan_cover。
- 没 MCP 的 Agent 可读同一 skill，使用后端 scripts/scan_workflow_cli.py；不必在命令中传登录密钥。
- skill 细节在 references/operation.md 与 geometry.md，含路径、接口、几何证据、配方及恢复规则。
- 日常无需把实验脚本交给 Agent 反复重写。通用实现位于 scripts/scanfit，生产对称模板位于 work-buddy-handoff/production-bases/06，不再依赖 experimental_candidates 路径。

## 云端连接

新接口仍在 `/api/internal/submissions/{id}/scan-workflow/*`，使用现有管理员代理和鉴权。云端通用 `/api/internal/*` 转发无需客户前端变动；若服务器有细粒度白名单，需允许新子路径。新路线 package URL 返回 STL ZIP，deliveryFormat=stl_zip；旧路线的 3MF 保留兼容。云端结果文件仍为组合 STL。

本机 supervisor 增加 scan 工作器；start-all.command 与 run-local.sh 均接入。发布此版只需重载本机服务。云端真实站点的最新在线交互需单独验收，不能由本地测试替代。

## 本轮验证记录

- 新通用几何生成器已用成功案例原点云真实回放到 STL_CANDIDATE_READY，输出总高375.2504mm，双片封闭，干涉检查为0，螺栓通道通过。
- 生产参考与病例数据分开；回放放在 data/scanfit_regression_run_20261017，不创建云端假订单。
- 新旧后端测试共24项通过，覆盖鉴权、输入变更、相机尺度绑定、幂等排队、失败中断、重试上限、下载和云桥接。
- skill 验证通过；后台 JavaScript 语法检查通过。

## 文件和恢复

每单：data/cover_tasks/{id}/scan_reference、scan_workflow.json、scan_candidates/{candidateId}。

失败先读 error、worker.log、logs；修复原因后重新批准，再入队生成新候选号。相同配置最多两次尝试。旧参考需要重做时显式归档，不能覆盖正在运行的输入。按单检查绑定哈希，输入变动则重新审批；绝不把不完整网格发布为ready。
