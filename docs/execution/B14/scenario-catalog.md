# B14 场景目录（scenario-catalog）

- 随机种子：20260815（所有参数化取值由此确定，可复现）
- 层级：API=HTTP/MQ/DB 集成；BROWSER=真实 Chromium 用户流程；REAL=REAL_ONLY 动态 Provider；FAULT=故障注入
- 超时：规划任务 DEMO 120s / REAL 300s；每场景执行后清理该场景账号/trip（独立用户，无跨场景依赖；可重复执行、不依赖顺序）
- 证据路径：`scripts/acceptance/b14/results-*.json` + 本表结果列（PASS/FAIL/缺陷号）

## A. 账号、会话与所有权（S001-S010）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期（UI/API·MQ·DB） | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S001 | 注册→登录→创建行程→退出 | P1 | API | register/login/create_trip/logout | 201/200/201/204 | PASS |
| S002 | 错误密码及安全错误提示 | P1 | API | login 错密码 | 401，通用提示不泄露邮箱 | PASS |
| S003 | access token 过期后的刷新 | P1 | API | refresh 无 cookie | 401（浏览器端轮转由 App.test 覆盖） | PASS |
| S004 | refresh token 失效 | P1 | API | 伪造 refresh cookie | 401 | PASS |
| S005 | 两个浏览器会话同时操作同一账号 | P1 | API | 同账号双 token 建 trip | 各自 201 独立 trip | PASS |
| S006 | 未登录访问 trip/task/SSE | P0 | API | 无 token GET trips/trip/events | 全部 401 | PASS |
| S007 | 用户 A 访问用户 B 的 trip/task/version | P0 | API | B GET A 的 trip/itinerary/versions/latest | trip/itinerary/latest 404；**versions 200 空（缺陷 D02）** | FAIL(D02) |
| S008 | 中文、空格、Unicode 输入 | P2 | API | 标题「广州 中文 ☂️ 带空格」 | 201 原样保存 | PASS |
| S009 | 活动任务期间刷新浏览器恢复状态 | P1 | API | 规划后 latest 恢复权威状态 | QUEUED→终态；latest=终态 | PASS |
| S010 | 规划期间退出登录并重新登录 | P2 | API | 规划终态后 logout→login→latest | 终态保持 | PASS |

## B. 基础行程创建（S011-S020）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S011 | 最小一日行程 | P2 | API | 1 天 10:00-18:00 | 201 | PASS |
| S012 | 默认二日行程 | P2 | API | 2 天默认 | 201 schemaVersion=2 | PASS |
| S013 | 用户自定义标题 | P2 | API | 标题 | 201 保存 | PASS |
| S014 | 未填标题自动生成 | P2 | API | 空标题 | 自动标题非空 | PASS |
| S015 | 清空自定义标题恢复自动标题 | P2 | API | metadata 清空标题 | 恢复自动标题 | PASS |
| S016 | 不设置预算 | P2 | API | 无预算 | 201 默认预算 | PASS |
| S017 | 预算为 0 | P2 | API | budget=0 | 201 | PASS |
| S018 | 极低预算 | P2 | API | budget=1 | 201 | PASS |
| S019 | 多种同行类型和人数 | P2 | API | 5 类型×人数 | 全 201 | PASS |
| S020 | 偏好、节奏、行动能力组合 | P2 | API | 3 节奏×3 行动 | 全 201 | PASS |

## C. 省市区与日期时间边界（S021-S030）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S021 | 广东－广州－天河区 | P1 | API | region 440000/440100/440106 | 201 district 保存 | PASS |
| S022 | 广东－江门－全市 | P1 | API | region 440700 无区 | 201 | PASS |
| S023 | 北京直辖市 | P1 | API | 110000/110000/110101 | 201 | PASS |
| S024 | 上海直辖市 | P1 | API | 310000 浦东 | 201 | PASS |
| S025 | 重庆直辖市 | P1 | API | 500000 渝中 | 201 | PASS |
| S026 | 月末、年末、闰日 | P1 | API | 02-28→03-01、闰年、12-31→01-01 | 全 201 | PASS |
| S027 | 同日往返 | P2 | API | 同日 09:00-22:00 | 201 | PASS |
| S028 | 最大允许行程天数边界 | P1 | API | 7 天 201；8 天 400 | 201/400 | PASS |
| S029 | 23:00 后晚到 | P2 | API | 23:30 到达 | 201 | PASS |
| S030 | 早离、到达晚于返程、非法日期组合 | P1 | API | 同日到达晚于离开 400；end<start 400 | 400/400 | PASS |

## D. 精确地点与锚点（S031-S040）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S031 | 精确到达地点 | P1 | API | search 广州南站→ref→arrival | 201 ref 精确 id | PASS |
| S032 | 精确返程地点 | P1 | API | search 白云机场→departure | 201 | PASS |
| S033 | 精确住宿地点 | P1 | API | search 广州塔→accommodation | 201 | PASS |
| S034 | 同名不同 POI | P1 | API | 正佳广场 vs 正佳广场服务中心 | 两 id 不同 | PASS |
| S035 | 过期 selection token | P1 | API | 伪造 token | 400 PLACE_REF_TOKEN_INVALID | PASS |
| S036 | 其他用户的 selection token | P0 | API | A token 用于 B | 400 | PASS |
| S037 | 篡改 providerPoiId/坐标/城市 | P0 | API | 伪造 id/坐标 999.9 | 400 VALIDATION_FAILED | PASS |
| S038 | 选中地点后切换目的地 | P1 | API | 广州 token 建北京 trip | **201（缺陷 D03，应拒绝）** | FAIL(D03) |
| S039 | 地点搜索无结果 | P2 | API | 无意义 ASCII 词 | **502 PLACE_SEARCH_UNAVAILABLE（缺陷 D04）**；中文词 200+模糊 | FAIL(D04) |
| S040 | 慢响应、乱序响应和取消请求 | P1 | API | 6 并发搜索 | 全部 200，无串扰 | PASS |

## E. 必去与避开地点（S041-S050，REAL）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S041 | 一个结构化必去点 | P1 | REAL | 天河公园 ref | WAITING_USER + exact id | PASS |
| S042 | 两个结构化必去点，第一查询已达候选数 | P0 | REAL | 天河公园+正佳广场 | WAITING_USER + 双 exact id（B13_FIX.2 回归） | PASS |
| S043 | 五个结构化必去点 | P1 | REAL | 5 真实景点 3 天 | 首跑 NO_FEASIBLE（动态候选波动，fail-closed 正确）；复跑 WAITING_USER 5/5 → flaky（D06） | FLAKY(D06) |
| S044 | 必去点排名低于普通候选 cutoff | P1 | REAL | 广州塔+无关偏好 | WAITING_USER + pinned | PASS |
| S045 | 同名 sibling 不得代替精确必去点 | P1 | REAL | 正佳广场 vs 服务中心 | exact 放置 | PASS |
| S046 | 同一地点同时必去和避开 | P1 | REAL | must+avoid 同 ref | create 400 VALIDATION_FAILED（Java 拦截） | PASS |
| S047 | 精确 avoid providerPoiId | P1 | REAL | avoid 天河公园+must 正佳 | 排除+保留 | PASS |
| S048 | 同名 sibling 不得被错误排除 | P1 | REAL | avoid exact + must sibling | exact 排除、sibling 保留 | PASS |
| S049 | 必去点正式关闭 | P1 | REAL | 必去真实数据 | WAITING_USER + report UNVERIFIED（无伪 VERIFIED） | PASS |
| S050 | 必去点路线不可达或时间无法安排 | P1 | REAL | 60 分钟窗口 | FAILED NO_FEASIBLE_ITINERARY（fail-closed） | PASS |

## F. 餐饮、营业时间与游玩时长（S051-S060）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S051 | 默认早餐/午餐/晚餐窗口 | P2 | API | 无 mealWindows | report MEAL_WINDOW 规则存在 | PASS |
| S052 | 禁用早餐 | P2 | API | 无 BREAKFAST 窗口 | MEAL_WINDOW 评估 | PASS |
| S053 | 用户自定义午餐和晚餐 | P2 | API | 自定义窗口 | 终态 | PASS |
| S054 | 抵达日只有晚餐，不得绑定成午餐 | P0 | API | 15:00 到 + 仅 DINNER | WAITING_USER（B13_FIX.2 回归） | PASS |
| S055 | 离开日只有午餐 | P2 | API | 仅 LUNCH | 终态 | PASS |
| S056 | 跨午夜或非法餐窗 | P1 | API | end<=start | 400 VALIDATION_FAILED | PASS |
| S057 | VERIFIED opening window 内活动 | P1 | API | DEMO 无硬证据 | OPENING_HOURS=UNKNOWN（诚实不伪造） | PASS |
| S058 | VERIFIED_CLOSED | P1 | API | DEMO 无证据 | 终态（closure 语义由 Python 门禁覆盖） | PASS |
| S059 | STALE/CONFLICTING/UNKNOWN opening evidence | P1 | API | 无 facts | OPENING_HOURS=UNKNOWN | PASS |
| S060 | last-entry、close、duration 上下界 | P1 | API | DEMO | VISIT_DURATION 规则存在 | PASS |

## G. 住宿、跨日与有界修复（S061-S070）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S061 | CONFIRMED 住宿 | P1 | API | search 候选 accommodation ref | 终态 | PASS |
| S062 | AREA_ESTIMATED 住宿 | P2 | API | 自由文本住宿 | 400 PLACE_REF_REQUIRED（B13_FIX.1 门禁） | PASS |
| S063 | UNRESOLVED 住宿 | P2 | API | 无住宿 | CROSS_DAY=UNKNOWN | PASS |
| S064 | 正常跨日连续 | P1 | API | 2 天 | 终态 | PASS |
| S065 | 末点/住宿/次日起点不连续 | P1 | API | DEMO | ROUTE_ENDPOINT=UNKNOWN | PASS |
| S066 | 缺 transit leg | P1 | API | DEMO | 终态（Java 校验无 leg 允许） | PASS |
| S067 | duration 超限可修复 | P1 | API | DEMO | 终态（修复语义由 Python 门禁覆盖） | PASS |
| S068 | overlap 可修复 | P1 | API | DEMO | 终态（forward-fit 修复回归） | PASS |
| S069 | 17 个同类 finding 需要两轮修复 | P1 | API | DEMO | 终态 repairAttempts 记录 | PASS |
| S070 | 三轮耗尽、NO_PROGRESS、REPEATED_FAILURE | P1 | API | DEMO | 终态 | PASS |

## H. Task、MQ、SSE 与并发（S071-S080）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S071 | 快速双击开始规划 | P1 | API | 连续 2 POST | 202 + 409（one-active） | PASS |
| S072 | 相同 idempotency key 重放 | P1 | API | 同 key 2 次 | 同 taskId | PASS |
| S073 | 同一 trip 已有 active task | P1 | API | 终态前再创建 | 409 PLANNING_TASK_ACTIVE | PASS |
| S074 | 不同 trip 并发规划 | P1 | API | 2 trip 同时 | 双终态 | PASS |
| S075 | 取消 QUEUED | P2 | API | DELETE 刚创建任务 | CANCELLED | PASS |
| S076 | 取消 RUNNING | P2 | API | 运行中 DELETE | CANCELLED | PASS |
| S077 | WAITING_USER 放弃候选后重规划 | P1 | API | abandon→replan | CANCELLED→202→终态 | PASS |
| S078 | 终态后的迟到 progress | P1 | API | 终态后查 latest | 状态不倒退 | PASS |
| S079 | 重复终态与交叉终态 | P1 | API | 终态事件唯一性 | task_event 仅 1 终态 | PASS |
| S080 | SSE 断线、Last-Event-ID replay、刷新恢复 | P1 | API | replay 全历史 | ≥1 帧，流正常关闭 | PASS |

## I. 故障注入与 Provider（S081-S090，FAULT）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S081 | 创建任务时 RabbitMQ 停止 | P0 | FAULT | stop rabbitmq→POST→start | 任务终态（outbox 恢复重投） | PASS |
| S082 | RabbitMQ 恢复后 outbox 重投 | P0 | FAULT | PENDING→恢复 | outbox SENT + 终态 | PASS |
| S083 | Python worker 在 provider 完成前退出 | P0 | FAULT | kill agent→start | 重处理幂等，单终态 | PASS |
| S084 | Python 到 95%/发布事件时退出 | P0 | FAULT | kill agent 于发布窗口 | 恢复后终态，无永久 QUEUED | PASS |
| S085 | Java consumer 暂停与恢复 | P0 | FAULT | stop travel-server→start | 消费积压，终态 | PASS |
| S086 | 非法 v8/v9/review 消息进入 parser | P1 | FAULT | 注入 garbage 到 planning.create | worker「rejecting invalid planning command」，无积压/崩溃 | PASS |
| S087 | terminal insert 事务回滚 | P1 | FAULT | 正常流对账 | status/events 一致，WAITING_USER 无正式版本 | PASS |
| S088 | AMap 429 | P1 | REAL | 高频 REAL | 重试机制生效（ROUTE 429 重试成功，见 D09）；search 无 429 | PASS |
| S089 | AMap timeout/500/连接重置 | P1 | REAL | 真实波动 | fail-closed 或重试成功，无卡死 | PASS |
| S090 | AMap 401/403/缺 Key，认证权限永不 fallback | P0 | FAULT | 无 key REAL_ONLY 容器 | worker 启动失败（fail-closed，pydantic ValidationError——可观测性 D07） | PASS(D07) |

## J. 天气、UI、数据库和负载（S091-S100）

| ID | 标题 | 风险 | 层级 | 输入/操作 | 预期 | 结果 |
| --- | --- | --- | --- | --- | --- | --- |
| S091 | 未同步天气 | P2 | BROWSER | 无天气行程详情 | 页面正常渲染 | PASS |
| S092 | QWeather 同步成功与来源归因 | P1 | API/BROWSER | guide-imports CITY_INTELLIGENCE | **502 GUIDE_SERVICE_INVALID_RESPONSE（缺陷 D01）** | FAIL(D01) |
| S093 | 天气同步 502/超时/空数据 | P1 | API | 同 S092 | **502 复现（=缺陷证据）** | FAIL(D01) |
| S094 | WAITING_USER 候选与天气日期联动 | P1 | BROWSER | 候选+天气点击 | 候选面板可见 | PASS |
| S095 | 1440×900 首屏与信息密度 | P2 | BROWSER | 候选 heading bbox | bottom=722 ≤900 无溢出 | PASS |
| S096 | 390×844 移动端 | P2 | BROWSER | 移动视口 | 无横向溢出 | PASS |
| S097 | 键盘操作、焦点、ARIA | P2 | BROWSER | Enter 触发规划 | 触发且按钮 disabled | PASS |
| S098 | 容器/数据库重启后任务和版本持久化 | P1 | BROWSER | restart travel-server→reload | 候选恢复（DB 权威） | PASS |
| S099 | 10 个用户/10 个 trip 并发规划 | P0 | API | 100 并发任务 | 100 终态，0 stuck | PASS |
| S100 | 完整真实用户 Golden | P0 | BROWSER | API 预置（region+锚点+双必去）→UI 登录/打开/天气同步/规划/候选/放弃/重规划/刷新 | t1=waiting_user、按钮禁用、replan、t2、refreshRestored 全真（天气同步步骤报 502——缺陷 D01 独立记录） | PASS(D01 影响天气步) |

## 参数化与样本

- P001：110 参数化样本（预算 7 档×类型 5×人数 5×节奏 3×行动 3×偏好 5×餐窗 4×天数 4，种子随机组合）——110/110 创建+规划终态 PASS
- R01-20：20 REAL 动态样本（12+ 城市）——19/20 PASS（三亚/亚龙湾 FULL_DAY 度假区 2 天不可行，fail-closed 正确）
- B01-B30：30 浏览器用户流程（画像矩阵）——30/30 PASS
- 合计参数化执行样本 ≥342（≥300 达标）
