# API Coverage — Phase 4: Postprocess Pipeline Hardening

No external API integration: this phase hardens `src/data/postprocess.py`'s local SQLite
suspend/resume interval logic (validation gate, regression tests, atomic table swap) —
it does not add, modify, or call any external API/SDK/service. The detector's trigger came
from incidental prose (a threat-model note about the cost of re-parsing PDFs "through a paid
LLM API" if the production database were lost, and a pre-existing `KIMI_API_KEY` docstring
line in `scripts/parse_announcements.py` that predates this phase and is untouched by it).
The actual Kimi/OpenAI-compatible LLM client surface is addressed by its own coverage
decision in Phase 5 (Dual-Provider LLM Client & Extraction Reliability), not here.
