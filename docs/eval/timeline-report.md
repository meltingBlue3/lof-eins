# 每日状态覆盖率报告（v2，阶段 D）

- 生成日期：2026-11-18；对应 [重构方案](../redesign-subscription-state.md) §7.2、§7.5
- 范围：2022-01-04 ~ 2024-12-31，410 只基金，297,660 个基金日（公告语料从 2022 年开始，所以从 2022-01-01 起统计）

## 状态与来源

| 状态 | 基金日 | 占比 |
|---|---:|---:|
| unknown | 148,840 | 50.0% |
| open | 72,675 | 24.4% |
| closed | 47,084 | 15.8% |
| limited | 29,061 | 9.8% |

`limited` 中金额不明的 10,236 天。

| 来源 | 基金日 | 占比 |
|---|---:|---:|
| default | 148,840 | 50.0% |
| change | 84,136 | 28.3% |
| inferred_prior | 31,176 | 10.5% |
| inferred_open | 24,171 | 8.1% |
| restatement | 6,256 | 2.1% |
| overlay | 3,081 | 1.0% |

## 基金分布

- 整个区间都是 unknown 的基金 185 只；unknown 占一半以上的 204 只；完全没有 unknown 的 177 只。
- unknown 的日子没有任何目标路径上的声明可依。回测按 `unknown_policy` 处理（§8.1），保守边界当作不能申购。

## 金标基金

| 基金 | open | limited | closed | unknown | 来自 overlay | 来自推断 |
|---|---:|---:|---:|---:|---:|---:|
| 160128 | 20 | 0 | 706 | 0 | 20 | 571 |
| 160416 | 247 | 452 | 27 | 0 | 27 | 0 |
| 160723 | 0 | 189 | 537 | 0 | 18 | 0 |
| 161005 | 0 | 726 | 0 | 0 | 0 | 0 |
| 161116 | 0 | 40 | 686 | 0 | 2 | 0 |
| 161125 | 0 | 289 | 437 | 0 | 27 | 0 |
| 161128 | 29 | 278 | 419 | 0 | 27 | 0 |
| 161129 | 0 | 0 | 726 | 0 | 16 | 0 |
| 161815 | 683 | 0 | 43 | 0 | 43 | 0 |
| 162207 | 0 | 0 | 0 | 726 | 0 | 0 |
| 162411 | 0 | 699 | 27 | 0 | 27 | 685 |
| 163208 | 644 | 0 | 82 | 0 | 32 | 0 |
| 163417 | 686 | 0 | 40 | 0 | 40 | 0 |
| 164701 | 0 | 686 | 40 | 0 | 36 | 483 |
| 164906 | 293 | 336 | 91 | 6 | 42 | 0 |
| 167506 | 697 | 0 | 29 | 0 | 29 | 0 |
| 169201 | 0 | 0 | 0 | 726 | 0 | 0 |
| 501018 | 0 | 437 | 289 | 0 | 49 | 0 |
| 501300 | 354 | 348 | 24 | 0 | 24 | 0 |

## 时间线异常

冲突一律按更严格的状态物化，并写入 `anomalies`，等人裁决。各类型的含义见 `src/pipeline/timeline.py` 模块说明。

| 类型 | 条数 | 基金数 |
|---|---:|---:|
| long_inferred_prior | 125 | 125 |
| investor_scope | 59 | 11 |
| ignored_resume | 30 | 17 |
| conflict_same_day | 1 | 1 |

`conflict_same_day` 示例（金标基金在前）：

- 164906 2022-05-23~2022-05-25：changes effective the same day disagree; the stricter is used

`investor_scope` 示例（金标基金在前）：

- 160105 2025-01-15~2025-01-15：institution-only limited 5000000.0: 自2025年1月15日起，本基金管理人将暂停接受非个人投资者单日每个基金账户累计申购和定投本基金超过500万元的申请（不含500万元，申购和定投的申请金额合并计
- 160105 2025-01-21~2025-01-21：institution-only open None: 本基金管理人决定自2025年1月21日 起取消本基金对非个人投资者大额申购及定投的限制，恢复办理本基金的正常申购及定投业务
- 160105 2026-01-09~2026-01-09：institution-only limited 5000000.0: 自2026年1月9日起，本基金管理人将暂停接受非个人投资者单日每个基金账户累计申购和定投本基金超过500万元的申请（不含500万元，申购和定投的申请金额合并计算
- 160105 2026-01-20~2026-01-20：institution-only open None: 本基金管理人决定自2026年1月20日起取消本基金对非个人投资者大额申购和定投业务的限制，恢复办理本基金的正常申购和定投业务
- 160106 2025-01-15~2025-01-15：institution-only limited 5000000.0: 自2025年1月15日起，本基金管理人将暂停接受非个人投资者单日每个基金账户累计申购和定投本基金超过500万元的申请（不含500万元，申购和定投的申请金额合并计
- 160106 2025-01-21~2025-01-21：institution-only open None: 本基金管理人决定自2025年1月21日起取消本基金对非个人投资者大额申购及定投的限制，恢复办理本基金的正常申购及定投业务
- 160106 2026-01-09~2026-01-09：institution-only limited 5000000.0: 自2026年1月9日起，本基金管理人将暂停接受非个人投资者单日每个基金账户累计申购和定投本基金超过500万元的申请（不含500万元，申购和定投的申请金额合并计算
- 160106 2026-01-20~2026-01-20：institution-only open None: 本基金管理人决定自2026年1月20日起取消本基金对非个人投资者大额申购及定投业务的限制，恢复办理本基金的正常申购及定投业务

`ignored_resume` 示例（金标基金在前）：

- 163417 2022-07-04~2022-07-04：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 167506 2022-10-10~2022-10-10：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 160505 2022-01-17~2022-01-17：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 161010 2024-12-13~2024-12-13：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 161010 2025-05-16~2025-05-16：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 161010 2025-09-17~2025-09-17：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 161010 2025-10-21~2025-10-21：resumption right after a closure of the same notice: back to the pre-holiday baseline
- 161010 2025-12-11~2025-12-11：resumption right after a closure of the same notice: back to the pre-holiday baseline
