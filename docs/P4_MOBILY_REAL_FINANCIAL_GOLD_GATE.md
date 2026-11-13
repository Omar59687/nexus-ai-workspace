# Phase 4 — Independent real financial revenue gate (Mobily FY2025)

We now have independently verified target labels, **not self-derived from
the evaluated PDF**:

- Financial year: **2025**
- Company: Etihad Etisalat (Mobily)
- Total revenue: **19,642 million Saudi riyals (SAR)**
- Comparative 2024 revenue: **18,206 million Saudi riyals**
- Official issuer announcement (16 February 2026):
  https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/issuer-news/issuer-announcements/issuer-announcements-details/?anCat=17&anId=93172&cs=7020&locale=en
- Official Arabic earnings-release PDF:
  https://www.saudiexchange.sa/Resources/fsPdf/19852_481_2026-02-16_15-57-44_ar.pdf

The local annual-report PDF was previously processed with 142 pages / 2,139
chunks. An auditor's approximate `19.6 billion` statement on PDF page 114
**is not the exact gold value** and must not be marked as an exact-answer
success.

## Execute just once on owner's real PDF

From the `feature/p4-final-acceptance-candidate` checkout, in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" `
  scripts/verify_mobily_2025_revenue.py --run `
  --pdf "C:\Users\HP PAVILION\Downloads\Mobily Annual Report 2025 - Arabic.pdf" `
  --report "$env:LOCALAPPDATA\NexusAI\reports\mobily-fy2025-gold-acceptance.json"
```

The script performs one bounded isolated extraction, RAM indexing,
registered company/year filtering and 2 model-free retrievals. It checks
whether the exact number `19,642` (Arabic or Western digits, optional
thousands delimiter) and revenue terminology appear on the **same
extracted page**, and whether that candidate page appears among the
top-5/top-10 Arabic and English query results. It also notes same-chunk
cooccurrence. The stdout and report include metadata only, no source
page text or filesystem path. There are no database writes, models,
embeddings or third-party API calls.

### Pass/fail meaning

- `status=PASS` means the diagnostic ran without technical error.
- `technical_status=CANDIDATES_RETRIEVED` means **candidate** pages with
  exact numeric gold and revenue terms were retrieved at top 10 for both
  languages; NOT a confirmed financial answer.
- `technical_status=RETRIEVAL_OR_EXTRACTION_GAP` means the exact gold
  and revenue cue were missing from the extracted page text, or those
  pages were not among the top 10 for one or both languages.
- `financial_truth_status=HUMAN_TABLE_ROW_CONFIRMATION_REQUIRED`
  always remains until we confirm the numeric row is actually 2025
  total revenue, the units are SAR millions, and the citation corresponds
  to that row in this exact **local** document.

Next verify one or two candidate pages visually in the local PDF. If
the exact value is not extractable from the local PDF despite visibly
appearing in the original, the extractor/table-layout track remains
open; do **not** fake a passing gold result by injecting the amount
from official announcements into the indexed text.

Do not upload user's private local PDF or its extracted source text into
GitHub; this benchmark only reports numeric diagnostic indicators.
