# 日程调度器对照基准（greedy vs CP-SAT）

回答一个问题：**CP-SAT 相对现有贪心内核到底带来什么、代价是什么**。
所有场景确定性（静态 JSON + 求解器 seed 0 / 单 worker），无 Provider、无网络、无数据库。

## 运行

```bash
cd apps/agent-service
.venv/Scripts/python.exe benchmarks/scheduler/run_scheduler_benchmark.py
```

输出 stdout 对照表 + `results/latest.json`（跨运行 diff 用）。

## 当前结果（2026-09-03，ortools 9.14.6206）

| scenario | greedy score/items/util | cpsat score/items/util | cpsat solve ms | verdict |
| --- | --- | --- | --- | --- |
| 01-clean-day | 350 / 5 / 60% | 350 / 5 / 60% | 11.7 | TIE |
| 02-tight-capacity | 471 / 6 / 86% | 471 / 6 / 86% | 7.3 | TIE |
| 03-stranded-capacity | 150 / 1 / 100% | 200 / 2 / 80% | 1.5 | **CPSAT_BETTER** |
| 04-must-visit-conflict | 235 / 4 / 88% | 235 / 4 / 88% | 3.2 | TIE |
| 05-opening-windows | 305 / 4 / 55% | 305 / 4 / 55% | 1.7 | TIE |
| 06-verified-closure | 150 / 2 / 23% | 150 / 2 / 23% | 1.1 | TIE |
| 07-meal-split-slots | 345 / 4 / 85% | 345 / 4 / 85% | 7.8 | TIE |
| 08-relaxed-pace | 340 / 4 / 83% | 340 / 4 / 83% | 6.1 | TIE |
| 09-region-coherence | 400 / 5 / 73% | 400 / 5 / 73% | 4.9 | TIE |
| 10-mixed-durations | 269 / 3 / 69% | 322 / 4 / 59% | 5.6 | **CPSAT_BETTER** |

**CPSAT_BETTER 2 / TIE 8 / CPSAT_WORSE 0；单日最大求解 11.7 ms。**

## 结论

1. **贪心在常规日形态已接近最优**（8/10 平）：分数排序 + 首次适配在候选池
   与容量比例健康时并不亏——这是对现有内核的正面验证，不是废它。
2. **劣化集中在容量碎片化形态**：150 分钟槽被单个长高分活动占满时，
   贪心丢掉两个 60 分钟候选（150 vs 200，-25% 总分）；混合时长双槽形态
   贪心 269 vs CP-SAT 322（-16.5%）。这类形态恰好在「到达/离开日窗口被
   锚点压缩」时真实出现。
3. **CP-SAT 零劣化 + 毫秒级代价**：10/10 场景 ≥ 贪心，单日求解 ≤ 12 ms，
   相对规划全链路 3~4 s 可忽略。可行性域与贪心一一镜像
   （容量折扣 / 节奏缓冲 / VERIFIED 营业窗口与闭馆 / must-include），
   所以切换只改变「选谁」，不改变「什么是可行」。

## 切换方式

`PLANNING_DAY_SCHEDULER=GREEDY`（默认，历史行为）/ `CPSAT`（精确求解，
失败回退贪心）/ `SHADOW`（贪心为权威结果返回，同时跑 CP-SAT 并记录对照
日志——生产流量收集切换证据的推荐路径）。
