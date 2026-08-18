# Phase 4: Postprocess Pipeline Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-18
**Phase:** 4-Postprocess Pipeline Hardening
**Areas discussed:** validate() 阻断行为, 表级原子写入方式, 测试覆盖范围, 现有数据处理

---

## validate() 阻断行为

| Option | Description | Selected |
|--------|-------------|----------|
| 任何异常就阻断 | validate() 检测到的任何问题都阻止写入 | ✓ |
| 数量阈值 | 异常记录数超过某个百分比/绝对数才阻断 | |
| 按严重度分级 | 区分 hard/soft 异常，只有 hard 级别才阻断 | |

**User's choice:** 任何异常就阻断
**Notes:** 该模块已经出过一次未被察觉的真实 bug，选择最保守的方案。

| Option | Description | Selected |
|--------|-------------|----------|
| 默认就阻断 | 静默写坏数据比多跑一次人工审查代价高得多 | ✓ |
| --strict flag 才开启 | 默认只警告，人工跑时加 --strict 才硬阻断 | |

**User's choice:** 默认就阻断

| Option | Description | Selected |
|--------|-------------|----------|
| 报告具体异常列表，不写 limit_events，进程退出码非零 | limit_events 保持上一次成功的状态 | ✓ |
| 写入 limit_events_pending 等待人工审核 | 保留本次输出到一个单独表供人工审核/手动推进 | |

**User's choice:** 报告具体异常列表，不写 limit_events，进程退出码非零

---

## 表级原子写入方式

| Option | Description | Selected |
|--------|-------------|----------|
| 写入 limit_events_new，成功后 ALTER TABLE RENAME 换名 | 失败时旧表完好无损 | ✓ |
| 先备份为 limit_events_prev 再写 | 每次运行先把旧 limit_events 重命名为 limit_events_prev，再新建写入 | |

**User's choice:** 写入 limit_events_new，成功后 ALTER TABLE RENAME 换名

| Option | Description | Selected |
|--------|-------------|----------|
| 直接丢弃 | 换表成功就丢弃旧数据，不保留历史 | ✓ |
| 保留一份为 limit_events_prev 备用 | 每次成功写入后保留上一次的表作为 limit_events_prev | |

**User's choice:** 直接丢弃
**Notes:** limit_events 可从 subscription_restrictions 完全重建，不需要额外备份表。

---

## 测试覆盖范围

| Option | Description | Selected |
|--------|-------------|----------|
| 完整状态机矩阵 | 除历史 bug 场景外，还覆盖正常配对、未匹配开放式 suspend、未知 restriction_type | ✓ |
| 只补历史 bug 的两个场景 | 只写 holiday-resume-in-the-middle 和 missing-prior-suspend 两个回归测试 | |

**User's choice:** 完整状态机矩阵
**Notes:** CONCERNS.md 列出的五种场景全部纳入。

| Option | Description | Selected |
|--------|-------------|----------|
| 真实临时 SQLite + 构造的 subscription_restrictions 记录 | 与项目现有测试约定一致（不用 mock） | ✓ |
| 纯内存 dict 构造，不过 SQLite | 直接构造 records 列表调 build_limit_events()，跳过数据库 IO | |

**User's choice:** 真实临时 SQLite + 构造的 subscription_restrictions 记录

---

## 现有数据处理

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 4 完成后先跑一次实际数据验证 | 在真实 fund_status.db 上跑一次 postprocess()，就地判断报错是真 bug 还是需要放宽阈值 | ✓ |
| 不管，只针对新代码路径写测试 | 假设现有数据干净，有问题到时候再说 | |

**User's choice:** Phase 4 完成后先跑一次实际数据验证

---

## Claude's Discretion

- validate() 返回的具体异常列表数据结构/形状
- 原子换表是实现为 postprocess.py 内的方法还是独立小 helper
- tests/test_postprocess.py 里新增测试辅助函数的命名/结构

## Deferred Ideas

None — 讨论全程在 phase 范围内。CONCERNS.md 里最初提出的 --strict flag 方案被明确讨论并否决，选择了默认硬阻断（见 D-02）。
