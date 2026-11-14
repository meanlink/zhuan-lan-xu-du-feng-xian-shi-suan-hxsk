# 专栏续读风险试算

分类与阈值选择的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18207；后端文档 http://localhost:19207/docs；数据库宿主端口 17707。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed/cancelled；执行记录 JobAttempt 状态：running/completed/failed/interrupted/cancelled。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 并发领取、恢复与取消
- 计算进程以独立 `WORKER_ID` 运行，通过数据库条件更新原子领取 `queued` 任务；同一试验只会有一个进程领到，重复领取或已取消的任务直接放弃。
- 领取时写入领取令牌（claim_token）、租约（`JOB_LEASE_SECONDS`，默认 60 秒）和一条 JobAttempt。恢复后的重试**沿用首次领取的样本快照与参数**，不重新读取可能已变化的批次。
- 执行期间持续续租；新进程启动不会按「running」一刀切重排，只回收租约已过期（原进程已失联）的试验，**不会重排其他计算进程仍在执行的试验**。
- 发布结果必须匹配当前领取令牌且任务仍在运行。旧进程迟到的成功或失败一律丢弃并记审计 `job.stale_result_ignored`，不覆盖恢复后的结果。
- 编辑（admin/analyst）可取消排队中或运行中的试验。取消与完成并发时由数据库条件更新裁定先落定者，后到的一方收到 409，不改写既有状态。
- 结果页可查每次执行记录（领取进程、状态、是否发布、时间）；「生效」的只有唯一一次完成记录。
- 未完成、失败与已取消试验不能批准，也不参与简报分发；`reports.create` 与 `deliver` 都按生效结果校验。


## 环境变量与 Docker
COMPOSE_PROJECT_NAME=reader-risk；FRONTEND_PORT=18207；BACKEND_PORT=19207；DB_PORT=17707；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true；JOB_LEASE_SECONDS 默认 60。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
需要加开计算进程时执行 `docker compose up -d --scale worker=2`；worker 服务不设固定 container_name，各进程经租约协调，不会重排彼此在跑的试验。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1008/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
