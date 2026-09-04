# 09 · 安全与性能审计

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 原则：只指出有证据的风险，不做无证据的"最佳实践"建议。

---

# A. 安全审计

## A1. 已核验的安全机制（正面）

| 项 | 实现 | 证据 |
|---|---|---|
| 认证 | OAuth2 Resource Server + JWT（access）+ refresh cookie | SecurityConfig.java:39-47（oauth2ResourceServer.jwt）；identity/TokenService.java |
| 令牌比较 | 常量时间比较 MessageDigest.isEqual | InternalPlanningDiagnosticsController.java:59-65 |
| CSRF | 关闭（无状态 JWT，标准做法） | SecurityConfig.java:30 |
| SQL 注入 | MyBatis 注解 SQL 全部 `#{}` 参数化，无字符串拼接 | 32 个 Mapper 全量扫描（无 concat 风险） |
| **SSRF（亮点）** | **双层**：① 域白名单校验 validate_source_url（acquisition/security.py）；② DNS 解析后校验仅允许全局公网地址（resolve_request_target，acquisition/dns.py:57-59 `not address.is_global` 拒绝）；guide 导入 HTTP 路径复用（fetching.py:98，guide_intelligence/service.py:18 注入） | 已逐层核验 |
| 攻略内容安全 | security_filter.filter_content + _check_rules（引导式内容规则过滤） | guide_intelligence/security_filter.py:101,131 |
| 分享限流 | PublicShareRateLimiter（公开分享端点限流） | share/PublicShareRateLimiter.java |
| 密钥扫描 | .gitleaks.toml + .gitleaksignore | 仓库根 |
| 预置账号 | admin@admin.com 种子账号（V42），README 明示部署前删除 | README.md:155-162 |
| 日志结构 | structured_logging.py（结构化日志）；未发现密码/token 明文日志 | worker/structured_logging.py |

## A2. 已发现的风险

| # | 风险 | 证据 | 级别 |
|---|---|---|---|
| 1 | **/api/internal/diagnostics/** 网络层公开（permitAll），仅靠 header token 自校验**：端点暴露到所有网络对端；虽用常量时间比较，但无速率限制、无来源限制；若 token 泄露即可触发 FAILED 任务重试 | SecurityConfig.java:36-37 permitAll vs InternalPlanningDiagnosticsController.java:53-61 | **P2**（本地部署默认 127.0.0.1 绑定，公网部署前必须收紧） |
| 2 | **CORS 无显式白名单**：`cors(Customizer.withDefaults())`（SecurityConfig.java:31），无 CorsConfigurationSource bean → 依赖 nginx 同源代理（web 经 /api 反代）；直接跨域访问默认被浏览器拦截（fail-closed 安全默认），但语义不明确，公网部署时应显式声明 | SecurityConfig.java:31 | P3 |
| 3 | **OCR/图片上传边界**：图片经 OCR API 传输（ocr.py:292,430 调视觉模型），未核验上传大小/内容类型限制 | compose.prod.yaml:170-175 OCR_MODEL_* | P3 / NEED_VERIFY |
| 4 | **LLM 提示注入边界（软）**：Agent 系统提示限定"只使用给定工具获取事实，不得编造营业时间/路程耗时"（graph.py:339-353），约束值需 evidence 匹配才确认（tools.py:114-131）——**主体防护到位**；但攻略正文（不可信来源）会进入结构化抽取 LLM（structured_model.py:176），抽取提示是否隔离用户内容为数据而非指令，未在代码内显式声明 | graph.py:339-353 / structured_model.py:176 | P3 / OBSERVATION |
| 5 | **/actuator/prometheus permitAll**（SecurityConfig.java:36）：指标端点公网可读（含任务计数等非敏感指标）；依赖网络绑定 | 同上 | P3 |
| 6 | 预置 admin 种子账号：若未删除即公网部署 = 已知口令入口 | README.md:155-162 | P3（文档已警示） |

## A3. 安全判定
**整体安全姿态良好**：JWT + 参数化 SQL + SSRF 双层防护 + 内容过滤 + 限流 + gitleaks。最大风险是"内部诊断端点的网络暴露 + 无速率限制"（P2）与"CORS 语义隐晦"（P3）。未发现硬编码密钥（gitleaks 已扫描）；.env 中的 JWT_SECRET 等为环境注入，符合预期。

---

# B. 性能审计

## B1. Top Performance Risks（带证据）

| # | 风险 | 证据 | 级别 |
|---|---|---|---|
| 1 | **Java 行程读取 N+1（明确存在）**：`toItineraryResponse`（ItineraryService.java:366-376）先 findDays，再对每天 findActivities + findTransitLegs → 1 次读取 ≈ 1+N×2 次查询；`readEditableItinerary`（:424-433）、`toKnowledgeResponse`（:806-828 findKnowledge→findKnowledgeCitations）、`ItineraryVersionService.readOwned`（:252-289）同型 | ItineraryService.java:366-376 | **P1**（行程详情每次打开 10-30 次 DB 往返） |
| 2 | **版本快照逐行 insert**：`ItineraryVersionService.copyVersion`（:207-243）、`ItineraryService.persistEditedVersion`（:713-734）行级循环插入（day/activity/transit_leg 每行一条 SQL） | ItineraryVersionService.java:207-243 | P2（编辑提交 O(n) 往返，中等行程可接受，大行程慢） |
| 3 | **Python 同步 DB 无连接池**：persistence.py 经 asyncio.to_thread 执行同步 DB 操作，每次开新连接（无池复用） | agent/persistence.py（agent 审计 §6.9） | P2 |
| 4 | **DLQ 无消费者 → 死消息无限堆积**：占位消息在 broker 上只增不减（06 §5） | RabbitMessagingConfiguration.java:95 | P1（可靠性>性能） |
| 5 | 外部依赖延迟：STRUCTURED_MODEL_TIMEOUT=8s / OCR=15s（compose.prod.yaml:167,173）——Agent 决策受 LLM 延迟影响；已有超时与降级（graph.py:293-300） | compose.prod.yaml:167-173 | P3（设计内） |
| 6 | Provider 重试窗口：PROVIDER_RETRY_MAX_ELAPSED_SECONDS=5s（compose.prod.yaml:103）——AMap 失败时规划任务最多叠加 ~5s+ 重试延迟，可接受 | compose.prod.yaml:103 | P3 |
| 7 | OR-Tools 未使用 → "全局优化"类性能无从谈起（04 已判）：非风险而是能力缺失 | pyproject.toml:12 | — |

## B2. 性能判定
**唯一明确且可量化的性能缺陷是 Java 行程读取的 N+1**（P1）：这是每次打开行程详情/版本对比都会触发的稳定开销，应在 3.0 用批量查询（WHERE day_id IN (...)）或 join 修复。其余为中等/低风险。

---

# C. 安全+性能综合结论

- 保留：SSRF 双层防护、参数化 SQL、常量时间比较、结构化日志、分享限流 —— 均为高质量实现。
- 优先修：内部诊断端点网络暴露（P2）、行程读取 N+1（P1）。
- 3.0 关注：CORS 显式化、OCR 上传边界、prompt 注入边界文档化。
