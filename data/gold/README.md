# 金标时间线（gold timeline）

人工核对过的"场内申购"每日状态，用来给任何一版限购数据打分（`scripts/eval_timeline.py`）。
设计背景见 [docs/redesign-subscription-state.md](../../docs/redesign-subscription-state.md) §7.3。

## 文件

| 文件 | 内容 |
|---|---|
| `timeline.csv` | 状态区间，一行一个区间 |
| `funds.csv` | 每只基金的标注元信息：临时覆盖是否标全、谁起草、谁复核 |

## `timeline.csv` 字段

| 字段 | 说明 |
|---|---|
| `fund_code` | 场内代码（LOF 的 A 类人民币份额） |
| `layer` | `baseline`（长期状态）或 `overlay`（临时状态，比如节假日暂停） |
| `status` | `open` / `limited` / `closed` |
| `amount` | `limited` 时必填：单日单账户上限，单位为元；其他状态留空 |
| `valid_from`, `valid_to` | 闭区间，格式 `YYYY-MM-DD`，两者都必填 |
| `confidence` | `high`：有原文直接说明<br>`medium`：由"没有限购公告、节假日公告恢复申购时没有附加条件"推断得出；或者引用的是交易所层面的日历（比如别的基金公告里的非港股通交易日）<br>`low`：语料里根本没有这只基金的申购状态公告，只能从"费率优惠名单里有它"推断为开放 |
| `source_pdf` | 相对 `data/real_all_lof/announcements/` 的路径 |
| `evidence` | 原文摘录。baseline 行必填；overlay 行可以留空 |
| `note` | 备注 |

## 规则

1. 同一只基金的 baseline 区间**不能重叠**。baseline 没覆盖到的交易日视为"未标注"，不参与评分。
2. 某天如果有 overlay，以 overlay 为准；否则取当天的 baseline。
3. 只标注目标路径：场内代码、代销或全部渠道、申购业务。直销柜台的限额不算；某一家销售机构的暂停也不算。
4. "暂停大额申购，单日单账户不超过 X 元"一律记为 `limited`，金额取 X。
5. 节假日公告如果只暂停赎回（因为申购本来就处于暂停状态），不需要标 overlay。
6. 窗口目前是 2021-01-04 ~ 2024-12-31，与现有行情数据一致。公告语料从 2022 年开始，所以需要节假日 overlay 的开放或限额区间，2021 年一律不标，只有整段处于暂停状态的 2021 年区间才标。
7. 只适用于某一类份额的公告（比如"A 类人民币份额恢复申购"），按目标份额（场内 A 类人民币）取值。
8. 多只基金合在一起的家族公告，只认列出了本基金代码的那一段和那张表。

## 复核状态

19 只基金都由 Claude 根据 PDF 原文起草，**尚待人工复核**。复核完成后，在 `funds.csv` 的 `reviewed_by` 一栏填写复核人和日期。`funds.csv` 的 `overlays` 一栏为 `partial` 的基金（目前是 167506），有已知但无法从语料确认的临时暂停日。
