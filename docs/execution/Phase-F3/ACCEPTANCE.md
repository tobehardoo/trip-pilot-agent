# F-3 验收记录 — 架构职责收敛

- 范围：F-0 收敛方案 §F-3（a/b/c/d 逐刀）
- 纪律：一刀一验收一提交；依赖方向以"架构图"为准（providers 契约层不得依赖 infrastructure 适配层）

## F-3a Python 依赖方向修复（`92304cf`）

### 修复内容

`providers/map.py`、`providers/_amap_route_failures.py`、`providers/_amap_transit_failures.py`
三个 providers 层文件从 `infrastructure/amap/errors.py` 导入 6 个错误码 frozenset——
**反向依赖**（providers 契约层依赖 infrastructure 适配层）。

处置：
1. 6 个 frozenset（AUTH/PERMISSION/RATE/QUOTA/UNAVAILABLE/INVALID_REQUEST_CODES）上提到
   `providers/amap_error_codes.py`（单一事实来源现在位于契约层）
2. 3 个消费者 import 改指新位置；docstring 同步更新
3. `infrastructure/amap/errors.py` 删除（grep 证实唯一消费者就是这 3 个 providers 文件；
   `infrastructure/amap/__init__.py` 无 re-export；tests/ 无引用）

依赖方向恢复为：`infrastructure（适配器） → providers（契约）`。

### 豁免评估（记录在案）

`domain/planning/protocols.py` 从 `worker/contracts` 导入 7 个类型
（FallbackOperation / Itinerary / KnowledgeEvidence / PlanningCandidateValidationCommand /
PlanningCreateCommand / PlanningReplanCommand / ProviderProvenance）。

**结论：豁免（成本 > 收益）**。依据：
- 这些类型全部继承 `worker/contracts` 内部的 `MessageModel` / `InboundMessageModel`
  基类体系（分布于 496–1670 行），与 RabbitMQ wire 契约深度耦合
- 下沉 domain 层 = 在 domain 复制消息类型（违反 F-2a "唯一"原则）或拖拽整个
  消息基类体系（等价于把 worker.contracts 搬到 domain，超出本刀职责）
- protocols.py 对 worker/contracts 的依赖是协议签名层面的类型标注，非运行时反向调用

### 验收

- `tests/test_map_provider.py` + `test_route_provider.py` + `test_amap_transit.py`
  + `test_provider_error_mapping.py`：**159 passed**
- 全量 pytest：**2063 passed / 42 skipped**（1 error 经双盲对照确认为既有测试隔离
  问题——单独重跑通过，且该测试与本次修改零依赖）
- ruff：全绿

---

## 附：git store corruption 事件记录（2026-09-01，F-3a 期间）

**现象**：`git stash push` 报 `not a valid object` → `git status` 报 `bad object HEAD` →
fsck 发现最近 7+ 个 commit 对象及部分 tree 对象缺失（reflog 中 20 个提交仅 4 个
commit 对象幸存，且无一个历史 tree 完整）。

**影响**：F-2b 刀4（`50a860f`）至 F-2d（`8604089`）共 7 个本地提交的 commit 对象
不可恢复（对象缺失且无任何引用；reflog 文本仍保留完整提交信息可追溯）。

**处置**（内容 100% 保全）：
1. 备份 `.git/logs`、index、main ref 到 `/tmp/git-backup-20260901/`
2. `git checkout-index -a -f` + `git add -A` 从工作树全量重建 index（996 文件）
3. 重建基线提交 `23fc612`（树 = F-2d 全量内容，message 注明恢复性质）
4. F-3a 修改单独提交为 `92304cf`（独立刀次粒度保留）

**注意**：本环境 git 对象库写入存在不稳定性（仓库初始化时即有
"after git store corruption" 基线记录），**强烈建议尽快 `git push` 到远端备份**
（本会话内 fetch 因代理隧道 502 失败，非仓库问题）。历史 broken link 均为
悬空对象，不影响当前 HEAD 链（`git rev-list --count HEAD` = 1 正常）。
