"""
Evaluation of subscription-state timelines against hand-verified gold data
and against market behaviour (red flags).

申购状态时间线的评估：对照人工核对的金标数据，以及对照市场行为（红旗检测）。

A "daily timeline" throughout this package is a DataFrame indexed by trading
day with columns ``status`` ('open' | 'limited' | 'closed' | 'unknown') and
``amount`` (float yuan per account per day, NaN unless status is 'limited').
"""
