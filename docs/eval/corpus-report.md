# 公告清单与正文覆盖报告

- 生成日期：2026-11-18；数据库：`data/real_all_lof/config/subscription_state.db`
- 对应 [重构方案](../redesign-subscription-state.md) 阶段 B（§5 表 1~3、§6.1、§6.2）

## 登记

- PDF 文件 11,802 个，涉及 409 只基金；不同内容（sha256）5,277 份。同一份家族公告会被复制到多只基金的目录下，所以文件数远多于内容数。

## 分诊

| 结果 | 依据 | 文件 | 不同内容 |
|---|---|---:|---:|
| irrelevant | `rule:sales_fee` | 5,974 | 2,015 |
| irrelevant | `rule:single_agency` | 2,507 | 440 |
| irrelevant | `rule:doc_type` | 26 | 21 |
| irrelevant | `llm:workbuddy/glm-5.3-flash@triage-v1` | 3 | 3 |
| relevant | `rule:state` | 3,276 | 2,796 |
| relevant | `llm:workbuddy/glm-5.3-flash@triage-v1` | 16 | 2 |

## 召回验收（金标引用的 PDF）

- 金标中 high / medium 置信度的行一共引用了 391 份 PDF，其中 391 份被分为 relevant（召回率 100.0%）。
- low 置信度的行（169201、162207）引用的是费率优惠公告，只用来证明基金在售，不计入召回。
- 按分诊依据：`rule:state` 391

## 正文缓存

- relevant + unsure 共 2,798 份不同内容，已缓存 2,798 份；共 6,136 页、3,635,598 个字符。另有 3 份是分诊前缓存、后来被判为 irrelevant 的。
- 提取器：`pdfplumber@0.11.9+fonttol`；无文字层（疑似扫描件）1 份，打不开 1 份，超过 60 页被截断 0 份。

需要人工处理或 OCR 的文件（扫描件不会被静默跳过）：

| 文件 | 分诊 | 页数 | 副本 | 问题 |
|---|---|---:|---:|---|
| `161229/2022-12-21_国投瑞银中国价值发现股票型证券投资基金(LOF)暂停及恢复申购和赎回业务的申请.pdf` | relevant | 1 | 1 | 无文字层 |
| `501215/2026-01-13_关于兴全积极配置混合型基金中基金(FOF-LOF)暂停接受大额申购(含定投)、大额转换转入申请的公告.pdf` | relevant | – | 1 | PdfminerException: No /Root object! - Is this really a PDF? |

## LLM 分诊调用

| 模型 | 状态 | 份数 |
|---|---|---:|
| `workbuddy/glm-5.3-flash` | ok | 5 |
