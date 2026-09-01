# F-2b 验收记录 — Python 概念统一与重复合并

- 日期：2026-09-01
- 范围：F-0 收敛方案 §F-2b 四类 Python 重复合并（provider 模式解析 / STRUCTURED_MODEL_* 读取 / 中文日期解析 / transient 代码派生）
- 纪律：一刀一验收一提交；每刀合并前后行为不变（集合/默认值/返回类型逐一核对）；agent 全量 pytest + ruff 全绿

## 总览

| # | 合并项 | 合并前 | 合并后 | 提交 |
|---|---|---|---|---|
| 1 | Provider 模式解析 | 2 处（`tool_capabilities._mode` / `places/api._resolved_provider_mode`） | 1 处（`providers/settings.resolve_provider_mode`） | `afb729c` |
| 2 | STRUCTURED_MODEL_* 读取 | 4 处（`DecisionModelConfig.from_env` / `build_extractor` / `configured_structured_extractor` / `configured_text_refiner`） | 1 处（`providers/settings.structured_model_config`） | `37d7281` |
| 3 | 中文/ISO 日期归一化 | 2 处（`dialog._parse_date_text` / `agent.normalize_trip_date`） | 1 处（`domain/shared.normalize_trip_date`） | `c37349d` |
| 4 | transient 代码派生 | 字面量集合 | 派生自 `providers/errors.TRANSIENT_CATEGORIES` | `50a860f` |

## 逐刀验收

### 刀 1：provider 模式解析 3→1（`afb729c`）

- 新增 `providers/settings.resolve_provider_mode() -> ProviderExecutionMode`（PROVIDER_MODE 优先，缺失时按 AMAP_WEB_SERVICE_KEY 判定 REAL/DEMO）
- `tool_capabilities._mode()` 改为薄转发（保留返回 `str` 契约，两个调用点不动）；`places/api._resolved_provider_mode()` 删除，调用点直接用新函数
- **刻意例外**：`WorkerSettings.resolved_provider_mode` 未合并——B12 验收要求缺省 fail-closed 为 DEMO_ONLY（不读 key），与工具/端点策略语义不同，文档已注明
- 验收：`tests/test_provider_settings.py` +8 用例；全量 **2049 passed / 42 skipped**

### 刀 2：STRUCTURED_MODEL_* 读取 4→1（`37d7281`）

- 新增 `providers/settings.structured_model_config(env=None) -> StructuredModelConfig | None`（endpoint/api_key/model 三身份字段必填，缺一即未配置；timeout=8.0s / max_retries=1 / max_input=30k 与各历史读取默认完全一致）
- 四个消费点全部改为委托；`DecisionModelConfig.__post_init__` 边界校验保留不动
- **附带修复**：`structured_model.py` 原对"显式空 knob"（`STRUCTURED_MODEL_TIMEOUT_SECONDS=""`）抛 ValueError，统一为"空→默认"（与 factory/dialog 多数派一致），非破坏性
- 验收：+7 用例；全量 **2056 passed / 42 skipped**

### 刀 3：中文/ISO 日期归一化 2→1（`c37349d`）

- `normalize_trip_date` 移入 `domain/shared.py`（超集：ISO 分隔符 `-/.年` + `前后` 后缀 + 自由文本提取），`itinerary_builder` 保留公共导出（`agent/__init__.py` 链路不变），`dialog._parse_date_text` 薄转发（返回 str 契约不变）
- **语义核对**：中文分支保留 `search`（dialog 扫描链路传带环绕文本片段，如 `"…2个人，10月1日"`，有测试依赖）；ISO 分支保持 `fullmatch`。合并初期曾误用 `fullmatch` 导致 `test_creation_rich_first_message_scans_all_slots` 失败，已定位修复
- 验收：+7 用例（覆盖分隔符集/环绕提取/前后缀/跨年/非法）；全量 **2063 passed / 42 skipped**

### 刀 4：transient 代码派生（`50a860f`）

- `providers/errors.py` 新增公开 `TRANSIENT_CATEGORIES`（TIMEOUT/NETWORK_ERROR/PROVIDER_UNAVAILABLE/RATE_LIMITED/QUOTA_EXCEEDED——quota 可重试但其 real→demo fallback 保持配置门控）；`ProviderFallbackPolicy._explicitly_allowed` 派生为 `TRANSIENT_CATEGORIES - {QUOTA_EXCEEDED}`
- `failure_policy._TRANSIENT_CODES` 裸 category 值改为派生，prefixed `PROVIDER_*` 与 planning 层 `TIMEOUT_ERROR` 保留字面量；结果集合与原来 9 元素完全一致
- 验收：+1 派生守卫（断言每个类别值均分类 TRANSIENT）；全量 **2064 passed / 42 skipped**

## 环境备注

- 四次全量回归均 42 skipped，与 E-1 基线一致；唯一 warning 为既有 qweather URL 的 Pydantic 序列化提示，非本次引入
- ruff 全绿（E/F/I/UP/B/SIM 全部规则）

## 遗留（不在本刀范围）

- `_norm_date`（dialog 内部 ISO/date 归一化）与 `normalize_trip_date` 存在部分语义重叠，但前者服务 slot 回填（str 输出），无重复读取问题，暂不合并
- WorkerSettings fail-closed 与工具/端点"按 key 自动 REAL"的语义差异为刻意设计，若未来统一需重新验证 B12 验收契约
