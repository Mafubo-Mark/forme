# Forme 部署与数据库使用说明

日期：2026 年 10 月 12 日（香港时间）

> 当前状态：功能实现和本地验收已完成，19.43 MB 部署包已上传到 `/www/forme-staging/forme-deploy.tar.gz`。宝塔终端重连后黑屏，腾讯云备用终端也未返回可用命令输出；尚未确认服务器执行部署。新数据库、正式 HTTPS、服务与每日备份尚未创建／启用。原网站与原有数据库未修改。下文服务器目录、数据库查看和备份说明是待执行的部署方案，不是上线完成声明。
>
> 待用户操作：确认接受 Let's Encrypt 订户协议；把 Safari 的宝塔／OrcaTerm 页面切到前台并保持可见，或提供可用 SSH 连接方式。管理员 `forme / 123456` 和新增专用 MySQL 账号已经得到上线授权，不再重复请求该授权。

## 1. 网站与后台

- 主网站：`https://my-robot-home.com/`
- 邮箱注册：`https://my-robot-home.com/register.html`
- 用户登录：`https://my-robot-home.com/login.html`，支持邮箱或账号登录。
- 管理平台：主网站页脚的小按钮“管理平台”，或直接进入 `https://my-robot-home.com/admin.html`。
- 管理员账号：`forme`；密码：`123456`，按要求固定在服务端认证逻辑中。网页源码不包含管理员密码，用户账号不能访问管理接口。该密码容易猜测，网站有登录限速，但固定弱密码仍存在实际风险。

部署后，用户数据将保存到腾讯云服务器的 MySQL 中。本地测试已确认：用户退出、浏览器关闭或换设备后，重新登录仍可查看自己的设计和订单。

## 2. 新增业务流程

1. 用户输入邮箱、账号和至少 8 位密码注册。姓名选填，账号及邮箱不能重复。当前支持邮箱作为登录身份，未配置邮箱验证码、验证邮件或找回密码邮件，也不会把未验证邮箱标为已验证。
2. 用户上传 MP4／MOV／WebM 视频，选择七款模板、预设／自定义颜色、材料，并保存灵感文字和可选图片。
3. 系统保存视频归属、大小、SHA-256、设计选项、提交时间和建模历史，初始状态为等待人工审核。
4. 管理员选择用户，下载视频，更新审核结果及建模阶段，留下用户可见备注，并上传实际生成的 GLB／STL／3MF 模型文件。
5. 管理员将设计设置为“已完成”并填写港币报价后，用户才能下单。用户填收件人、电话、地区、城市／区、详细地址及配送备注。订单金额由服务器读取管理员报价，不能由用户在浏览器修改。
6. 用户按 Forme 另行确认的真实收款信息付款，再提交付款方式、交易参考编号及图片／PDF 凭证。提交凭证不会自动扣款，也不会自动把订单标为已付款。
7. 管理员核对收款后确认或拒绝付款，审核记录保存到数据库。已确认付款后，才能进入制作和发货流程。
8. 管理员填写物流公司、追踪号，依次更新制作、寄出、送达。用户在已寄出的订单上点击“确认收货”，系统保存确认时间。

**边界：**GitHub 仓库只包含用户前端及建模交接文档，原本的 FastAPI／COLMAP／Blender／混元建模工作器没有包含在此仓库。这次补上云端账号、持久化提交、人工建模管理和交易记录链路；自动视频重建、保护套几何适配、真实支付网关及物流公司实时接口没有被虚构成已接通。现有 3D 模板是样式预览，实际模型由管理员上传。部署不依赖 Mac 保持开机，人工建模可以稍后处理。

## 3. 数据库存了什么

计划创建的数据库名为 **`forme_production`**，应用数据库账号为 **`forme_app`**。仅连接服务器本机，并且只授予这一数据库的权限。服务器原有 `forme_db` 保留。

| 表名 | 保存内容 |
| --- | --- |
| `users` | 用户 ID、唯一邮箱、唯一账号、密码哈希、姓名、电话、注册时间 |
| `sessions` | 用户／管理员会话令牌的哈希、归属、角色、到期时间 |
| `uploads` | 视频归属、原始文件名、类型、大小、SHA-256、上传状态、时间 |
| `submissions` | 用户、视频、模板、颜色、材料、灵感文字／图片、模型文件、建模状态、报价、备注、创建／更新时间 |
| `modeling_events` | 每次建模／审核状态变化、阶段、备注、操作者和时间 |
| `orders` | 唯一订单号、用户、设计、确定的金额、付款状态、订单状态、时间 |
| `payments` | 订单、付款方式、交易编号、凭证文件、审核结果／备注、提交及审核时间 |
| `deliveries` | 收件人、电话、地址、地区／区、配送备注、物流公司、追踪号、发货／送达／用户确认收货时间 |
| `audit_events` | 注册、设计提交、付款提交／审核、模型上传、配送更新、确认收货等操作记录 |
| `rate_limits` | 登录、注册、上传频率限制计数 |

密码列是 `password_hash`，使用带独立随机盐的 scrypt 哈希。数据库和管理平台都不会显示用户原始密码；验证登录时对输入密码重新计算哈希并比较。管理员无需也不能“查看用户密码”。

视频、灵感图、付款凭证和实际模型不是塞进 MySQL 大字段，而是放在私有文件目录，数据库保存引用。下载先检查登录身份和归属。用户 A 不能访问用户 B 的文件或订单。

## 4. 如何在宝塔查看数据库

1. 打开你已经登录的宝塔面板，点击左侧 **数据库**。
2. 在 MySQL 数据库列表中找 **`forme_production`**；备注是 `Forme - my-robot-home.com`，用户名 `forme_app`。不要误选原有 `forme_db`。
3. 管理网站数据时，首选主网站的 **管理平台**：登录后左侧为用户列表，可以搜索邮箱或账号；点击用户，右侧可看设计历史、下载视频／模型、查看付款凭证和收件信息。
4. 如果要查看原始数据，数据库行的 **管理** 一般会打开 phpMyAdmin。以该数据库用户登录，然后在左侧选择 `forme_production`，点击需要的表，再点击 **浏览**。数据库密码可在宝塔该数据库行的密码查看入口读取，或从服务器私有配置中读取；报告不复制这个随机密码。
5. 如果当前宝塔没有安装 phpMyAdmin，仍可用管理平台浏览业务数据，也可在宝塔终端通过应用环境运行只读查询；不需要为查看数据把 MySQL 端口开放给公网。

常用只读 SQL：

```sql
SELECT id, email, username, full_name, phone, created_at
FROM users ORDER BY id DESC;

SELECT s.id, u.email, s.template_id, s.color, s.material,
       s.status, s.model_stage, s.quote_hkd, s.created_at
FROM submissions s JOIN users u ON u.id = s.user_id
ORDER BY s.created_at DESC;

SELECT o.order_number, u.email, o.amount_hkd,
       o.payment_status, o.order_status, o.created_at
FROM orders o JOIN users u ON u.id = o.user_id
ORDER BY o.created_at DESC;

SELECT o.order_number, d.recipient_name, d.recipient_phone,
       d.address_line, d.carrier, d.tracking_number, d.confirmed_at
FROM deliveries d JOIN orders o ON o.id = d.order_id;
```

数据库 ID 关联：`users.id → submissions.user_id / orders.user_id`；`submissions.id → modeling_events.submission_id / orders.submission_id`；`orders.id → payments.order_id / deliveries.order_id`。

## 5. 数据怎么部署到腾讯云、怎么备份

部署脚本将让新增的云端 Python 服务在腾讯云服务器创建独立 MySQL 数据库和表。网页与 `/api/` 接口走同一个域名，Nginx 把接口转发到服务器本机的后端。数据库和私有资料在腾讯云服务器上持续保存，页面重新部署不清空数据库。

| 内容 | 服务器位置 |
| --- | --- |
| 网站公开页面／3D 模板 | `/www/wwwroot/my-robot-home.com/` |
| 私有后端源码与 Python 环境 | `/www/forme-service/` |
| 私有连接配置（包含随机数据库密码） | `/www/forme-service/config.json`，权限 600 |
| 视频、灵感图、付款凭证、实际模型 | `/www/forme-service/private-data/` |
| MySQL 逻辑数据库 | `forme_production`；物理目录以 MySQL 的 `datadir` 为准 |
| 新部署前的原网站备份 | `/www/backup/forme-deployment/日期时间/` |
| 每日业务备份 | `/www/backup/database/forme_production/` |
| 本站 Nginx 配置 | `/www/server/panel/vhost/nginx/html_my-robot-home.com.conf` |

部署完成后，计划每日香港时间 **03:30** 由 `forme-backup.timer` 触发备份（当前尚未启用）：

- 使用 MySQL `mysqldump --single-transaction` 导出当前数据库，保留各表、索引和业务记录。
- 同一备份包收录私有视频、凭证、图片、模型、服务代码和连接配置。
- `manifest.json` 保存导出文件及私有资料的 SHA-256，便于检查文件完整性。
- 完成后保存为 `forme-YYYYMMDDTHHMMSSZ.tar.gz`，文件名使用 UTC（比香港时间早 8 小时）。
- 备份在公开网站目录之外，只有服务器管理员可以读取。包里包含用户资料和数据库连接密码，应作为私有资料保管。
- 当前策略保留所有已完成备份，未自动删除旧副本。视频较多时要留意磁盘空间。

**“腾讯云上保存”与“独立异地备份”有区别：**这里的数据库和备份包都位于这台腾讯云服务器的磁盘，未配置腾讯云 COS／独立云数据库／跨服务器复制。没有可用 COS 存储桶授权时，不能声称已做 COS 备份。整机磁盘故障或服务器被删除仍可能影响同机备份，应在宝塔文件管理下载备份到另一设备，或之后配置独立私有 COS 存储桶。

在宝塔左侧 **文件** 中进入 `/www/backup/database/forme_production/` 即可找到备份包，选择需要的包下载。也可以在终端运行：

```sh
systemctl start forme-backup.service
systemctl status forme-backup.timer
journalctl -u forme-backup.service -n 30 --no-pager
```

定时任务使用 systemd，不会自动出现在宝塔“计划任务”列表；以上命令能查看启用状态和执行结果。

## 6. 恢复与维护

恢复前先做当前数据备份，并停止 `forme-cloud` 服务防止新数据写入。解压所选私有备份包，确认 `database.sql` 和 `manifest.json` 存在，验证 SHA-256 后，通过宝塔数据库“导入”把 SQL 导入 **正确的 `forme_production`**。恢复私有文件到 `/www/forme-service/private-data/`，保持服务账号所有权和严格权限；再启动服务，验证健康接口、用户历史和文件下载。恢复操作会覆盖当前数据，应由管理员明确选择目标备份后执行。

```sh
systemctl status forme-cloud.service
systemctl restart forme-cloud.service
journalctl -u forme-cloud.service -n 50 --no-pager
curl -fsS http://127.0.0.1:18086/api/health
```

后端只监听 `127.0.0.1:18086`，不会新增公网建模服务端口。服务开机自启、异常自动重启。登录 Cookie 使用 HttpOnly、Secure、SameSite；接口检查跨站请求来源。密码不写浏览器存储，私有文件不放公开网站目录。

此仓库和源码交付包不含生产数据库随机密码、现有数据库密码、用户上传内容或登录 Cookie。主网站与管理平台的账号是两套身份，普通用户登录不会获得管理权限。

## 7. 验收记录

- 本地集成测试：注册、重复邮箱／账号拒绝、密码哈希、登录／登出、资料保存、视频上传及大小校验、设计历史、管理员报价、模型上传、订单金额防篡改、付款审核、物流流转、用户确认收货。
- 权限测试：另一用户不能访问设计详情、原视频、付款凭证和订单；普通用户不能访问管理员接口；跨站修改被拒绝。
- 本地数据库恢复：用数据库备份恢复用户和已收货订单记录。
- 浏览器：实际提交注册表单后跳转至账户页，管理平台登录及用户列表通过验证。
- 公网原网站仍返回原首页，新增管理平台与数据库尚未上线。
- 云端证书、数据库表、服务启动、自动备份、原网站备份及公网流程：未验收；需终端恢复并执行部署后填写实际结果。

本地验收界面（所有内容为测试数据）：

![管理平台本地验收预览](管理平台本地验收预览.jpg)
