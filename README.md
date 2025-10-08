# Agora DRE Crawler - Multi-Workflow System

A production-ready, modular web crawler for the Diário da República (DRE) that supports four distinct workflows for discovering, extracting, and processing Portuguese legal documents.

## 🚀 Features

- **🎯 Workflow 1**: Direct URL extraction for immediate content processing
- **🗺️ Workflow 2**: Source discovery with advanced search form interaction
- **⚙️ Workflow 3**: Batch processing of unchunked sources
- **🔄 Workflow 4**: Retry extraction for existing sources
- **🔔 Job Notifications**: Real-time job status updates for user notifications (NEW!)
- **🎯 Multi-Selector Extraction**: Handles different URL types automatically
- **🌐 Translation Support**: Ready for Portuguese-English translation
- **📊 Database Integration**: Agora schema with sources and document_chunks
- **🏃‍♂️ GitHub Actions**: Automated workflows with manual and scheduled triggers


## 📋 Usage

### Workflow 1: Direct URL Extraction
Extract content from a specific law URL:
```bash
python main.py extract-url --url "https://diariodarepublica.pt/dr/detalhe/lei/2-2025-902120309"
```

### Workflow 2: Source Discovery
Discover laws within a date range:
```bash
python main.py discover-sources --start-date "2025-04-03" --end-date "2025-04-03" --type "Lei"
```

Available law types: `Lei`, `Decreto-Lei`, `Portaria`, `Despacho`, `Resolução`

### Workflow 3: Process Unchunked Sources
Process sources that haven't had their content extracted:
```bash
python main.py process-unchunked --limit 100
```

### Workflow 4: Retry Extraction for Existing Source
Retry content extraction for a source that was created but has no document chunks:
```bash
python main.py retry-extraction --source-id "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

**Use Case**: When a URL extraction workflow (Workflow 1 or 2) created a source record but failed during content extraction, leaving the source without any document chunks. This workflow allows you to retry the extraction using the existing source ID instead of creating a duplicate source.

**Key Differences from Workflow 1**:
- Does **NOT** create a new source record
- Uses an existing `source_id` from the database
- Fetches the `main_url` from the existing source
- Only inserts document chunks, preserving the original source metadata

### Job Notifications (All Workflows)
All workflows support the `--job-id` parameter for real-time status updates:
```bash
python main.py extract-url --url "..." --job-id "uuid-here"
python main.py discover-sources --start-date "..." --end-date "..." --type "Lei" --job-id "uuid-here"
python main.py process-unchunked --limit 100 --job-id "uuid-here"
python main.py retry-extraction --source-id "..." --job-id "uuid-here"
```

**How it works**:
1. Next.js creates a job record and gets a `job_id`
2. GitHub Action runs the crawler with `--job-id`
3. Crawler updates job status on completion (SUCCESS or FAILED)
4. Next.js listens for real-time updates and notifies the user

📖 **See full documentation**: [Job Notifications Guide](./README_JOB_NOTIFICATIONS.md)

## 🏗️ Architecture

### Project Structure
```
agora-crawler-python/
├── crawlers/
│   ├── __init__.py
│   └── dre_crawler.py      # Main crawler logic
├── lib/
│   ├── __init__.py
│   └── supabase_client.py  # Supabase singleton client
├── main.py                 # Entry point
├── Dockerfile              # Container configuration
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
└── deploy.sh              # Deployment script
```

### Crawling Strategy
1. **URL Generation**: Creates search URLs for each year (1976-2024) filtering for Série I, Lei and Decreto-Lei
2. **Search Results**: Extracts law detail page links from search results
3. **Law Extraction**: Scrapes metadata and article content from individual law pages
4. **Database Storage**: UPSERTs law metadata and INSERTs content chunks

### Data Flow
```
Search URLs → Law Links → Law Details → Database
     ↓            ↓            ↓            ↓
  49 URLs     ~1000+ links  Metadata +    agora.sources
  (1976-2024)               Articles       agora.document_chunks
```

## 📊 Database Schema

### Sources Table (`agora.sources`)
- `id`: UUID primary key
- `type_id`: "OFFICIAL_PUBLICATION"
- `author`: "Diário da República"
- `main_url`: Law detail page URL
- `is_official_document`: true
- `translations`: Portuguese metadata

### Document Chunks (`agora.document_chunks`)
- `id`: UUID primary key
- `source_id`: Foreign key to sources
- `chunk_index`: Article order
- `content`: Article text content

## ⚙️ Configuration

### Environment Variables
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: Service role key for database access
- `CRAWLER_START_YEAR`: First year to crawl (default: 1976)
- `CRAWLER_END_YEAR`: Last year to crawl (default: 2024)

### Crawler Settings
- **Concurrency**: Automatically managed by Crawlee
- **Retries**: Built-in retry logic for failed requests
- **Rate Limiting**: Respects website limits
- **Error Handling**: Graceful failure recovery

## 🔍 Monitoring & Logs

The crawler provides detailed logging:
- URL processing status
- Extraction results
- Database operation outcomes
- Error handling and retries

Example output:
```
Extracted from https://diariodarepublica.pt/dr/detalhe/...:
Official Number: Lei n.º 7/2009
Official Title: Lei n.º 7/2009
Number of Articles: 45
Successfully ingested 45 articles for Lei n.º 7/2009
```

## 🚀 Production Deployment

### Docker Deployment
```bash
# Build image
docker build -t agora-dre-crawler .

# Run with environment file
docker run --env-file .env --rm agora-dre-crawler

# Run with explicit env vars
docker run -e SUPABASE_URL=$SUPABASE_URL -e SUPABASE_SERVICE_ROLE_KEY=$KEY --rm agora-dre-crawler
```

### Kubernetes Deployment
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: agora-dre-crawler
spec:
  template:
    spec:
      containers:
      - name: crawler
        image: agora-dre-crawler
        envFrom:
        - secretRef:
            name: supabase-secrets
      restartPolicy: Never
```

### CI/CD Integration
The crawler can be integrated into CI/CD pipelines for scheduled execution:
- Weekly/monthly runs to capture new publications
- Incremental updates based on date ranges
- Automated deployment with infrastructure as code

## 🛠️ Development

### Adding New Selectors
Update the extraction methods in `dre_crawler.py`:
```python
async def _extract_official_number(self, page) -> str | None:
    selectors = ["h1", ".new-selector", "[data-field='number']"]
    # ... extraction logic
```

### Testing
```bash
# Test URL generation
python -c "from crawlers.dre_crawler import DRECrawler; c = DRECrawler(2020,2020); print('Test passed')"

# Test with single URL
# Modify add_start_urls() to use test URL temporarily
```

### Debugging
- Enable verbose logging by setting `LOG_LEVEL=DEBUG`
- Use browser developer tools to inspect DRE page structure
- Test selectors individually with Playwright

## 📈 Performance

### Expected Runtime
- **Full crawl (1976-2024)**: 2-4 hours depending on network and site load
- **Annual crawl**: ~5-10 minutes
- **Single law**: ~30 seconds

### Resource Usage
- **Memory**: ~500MB peak
- **CPU**: 1-2 cores
- **Network**: ~50MB data transfer for full crawl

### Optimization Tips
- Run during off-peak hours (European night time)
- Use multiple instances for different year ranges
- Implement caching for already processed laws

## 🔒 Security

- Service role key provides full database access
- No sensitive data stored in container
- Environment variables for all configuration
- Isolated execution in Docker containers

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Test changes locally
4. Submit a pull request

## 📝 License

This project is part of the Agora platform. See main project license for details.