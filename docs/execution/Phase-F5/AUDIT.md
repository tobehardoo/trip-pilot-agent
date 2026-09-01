# F-5 最终发布就绪审计（AUDIT ONLY）

- 审计起点：`F4-accepted`（`e0ac7a3`）——F-4 验收通过后的最终 HEAD
- 模式：**AUDIT ONLY**——未修改任何生产代码；全部结论基于当前 HEAD 实扫/实测
- 纪律：不用测试数量代替真实验证、不用 README 代替代码证据、不因用了 LangGraph/LLM Tool/Evaluation/Docker Compose 就判定真实

## 1. 真实性核验（Evidence First）

| 维度 | 证据 | 结论 |
|---|---|---|
| 规划主链路 | `infrastructure/amap/planning_provider.py` 真实 AMap 实现（B18-A 全关键词召回 / B19-C 交通分层 / P2-1 预算包络 / R12 单调清扫），F-4.1 拆分后 Facade + 6 协作者；`test_provider_modes.py` 覆盖 DEMO/REAL/FALLBACK 三模式 | ✅ 真实 |
| Agent 编排 | `agent/graph.py` 有界 LangGraph 编排 + E-1 反射预算守卫；决策策略（DIRECT/RETRIEVE/CLARIFY/REPLAN/RETRY）均有实际决策点 | ✅ 真实 |
| REPLAN 可达性（D-6 关闭） | 双路径：① Agent 内 `strategy="REPLAN"` ×3 均伴随 `update_constraints` 工具调用或提问循环（graph.py:219/244/337）+ E-1 无终止守卫（graph.py:776）；② 外部 `process_planning_replan`（processor.py:116）→ `provider.replan` → `LocalReplanningProvider`（replan_service.py:46）。"tools.py 无 replan 工具"是误读——REPLAN 不依赖独立工具 | ✅ 语义完整 |
| 状态机（D-5 复查） | 写入点 QUEUED/RUNNING/WAITING_USER/SUCCEEDED/FAILED/CANCELLED；CREATED/RETRYING/CANCELLING 为预留中间态（查询条件 + 语义注释引用），收紧 CHECK 需不可逆 migration | ✅ 保留合理 |
| Web 功能 | 29 测试文件 / 307 用例全绿；workspace 新 UI（src/workspace/）按 Phase 2 计划 REPLACE 旧 UI | ✅ 真实 |
| Real browser E2E | `apps/web/e2e/qa-real-chain.spec.ts`：**零 mock 真实栈链路**（Web→Java→MQ→Python→完成→真实持久化渲染）；另有 6 个 E2E spec；ci.yml:93-94 有 `playwright install + test:e2e` 步骤 | ✅ 声明有脚本+CI 支撑 |
| 部署就绪 | compose.prod.yaml 9 服务 + 卷（F-3d 已 `config --quiet` 验证）；Java 测试实测 42 migrations 全部可应用；预置 admin 账号有部署前删除/改密指引（README:162） | ✅ 就绪 |
| 依赖真实性 | pyproject 无 ortools（F-4.5 已修 10 处文档失实）；fastapi==0.116.1 / langgraph>=1.2.11 实际依赖 | ✅ 一致 |

## 2. 三端测试（F-4 验收门实测，与基线一致）

| 端 | 结果 |
|---|---|
| Python | 2051 passed / 42 skipped（skip 原因：KNOWLEDGE_TEST_DATABASE_URL 未配置等环境条件） |
| Java | 626 Tests / 0 Fail / 0 Error / 0 Skip |
| Web | 29 files / 307 passed |

## 3. 审计发现（P 分级，均未修改——AUDIT ONLY）

| 级别 | 发现 | 证据 | 建议 |
|---|---|---|---|
| **P1** | README "Current release validation" 段落**整体过期**（v1.0 收口快照）：Python **1717**→实际 2051、Java **558**→626、Web **446**→307；skip 描述"3 个可选真实 AMap 单测"与实际不符（实际为数据库配置未设置） | README.md:169-177 vs 本审计实测 | Release Freeze 前更新该段落为当前数字（F-5 后首个允许动作） |
| P2 | .dockerignore 缺 `**/__pycache__`、`**/.mypy_cache`、`**/.ruff_cache`、`docs/`、`test-results/` 等（build context 偏大） | .dockerignore 全文 7 行 | 下轮维护时扩列（非发布阻塞） |
| P3 | D-12 API_ONLY 端点（InternalPlanningDiagnosticsController /planning-failures、/retries；HealthController /health）无 UI 消费 | 控制器实扫 | 内部运维用途，保留记录在案 |
| P3 | Web coverage 95.51%（README 声明）未在本轮实测复核（vitest run 默认不带 coverage 报告） | — | 不作为缺陷，仅记录未复核 |

## 4. 十分制评分

**8 / 10**

得分构成：
- 代码真实性 +5（规划/Agent/Web/E2E/部署全部有代码证据与运行验证，无"README 冒充代码"）
- 测试与 CI 完备 +2（三端全绿、E2E 在 CI、migration 实测可跑）
- 文档/发布声明 −1（README validation 段落过期数字，P1）
- 部署打磨 −0.5（.dockerignore 可扩列，P2）
- 无 P0 问题、无虚构技术栈、无失实核心声明（F-4.5 已清 OR-Tools）→ 不扣分

## 5. Release Decision

**A 档——可进入 Release Freeze（附带 1 个前置动作）**

- 代码与测试：完整软件发布就绪（本地优先运行、未部署公网，README:185 限定诚实）
- **前置动作（冻结期间唯一必做）**：更新 README "Current release validation" 段落为当前三端数字与 skip 原因（P1）
- 动作指引：README 更新后可：Release Freeze → Demo/简历引用（可用 2051/626/307 + 零 mock E2E 作为可辩护证据）
- 限制记录：D-5 状态机预留值、D-12 内部端点、.dockerignore 扩列——作为已知限制记录在案，不影响发布

## 6. Checkpoint

- F-5 审计完成（AUDIT ONLY，零生产代码改动）
- 审计起点 `F4-accepted`（e0ac7a3）保持为发布候选 HEAD
- 唯一待办：README validation 数字更新（P1，Release Freeze 前置）
