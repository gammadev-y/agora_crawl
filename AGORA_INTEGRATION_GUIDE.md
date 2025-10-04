# Agora DRE Crawler - Integration Documentation

**Last Updated:** October 4, 2025  
**Project Repository:** [github.com/gammadev-y/agora_crawl](https://github.com/gammadev-y/agora_crawl)  
**Status:** ✅ Production Ready

---

## 🎯 Project Overview

The **Agora DRE Crawler** is a multi-workflow web crawler designed to extract Portuguese legal documents from the Diário da República (DRE) website. It integrates with the Agora platform by storing extracted content in Supabase PostgreSQL database using the `agora` schema.

### Key Features

- **4 Independent Workflows** for different use cases
- **Multi-Selector Extraction** handles different DRE URL structures automatically
- **Job Notification System** for real-time status updates
- **Supabase Integration** with `agora.sources` and `agora.document_chunks` tables
- **GitHub Actions CI/CD** with manual triggers and scheduled runs

---

## 📋 Available Workflows

### Workflow 1: Extract URL (`extract-url`)

**Purpose:** Extract content from a specific law URL immediately

**Use Case:** When you have a direct URL to a law and want to extract its content right away

**Command:**
```bash
python main.py extract-url --url "https://diariodarepublica.pt/dr/detalhe/lei/26-2007-636772"
```

**With Job Tracking:**
```bash
python main.py extract-url --url "URL_HERE" --job-id "uuid-here"
```

**Database Operations:**
- Creates or updates a record in `agora.sources`
- Creates multiple records in `agora.document_chunks` (one per article)
- Updates `agora.background_jobs` if `job-id` provided

**Test Results:**
- ✅ Successfully tested with Lei n.º 26/2007
- ✅ Extracted 4 articles
- ✅ Saved to database with source ID: `1edefc7a-e9fd-4611-830c-e900d2d11e7d`

---

### Workflow 2: Discover Sources (`discover-sources`)

**Purpose:** Search and catalog laws within a date range without extracting content

**Use Case:** Building an index of available laws for later processing

**Command:**
```bash
python main.py discover-sources \
  --start-date "2025-01-01" \
  --end-date "2025-01-31" \
  --type "Lei"
```

**Available Law Types:**
- `Lei` (Law)
- `Decreto-Lei` (Decree-Law)
- `Portaria` (Ordinance)
- `Despacho` (Dispatch)
- `Resolução` (Resolution)

**Database Operations:**
- Creates records in `agora.sources` with URL but NO content
- Does NOT create `document_chunks` (two-stage process)
- Updates `agora.background_jobs` if `job-id` provided

---

### Workflow 3: Process Unchunked (`process-unchunked`)

**Purpose:** Extract content for sources that were discovered but not yet processed

**Use Case:** Second stage after discovery - processes the backlog of unchunked sources

**Command:**
```bash
python main.py process-unchunked --limit 100
```

**Database Operations:**
- Finds sources with NO `document_chunks`
- Extracts content and creates `document_chunks`
- Updates `agora.background_jobs` if `job-id` provided

---

### Workflow 4: Retry Extraction (`retry-extraction`)

**Purpose:** Re-extract content for a specific source that failed previously

**Use Case:** When extraction failed or needs to be retried without creating duplicate sources

**Command:**
```bash
python main.py retry-extraction --source-id "1edefc7a-e9fd-4611-830c-e900d2d11e7d"
```

**Database Operations:**
- Uses existing source record (does NOT create new source)
- Attempts to create `document_chunks`
- Updates `agora.background_jobs` if `job-id` provided

**Important Notes:**
- Will warn if chunks already exist (prevents accidental duplicates)
- Does NOT delete existing chunks before retry
- Use for failed extractions, not for updating content

**Test Results:**
- ✅ Successfully detected existing chunks and prevented duplicates
- ✅ Warning system works correctly

---

## 🔧 GitHub Actions Integration

The crawler is fully integrated with GitHub Actions for automated execution.

### Workflow File Location

```
.github/workflows/crawler.yml
```

### Manual Trigger Inputs

| Input | Description | Required | Type | Default |
|-------|-------------|----------|------|---------|
| `crawler_mode` | Workflow to execute | Yes | Choice | `discover-sources` |
| `url` | URL for extract-url | No | String | - |
| `start_date` | Start date (YYYY-MM-DD) | No | String | `2025-01-01` |
| `end_date` | End date (YYYY-MM-DD) | No | String | `2025-01-01` |
| `law_type` | Law type for discovery | No | Choice | `Lei` |
| `limit` | Limit for unchunked processing | No | String | `100` |
| `source_id` | Source ID for retry | No | String | - |
| `job_id` | Job ID for tracking | No | String | - |

### Scheduled Run

- **Schedule:** Daily at 3:00 AM UTC
- **Workflow:** `discover-sources`
- **Date Range:** Previous day (yesterday)
- **Law Type:** `Lei`

### Required Secrets

Configure these in GitHub repository settings under **Settings → Secrets and variables → Actions**:

| Secret Name | Description |
|-------------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (bypasses RLS) |
| `SUPABASE_ANON_KEY` | Anonymous key (optional) |

---

## 🗄️ Database Schema Integration

### Table: `agora.sources`

**Purpose:** Stores metadata about legal documents

**Key Columns:**
- `id` (UUID, Primary Key) - Generated by crawler
- `main_url` (String) - URL to the DRE page
- `source_entity_id` (UUID, Foreign Key) - Link to emitting entity
- `type_id` (String) - Document type identifier
- `published_at` (Timestamp) - Publication date
- `translations` (JSONB) - Portuguese and English metadata
  - `pt.title` - Portuguese title
  - `pt.description` - Portuguese description
  - `en.title` - English title (if available)
  - `en.description` - English description (if available)

### Table: `agora.document_chunks`

**Purpose:** Stores individual articles from legal documents

**Key Columns:**
- `id` (UUID, Primary Key) - Generated by database
- `source_id` (UUID, Foreign Key) - References `agora.sources.id`
- `chunk_index` (Integer) - Article number (0-based)
- `content` (Text) - Article content
- `chunk_metadata` (JSONB) - Additional metadata
  - `article_number` - Original article numbering
  - `article_type` - Type of content section

**Unique Constraint:**
- `unique_chunk_for_source` on (`source_id`, `chunk_index`)
- Prevents duplicate articles for the same source

### Table: `agora.background_jobs` (Optional)

**Purpose:** Track job execution status for UI notifications

**Usage:** Pass `--job-id` parameter to any workflow

---

## 🚀 Agora Platform Integration Guide

### Step 1: Backend Integration (Next.js Server Actions)

Create a server action to trigger the crawler:

```typescript
// app/actions/crawler.ts
'use server'

import { createClient } from '@/lib/supabase/server'

export async function triggerCrawler(
  workflowType: 'extract-url' | 'discover-sources' | 'process-unchunked' | 'retry-extraction',
  params: {
    url?: string
    startDate?: string
    endDate?: string
    lawType?: string
    limit?: number
    sourceId?: string
  }
) {
  const supabase = createClient()
  
  // 1. Create a job record
  const { data: job, error } = await supabase
    .rpc('create_new_job', {
      p_job_type: `crawler-${workflowType}`,
      p_payload: params
    })
  
  if (error) throw error
  
  // 2. Trigger GitHub Action workflow
  const response = await fetch(
    'https://api.github.com/repos/gammadev-y/agora_crawl/actions/workflows/crawler.yml/dispatches',
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.GITHUB_PAT}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ref: 'main',
        inputs: {
          crawler_mode: workflowType,
          job_id: job.id,
          ...params
        }
      })
    }
  )
  
  if (!response.ok) {
    throw new Error('Failed to trigger crawler workflow')
  }
  
  return { jobId: job.id }
}
```

### Step 2: Frontend Integration (React Component)

Monitor job status in real-time:

```typescript
// components/CrawlerStatus.tsx
'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { triggerCrawler } from '@/app/actions/crawler'

export function CrawlerStatus() {
  const [jobId, setJobId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('idle')
  const supabase = createClient()

  useEffect(() => {
    if (!jobId) return

    // Subscribe to job status updates
    const channel = supabase
      .channel('job-updates')
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'agora',
          table: 'background_jobs',
          filter: `id=eq.${jobId}`
        },
        (payload) => {
          setStatus(payload.new.status)
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [jobId])

  const handleExtractUrl = async (url: string) => {
    const { jobId } = await triggerCrawler('extract-url', { url })
    setJobId(jobId)
    setStatus('PENDING')
  }

  return (
    <div>
      <button onClick={() => handleExtractUrl('https://...')}>
        Extract Law
      </button>
      {status !== 'idle' && <p>Status: {status}</p>}
    </div>
  )
}
```

### Step 3: Environment Variables

Add to your `.env.local`:

```bash
# GitHub Personal Access Token (with workflow permissions)
GITHUB_PAT=ghp_xxxxxxxxxxxxx

# Supabase credentials (already configured)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbG...
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...
```

---

## 🧪 Testing & Validation

### Test URLs

**Working Test Case:**
```bash
# Lei n.º 26/2007 - Successfully extracts 4 articles
https://diariodarepublica.pt/dr/detalhe/lei/26-2007-636772
```

**Known Issue:**
```bash
# Decreto n.º 16563/1929 - Content wrapper not found (historical document)
https://diariodarepublica.pt/dr/detalhe/decreto/16563-1929-358735
```

### Manual Testing Commands

```bash
# Test direct extraction
cd agora-crawler-python
source venv/bin/activate
python main.py extract-url --url "URL_HERE"

# Test discovery
python main.py discover-sources \
  --start-date "2025-01-01" \
  --end-date "2025-01-01" \
  --type "Lei"

# Test retry
python main.py retry-extraction --source-id "SOURCE_ID_HERE"
```

---

## 🔍 Troubleshooting

### Issue: GitHub Actions workflow not visible

**Cause:** Workflow file was in wrong directory (`agora-crawler-python/.github/workflows/`)

**Solution:** ✅ Fixed - Moved to `.github/workflows/crawler.yml` at repository root

### Issue: No articles extracted

**Cause:** Page structure changed or historical document with different format

**Solution:** Check URL type detection and selector in `crawlers/dre_crawler.py`

### Issue: Duplicate chunks error

**Cause:** Trying to retry extraction on source that already has chunks

**Solution:** This is expected behavior - Workflow 4 prevents duplicates automatically

---

## 📊 Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agora Next.js App                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Server Action: triggerCrawler()                          │  │
│  │  1. Create job in agora.background_jobs                   │  │
│  │  2. Trigger GitHub Action via API                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                           │                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  React Component: CrawlerStatus                           │  │
│  │  - Subscribe to Supabase real-time                        │  │
│  │  - Display job status to user                             │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                      GitHub Actions                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  .github/workflows/crawler.yml                            │  │
│  │  - Set up Python environment                              │  │
│  │  - Install dependencies & Playwright                      │  │
│  │  - Execute workflow (1, 2, 3, or 4)                       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                   agora-crawler-python/                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  main.py - CLI entry point                                │  │
│  │  ├─ extract-url (Workflow 1)                              │  │
│  │  ├─ discover-sources (Workflow 2)                         │  │
│  │  ├─ process-unchunked (Workflow 3)                        │  │
│  │  └─ retry-extraction (Workflow 4)                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  crawlers/dre_crawler.py                                  │  │
│  │  - Multi-selector extraction logic                        │  │
│  │  - Playwright browser automation                          │  │
│  │  - Article parsing & chunking                             │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Supabase PostgreSQL                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  agora.sources                                            │  │
│  │  - Law metadata                                           │  │
│  │  - URL, title, publication date                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  agora.document_chunks                                    │  │
│  │  - Individual articles                                    │  │
│  │  - Linked to source via source_id                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  agora.background_jobs                                    │  │
│  │  - Job tracking & status updates                          │  │
│  │  - Real-time subscription support                         │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📝 Next Steps for Agora Integration

1. **Configure GitHub Secrets**
   - Add `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY` to repository settings

2. **Test GitHub Actions**
   - Go to **Actions** tab in GitHub
   - Run workflow manually with test data
   - Verify logs and database entries

3. **Implement Server Action**
   - Create `app/actions/crawler.ts` in Agora Next.js
   - Add GitHub PAT to environment variables
   - Test job creation and workflow triggering

4. **Build UI Components**
   - Create crawler trigger buttons
   - Add real-time status monitoring
   - Display extracted laws in admin panel

5. **Production Deployment**
   - Set up scheduled daily discovery runs
   - Monitor job success/failure rates
   - Configure alerts for failed extractions

---

## 📞 Support & Maintenance

**Repository:** [github.com/gammadev-y/agora_crawl](https://github.com/gammadev-y/agora_crawl)

**Documentation:**
- `.github/copilot-instructions.md` - Complete technical documentation
- `agora-crawler-python/README.md` - Usage examples
- `context/` folder (excluded from git) - Development notes

**Deployment:**
- GitHub Actions for CI/CD
- Docker support via `Dockerfile` and `docker-compose.yml`
- Can be deployed to any container platform (AWS ECS, Google Cloud Run, etc.)

---

**Document Version:** 1.0  
**Last Tested:** October 4, 2025  
**Production Status:** ✅ Ready for integration
