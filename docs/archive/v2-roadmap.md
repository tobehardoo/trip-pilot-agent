# TripPilot V2.0 方针与范围

> 版本主题：**可观测、可交付、可持续使用的智能旅行规划产品**
>
> 文档状态：规划基线。本文描述目标和验收条件，不表示其中 V2 功能已经实现。

## 1. 版本定位

V1.3 已验证结构化约束、多日异步规划、真实与 Demo Provider、可信城市情报、不可变
行程版本、局部重规划和回滚等核心链路。V2.0 不以增加 Agent、Provider 或城市数量为主，
而是完成以下闭环：

1. 现有能力可稳定运行、可恢复并可诊断。
2. 新用户可以独立完成一次旅行规划和调整。
3. 成果可分享、可导出，并具备公开部署的基本条件。

V2 的核心用户旅程为：

```text
注册并创建旅行
  -> 填写约束或选择城市模板
  -> 同步可信城市情报并导入个人攻略
  -> 创建规划任务并查看真实执行阶段
  -> 查看带地图、交通、费用和事实依据的行程
  -> 编辑活动或交通方式，确认后生成新版本
  -> 比较或回滚版本
  -> 分享只读版本，或导出 PDF / 日历
  -> 在 Provider 故障或消息重试后恢复任务状态
```

## 2. 当前基线与表述规则

当前仓库中的 V1.3 事实和外部环境限制记录在
[V1.3 系统状态与交接](28-current-system-status-and-v1-4-plan.md) 和
[V1.3 发布验收清单](release-checklist.md)。其中真实高德 Web JS 底图授权仍需由部署者在
实际域名和凭据环境中完成验证。

本文及相关 V2 文档使用以下规则：

- "当前" 只描述已由代码、测试或验收记录证实的能力。
- "目标"、"应"、"必须" 均为 V2 待交付要求，不能据此宣称已完成。
- 只有迁移、契约、用例、前端交互、自动化测试和验收证据都完成后，交付项才能勾选。
- 外部 Provider 的真实验收与 Demo 验收分开记录；Demo 数据不得表现为实时结果。

## 3. 开发原则与边界

### 3.1 先收口，再扩展

在 V2 发布前，不新增 Agent、微服务、数据库、消息中间件、大规模城市覆盖、新攻略平台或
大型爬虫系统。优先让当前能力形成稳定闭环。

### 3.2 保持三服务 Monorepo

继续使用 Vue Web、Spring Boot Travel Server 和 Python Agent Service。V2 只收敛各层职责，
不为形式拆分用户、地图、攻略或版本服务，也不引入 Kubernetes、服务网格或完整 CQRS。

### 3.3 纵向切片与契约优先

每项能力必须按以下顺序形成可验证链路：

```text
数据模型 -> 数据库迁移 -> 后端用例 -> contracts/ 协议
-> 前端交互 -> 单元/集成测试 -> 浏览器 E2E -> 发布证据
```

`contracts/` 是 Java、Python 和 TypeScript 跨服务消息的唯一来源。每个活跃 Schema 至少有
`$id`、`schemaVersion`、必填字段、枚举、时间格式、示例和兼容性说明，并在 CI 中接受
Schema、Java 序列化、Python 解析、TypeScript 类型和示例一致性校验。

### 3.4 真实模式与 Demo 模式分离

页面和日志必须能区分真实 Provider、缓存、过期快照、Demo Provider 与估算降级。Provider
失败时可以降级，但不得以硬编码结果或模拟进度伪装真实调用成功。

## 4. P0：架构与可靠性闭环

P0 是 V2 的发布前提；各条目的证据和状态见
[V2 交付与验收清单](v2-delivery-checklist.md)。

### P0-0 V1.3 基线收口

完成分支审查、全量 Java/Python/Web 测试、Flyway 迁移、消息契约、Compose 验收、文档一致性
检查和稳定标签。构建产物、失效 TODO、重复实现和临时代码不得进入基线。外部底图授权作为
明确的部署验收项记录，不得被代码侧降级测试替代。

### P0-1 前端架构收敛

在不重写前端的前提下引入 Vue Router 和 Pinia。最终 `App.vue` 仅保留应用壳、`RouterView`、
全局通知、会话初始化和全局错误边界，不再承担业务 API 编排。

目标路由：

```text
/login
/register
/trips
/trips/new
/trips/:tripId
/trips/:tripId/plan
/trips/:tripId/versions
/share/:shareToken
```

建议按领域维护 `authStore`、`tripStore`、`planningStore`、`itineraryStore`、
`cityIntelligenceStore` 和 `notificationStore`，并将页面编排收敛为
`useCreateTrip`、`usePlanningTask`、`useTripEditing`、`useItineraryVersions`、
`useCityIntelligence`、`useSseConnection` 等 composable。保留既有的请求竞态保护和
SSE `Last-Event-ID` 恢复能力。

退出条件：页面拥有明确路由且刷新可恢复，核心状态不经深层 props/emits 传递，单一页面组件
原则上不超过约 400 行，并提供统一 Dialog、空状态、错误边界和关键页面骨架屏。

### P0-2 真实规划进度

Python Worker 必须发布真实阶段事件，Java 消费并持久化关键状态，再通过 SSE 输出给 Web。
前端只能展示服务端进度，不能自行生成百分比。

标准阶段：

```text
TASK_ACCEPTED
CONTEXT_VALIDATING
CITY_FACTS_LOADING
POI_RECALLING
KNOWLEDGE_RETRIEVING
CANDIDATES_RANKING
ROUTES_CALCULATING
CONSTRAINTS_SOLVING
RESULT_EXPLAINING
RESULT_PERSISTING
COMPLETED
```

每个事件至少包含 `stage`、`progress`、`message`、`occurredAt`、`taskId`、`sequence`，并可
附带统计信息。重放和重复事件不能使进度倒退；取消后停止更新；失败必须说明失败阶段和可理解
原因。Demo 模式使用相同契约。页面刷新或 SSE 重连后恢复最后状态，而不是重新播放动画。

### P0-3 通勤数据写回闭环

交通段成为正式行程结构，而不是前端临时估算。用户对相邻活动可选择步行、公共交通、打车/
驾车或自动推荐；确认前先查看影响预览，确认后创建新的不可变行程版本。

目标 `TransitLeg` 属性为：

```text
fromActivityId, toActivityId, mode, distanceMeters, durationMinutes,
estimatedCost, provider, providerRouteId, calculatedAt, stale
```

后端需要重新计算距离、时长、费用、出发时间、后续冲突、日交通时间、日预算和局部重规划
需求。路线 Provider 失败时允许使用估算，但必须带明确估算/过期标识，并支持 Provider 恢复后
重新核验。版本差异必须能显示通勤变化。

### P0-4 四条可重复 E2E 用户旅程

浏览器级 E2E 覆盖以下旅程，并使用独立测试数据库和受控 Demo Provider：

1. 注册、创建广州三日旅行、修改约束、创建规划、查看阶段、结果、地图和事实影响。
2. 创建北京旅行、导入攻略、同步情报、验证预约或天气事实进入结果。
3. 生成上海行程、编辑活动、切换交通、局部重规划、比较差异并回滚。
4. 规划过程中模拟 SSE 中断、重连、重复完成事件与 Java 幂等消费，页面只展示一个最终版本。

真实 Provider 验收是可选的独立门禁；核心 E2E 不依赖外部高德稳定性，并在 CI 中执行。

### P0-5 可观测性与故障诊断

最小生产可观测性包括规划成功/失败/取消率、平均与 P95 耗时、阶段耗时、不可行比例、
RabbitMQ 积压/重试/死信/重复、Provider 成功率/超时/限流/缓存命中/Demo 降级，以及城市情报
的有效/过期/冲突事实和刷新成功率。

关键日志统一携带 `traceId`、`tripId`、`taskId`、非敏感用户标识、`messageId` 和 `provider`。
不得记录 Token、Cookie、模型或高德 Key、完整攻略正文或未脱敏邮箱。应提供受保护的诊断入口，
用于查看失败任务、失败阶段、Provider 错误、消息重试、旧快照，并仅对安全可重试任务执行
幂等重试。

## 5. P1：使用与分发闭环

P1 在 P0 完成后实施：

- 旅行列表支持后端分页、目的地/日期/状态筛选、最近修改排序、空状态和删除或归档。
- 只读分享链接固定指向不可变行程版本，支持创建、撤销、有效期和匿名只读；Token 使用高熵
  随机值，数据库只保存摘要，并具备限流、过期、撤销和版本隔离。
- PDF 导出包含基本信息、每日行程、时间、地址、交通、费用、注意事项、事实摘要与生成时间；
  优先保证中文字体、分页、打印和内部字段隔离。
- ICS 导出将活动作为具有明确时区的日历事件，正确区分全日与定时事件。
- 手机浏览器优先支持行程时间轴、地图/路线概览、活动详情、今日行程、地址复制、来源提示、
  交通段和加载/错误状态；不建设完整 PWA、离线缓存或后台推送。

## 6. P2 与明确非目标

P0、P1 全部完成后才评估更丰富城市模板、来源管理 UI、多主题、多方案对比、预算/节奏模式、
更细 POI 过滤、结果评分、用户反馈和使用统计。

V2 明确不做国际化、多人实时协作、支付和真实预订、Kubernetes、完整 PWA、全面 UI 重构、
多城市联程和新基础设施。V2 仅提供建议、估算和官方入口提示，不接入订单或支付。

## 7. 架构演进方针

Web 逐步迁移至 `app/router`、`app/stores`、`pages`、`features`、`components`、`api`、
`composables`、`types` 和 `utils`，只在改动相关功能时迁移。

Java 继续保持 `controller -> application -> domain -> infrastructure` 分层，并按用例拆分超大
Service，例如版本查询、比较、回滚和创建。Python 逐步拆分高德 HTTP Client、鉴权限流、POI/
路线映射、缓存、降级和指标，以及规划 workflow、召回、排序、路由、求解、解释和局部重规划。

这些是渐进式目标，不改变当前模块化单体、Transactional Outbox、RabbitMQ at-least-once
消息和不可变行程版本的基本设计。详细设计边界见
[系统架构设计](architecture.md) 和 [规划算法与 Agent](planning.md)。

## 8. 阶段与退出标准

| 阶段 | 主要交付 |
| --- | --- |
| Phase 0 | V1.3 收口、发布标签、迁移/文档/验收一致 |
| Phase 1 | Router、Pinia、页面路由化、`App.vue` 瘦身、统一交互状态 |
| Phase 2 | 真实 SSE 阶段、通勤后端写回、时间/费用同步、版本差异 |
| Phase 3 | 列表、分享、PDF、ICS、移动端只读体验 |
| Phase 4 | 指标、结构化日志、诊断、幂等重试和故障演练 |
| Phase 5 | 四条 E2E、CI 门禁、Compose 发布验收、备份恢复、HTTPS 记录 |

只有同时满足以下条件才可发布 V2：用户可以完成规划、调整、版本回滚、分享和导出；规划展示
真实阶段；Provider 与消息故障可诊断并可按规则恢复；核心业务指标可查询；所有者校验、分享
隔离、SSRF 防护、日志脱敏和基本限流有效；Java/Python/Web、迁移、契约、四条 E2E 和 Compose
验收均有可复现证据。

## 9. 文档维护规则

实现每一项 V2 纵向切片时，同步更新下列文档，但只记录已实现且已验证的内容：

| 文档 | 负责内容 |
| --- | --- |
| [产品路线图](roadmap.md) | 当前版本、优先级、范围边界与发布状态 |
| [V2 交付与验收清单](v2-delivery-checklist.md) | 逐项状态、命令、证据、外部阻塞 |
| [系统架构设计](architecture.md) | 已实施职责边界、消息和可观测性设计 |
| [规划算法与 Agent](planning.md) | 实际阶段协议、通勤重算与求解行为 |
| [API](api.md) / [数据库](database.md) | 已发布 HTTP 契约和实际迁移，不预写未实现接口或表 |
| [部署](deployment.md) | 已验证指标、诊断、备份恢复和 HTTPS 操作 |
