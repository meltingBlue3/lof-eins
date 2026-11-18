"""
Subscription-state pipeline v2 (see docs/redesign-subscription-state.md).

申购状态流水线 v2。阶段 B：公告清单、正文缓存、分诊、LLM 客户端。

Modules:
    db        -- schema and connection for subscription_state.db
    registry  -- register every announcement PDF with its sha256
    texts     -- local pdfplumber text cache (pdf_texts)
    triage    -- title rules + LLM fallback deciding which PDFs to extract
    llm       -- OpenAI-compatible chat client with retries and tool calling
"""
