# Agora DRE Crawler - AI Agent Instructions

## Project Overview

This is a **multi-workflow web crawler** for Portuguese legal documents from Diário da República (DRE). It extracts laws, articles, and metadata, storing them in a Supabase PostgreSQL database for the Agora platform. The crawler supports **4 distinct workflows**, each with different entry points and purposes.

## Critical Architecture Concepts

### 1. Multi-Workflow System (PROD5 Architecture)

The crawler has **four independent workflows** - understand which you're modifying:

```python
# Workflow 1: Direct URL Extraction (run_single_url_crawl)
# - Takes a single URL, extracts content immediately
# - Creates new source record + document chunks
python main.py extract-url --url "https://diariodarepublica.pt/dr/detalhe/..."

# Workflow 2: Source Discovery (run_discovery_crawl) 
# - Searches by date range + law type
# - Creates source records WITHOUT content extraction
# - Two-stage: discovery → enqueue URLs for later processing
python main.py discover-sources --start-date "2025-04-03" --end-date "2025-04-03" --type "Lei"

# Workflow 3: Batch Processing (run_unchunked_processing)
# - Finds sources with no document_chunks
# - Extracts content for existing sources
python main.py process-unchunked --limit 100

# Workflow 4: Retry Extraction (run_retry_extraction)
# - Re-extracts content for a SPECIFIC source_id
# - Does NOT create new source, updates existing
python main.py retry-extraction --source-id "uuid-here"
```

**Key Distinction**: Workflows 1 & 2 create sources; Workflows 3 & 4 process existing sources.

### 2. Multi-Selector Extraction System

The crawler handles **two different DRE URL structures** using selector-based routing:

```python
# URL Type Detection (crawlers/dre_crawler.py:detect_url_type)
if '/legislacao-consolidada/' in url:
    return 'dr_legislation'  # Table-based consolidated pages
elif '/detalhe/' in url:
    return 'dr_detail'       # Regular law detail pages

# Each selector has its own extraction logic:
# - dr_detail: Uses div#b7-b11-InjectHTMLWrapper for articles
# - dr_legislation: Uses FragmentoDetailTextoCompleto blocks
```

**Critical**: When modifying extraction, identify which selector you're in. See `context/EXTRACTOR_SELECTORS.md` for CSS selectors.

### 3. Database Schema (Agora Schema)

All database operations use the **`agora` schema**, not public:

```python
# Use schema-aware helpers
from lib.supabase_client import get_agora_table

sources_table = get_agora_table('sources')      # agora.sources
chunks_table = get_agora_table('document_chunks')  # agora.document_chunks
```

**Tables Structure**:
- `agora.sources`: One record per law (metadata, URL)
- `agora.document_chunks`: Multiple records per source (articles)
- `agora.background_jobs`: Job tracking for UI notifications

**Critical Pattern**: Workflows 1-3 call `_save_law_to_database()` which UPSERTS sources. Workflow 4 calls `_save_chunks_for_existing_source()` which only INSERTs chunks.

### 4. Job Notification System

All workflows support **optional `--job-id`** for real-time status updates:

```python
# In main.py, every workflow follows this pattern:
job_id = getattr(args, 'job_id', None)
job_status = "FAILED"  # Default to failed
result_message = ""

try:
    result = await workflow_function()
    job_status = "SUCCESS"
    result_message = "Completed successfully"
except Exception as e:
    result_message = str(e)
finally:
    # ALWAYS runs - updates database for UI notifications
    if job_id:
        update_job_status(job_id, job_status, result_message)
```

**Critical**: Use try...finally pattern for new workflows. Never skip the finally block.

## Development Workflows

### Environment Setup
```bash
cd agora-crawler-python
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Required environment variables
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJhbG..."  # Use SERVICE_ROLE, not anon key
```

### Testing Workflows
```bash
# Test specific workflow (no database interaction)
python -m py_compile main.py  # Syntax check

# Test with real database
python main.py retry-extraction --source-id "d7eaa191-fd7b-48ef-9013-33579398d6ad"

# Test job notifications
python test_job_notifications.py
python example_job_flow.py  # End-to-end demo
```

### Debugging Extraction Issues

1. **Check URL Type**: Is it `dr_detail` or `dr_legislation`?
   ```python
   from crawlers.dre_crawler import detect_url_type
   print(detect_url_type(url))
   ```

2. **Inspect Page Structure**: Use browser DevTools on the DRE page to verify selectors still work.

3. **Test Selectors**: See `context/SELECTOR_QUICKREF.md` for current CSS selectors.

4. **Check Logs**: Look for emoji markers:
   - 🔍 = Selector detection
   - ✅ = Success
   - ❌ = Failure
   - 📋/📄 = Extraction steps

## Project-Specific Conventions

### File Organization
```
agora-crawler-python/
├── main.py                    # CLI entry point (argparse subcommands)
├── crawlers/
│   └── dre_crawler.py         # All 4 workflows + extraction logic (~1800 lines)
├── lib/
│   └── supabase_client.py     # Singleton pattern for DB connection
├── test_job_notifications.py  # Automated tests for job system
└── example_job_flow.py         # End-to-end demo

context/                        # Documentation (NOT code)
├── EXTRACTOR_SELECTORS.md      # Multi-selector architecture
├── JOB_NOTIFICATIONS_*.md      # Job system docs
└── WORKFLOW4_*.md              # Workflow 4 deep-dive
```

### Code Patterns

**1. Async/Await Everywhere**: All extraction uses Playwright's async API
```python
async def extract_something(page):
    await page.wait_for_selector('h1')
    title = await page.locator('h1').text_content()
```

**2. CSS Selector Fallbacks**: Always try multiple selectors
```python
selectors = ['h1[data-expression]', 'h1.document-title', 'h1']
for selector in selectors:
    if await page.locator(selector).count() > 0:
        return await page.locator(selector).first.text_content()
```

**3. Proper Locator Awaiting**: Common mistake to avoid
```python
# ❌ WRONG - Can't await locator.first directly
elem = await block.locator('.selector').first

# ✅ CORRECT - Check count, then await text_content()
locator = block.locator('.selector')
if await locator.count() > 0:
    text = await locator.first.text_content()
```

**4. Database Operations Use Schema**: Always specify `agora` schema
```python
# ❌ WRONG
supabase.table('sources').select('*')

# ✅ CORRECT
supabase.schema('agora').table('sources').select('*')
# OR use helper:
get_agora_table('sources').select('*')
```

### GitHub Actions Integration

Workflows are triggered via `workflow_dispatch` with inputs. See `.github/workflows/crawler.yml`:

```yaml
# Each workflow has conditional execution based on crawler_mode input
- name: Run Workflow 1 - Extract URL
  if: env.WORKFLOW == 'extract-url'
  run: python main.py extract-url --url "$URL"
```

**Critical**: When adding workflow parameters, update both `main.py` argparse AND GitHub Actions workflow file.

## Common Pitfalls & Solutions

### Issue: "Could not extract law title"
- **Cause**: Wrong selector for URL type
- **Solution**: Check `detect_url_type(url)` output, verify selectors in `context/EXTRACTOR_SELECTORS.md`

### Issue: "No articles extracted" 
- **Cause**: Page structure changed or wrong selector
- **Solution**: Inspect page HTML, update CSS selectors in appropriate `_extract_articles_*()` function

### Issue: Job status not updating
- **Cause**: Missing SERVICE_ROLE_KEY or job_id not passed
- **Solution**: Verify env vars, check finally block executes

### Issue: Duplicate sources created
- **Cause**: Using Workflow 1 instead of Workflow 4 for retry
- **Solution**: Use `retry-extraction` for existing sources, not `extract-url`

## Integration Points

### Supabase Database
- **Connection**: Singleton pattern via `get_supabase_client()`
- **Authentication**: Uses SERVICE_ROLE_KEY (bypasses RLS)
- **Schema**: All tables in `agora` schema
- **Real-time**: Job status updates trigger Supabase real-time subscriptions in Next.js

### Next.js Frontend (Pending Integration)
- See `context/NEXTJS_INTEGRATION_CHECKLIST.md` for complete integration steps
- Frontend should call `agora.create_new_job()` then trigger GitHub Action with returned job_id

## When Adding New Features

1. **New Workflow**: Add to `main.py` as new subcommand, implement in `dre_crawler.py`, update GitHub Actions workflow
2. **New Selector**: Add to `detect_url_type()`, create `extract_with_X_selector()` function, update routing in `_extract_and_save_law_details()`
3. **New Database Table**: Access via `get_agora_table('table_name')`, ensure schema migration exists in `context/`

## Documentation References

- **Architecture**: `context/EXTRACTOR_SELECTORS.md` (multi-selector design)
- **Workflows**: `agora-crawler-python/README.md` (usage examples)
- **Job System**: `context/JOB_NOTIFICATIONS_README.md` (notification flow)
- **Testing**: `test_job_notifications.py` and `example_job_flow.py`

## Quick Reference Commands

```bash
# Syntax validation
python -m py_compile main.py

# Test workflows
python main.py extract-url --url "https://..."
python main.py discover-sources --start-date "2025-04-03" --end-date "2025-04-03" --type "Lei"
python main.py process-unchunked --limit 10
python main.py retry-extraction --source-id "uuid-here"

# With job tracking
python main.py extract-url --url "..." --job-id "job-uuid"

# Test job notifications
python test_job_notifications.py
python example_job_flow.py --fail

# Run in Docker (production)
docker build -t agora-dre-crawler .
docker run --env-file .env agora-dre-crawler
```

---

**Last Updated**: October 4, 2025  
**Project Status**: Multi-selector architecture complete, job notifications implemented, Next.js integration pending
