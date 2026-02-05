# Phase 2: PDF Processing - Context

**Gathered:** 2026-02-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract text from downloaded LOF fund announcement PDFs and parse purchase limit information using a local LLM (Ollama). This phase delivers the extraction and parsing pipeline that feeds into timeline integration (Phase 3).

**In scope:** PDF text extraction, LLM parsing with structured output, storing parse results
**Out of scope:** Timeline merging (Phase 3), end-to-end CLI (Phase 4)

</domain>

<decisions>
## Implementation Decisions

### PDF Extraction Strategy

**Library: pdfplumber**
- Better Chinese text support than PyPDF2
- Superior table extraction capabilities
- Slightly slower but accuracy is priority for Chinese financial documents

**Table Handling: Hybrid Approach**
- Detect tables in PDF content
- Preserve row/column structure when tables are found
- Fall back to plain text for non-tabular sections
- Pass structured table data to LLM for better parsing

**Multi-page Handling: Page-aware Extraction**
- Include page markers (e.g., "--- Page 2 ---") to preserve context
- Maintain page sequence for LLM understanding
- Handle page breaks intelligently without breaking sentence context

**Success Threshold: 95% extraction rate**
- Log extraction failures with file paths
- Continue processing remaining PDFs
- Track failures for manual review later

### LLM Prompt Design

**Output Format: Structured JSON**
Required schema fields:
```json
{
  "ticker": "string or null",
  "limit_amount": "number or null", 
  "start_date": "YYYY-MM-DD or null",
  "end_date": "YYYY-MM-DD or null",
  "announcement_type": "complete|open-start|end-only|modify|null",
  "is_purchase_limit_announcement": "boolean",
  "confidence": "number 0-1"
}
```

**Few-shot Examples: 2-3 examples covering all types**
- Example 1: Complete announcement (start + end dates)
- Example 2: Open-start announcement (only end date)
- Example 3: End-only announcement (closes existing limit)
- Implicitly covers modify through confidence/uncertainty handling

**Uncertainty Handling: Return null with flags**
- Use `null` for fields that are unclear or not present
- Include `is_purchase_limit_announcement: false` for unrelated PDFs
- Include `confidence` score (0-1) for each extraction
- **Important domain insight:** Some PDFs are not purchase restriction announcements at all — this is completely normal and expected

**Chinese Text: Contextual interpretation**
- Rely on LLM's understanding of Chinese financial terminology
- Minimal phrase mapping — let model interpret contextually
- Trust LLM to understand variations in phrasing (e.g., "暂停申购", "限制大额申购")

### Claude's Discretion

- Exact pdfplumber configuration parameters (table detection thresholds, text extraction settings)
- Prompt engineering specifics (exact wording, system prompts)
- Retry logic for LLM API failures
- Caching strategy for extracted text and LLM responses
- Progress reporting format during batch processing

</decisions>

<specifics>
## Specific Ideas

- **Domain insight:** Not all downloaded PDFs will be purchase restriction announcements — some may be regular fund reports, dividend announcements, etc. The system should gracefully handle these by detecting they're not limit announcements and moving on.
- **Confidence scoring:** LLM should self-assess confidence to help with quality validation
- **Four announcement types must be covered:**
  1. Complete: Has both start_date and end_date
  2. Open-start: Only has end_date (limit already active)
  3. End-only: Announces end of existing limit
  4. Modify: Changes existing limit parameters

</specifics>

<deferred>
## Deferred Ideas

- OCR for scanned PDFs (image-based) — currently assuming text-based PDFs only
- Multi-language support beyond Chinese — not needed for LOF funds
- Automatic re-prompting for uncertain extractions — could be Phase 3 enhancement
- PDF quality scoring before extraction — nice to have for Phase 4

</deferred>

---

*Phase: 02-pdf-processing*
*Context gathered: 2026-02-06*
