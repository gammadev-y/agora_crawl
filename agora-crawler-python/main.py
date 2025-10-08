import asyncio
import argparse
import sys
import os
import json
from datetime import datetime, date
from typing import List

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Add the project root to Python path for imports
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from crawlers.dre_crawler import (
    run_single_url_crawl,
    run_discovery_crawl,
    run_unchunked_processing,
    run_retry_extraction
)
from lib.supabase_client import get_supabase_client


def update_job_status(job_id: str, status: str, result_message: str):
    """
    Update the status of a background job in the database.
    
    **IMPORTANT**: This is a non-critical, optional feature for UI notifications.
    If job status updates fail, the crawler continues normally. Job notifications
    should NEVER prevent data extraction and persistence.
    
    Args:
        job_id: UUID of the job to update (optional)
        status: Job status ('SUCCESS' or 'FAILED')
        result_message: Message describing the result
    """
    if not job_id:
        return  # No job ID provided, skip update
    
    try:
        supabase = get_supabase_client()
        supabase.schema('agora').table("background_jobs").update({
            "status": status,
            "result_message": result_message,
            "updated_at": datetime.now().isoformat()
        }).eq("id", job_id).execute()
        print(f"📝 Updated job {job_id} to status: {status}")
    except Exception as e:
        # Job notification failures are non-critical - log and continue
        print(f"⚠️  Warning: Job notification failed (non-critical): {str(e)}")


def parse_date(date_string: str) -> date:
    """Parse date string in YYYY-MM-DD format"""
    try:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_string}. Use YYYY-MM-DD format.")


def validate_date_range(start_date: date, end_date: date):
    """Validate that start_date is not after end_date"""
    if start_date > end_date:
        raise ValueError("Start date must be before or equal to end date")


def handle_describe_workflows(args):
    """
    Handle the describe-workflows command.
    
    This command outputs a JSON manifest describing all available crawler workflows.
    The manifest is consumed by the Agora Next.js frontend to dynamically build
    the UI for triggering crawls.
    
    This is the single source of truth for workflow definitions.
    """
    workflows = [
        {
            "id": "extract-url",
            "name": "Extract Content from URL",
            "description": "Performs a deep extraction on a single, specific law URL. Creates or updates the source record with full metadata (translations, slug, authors) and extracts all articles as document chunks.",
            "workflow_number": 1,
            "inputs": [
                {
                    "id": "url",
                    "label": "Law URL",
                    "type": "text",
                    "required": True,
                    "placeholder": "https://diariodarepublica.pt/dr/detalhe/lei/...",
                    "help_text": "Direct URL to a law detail page on Diário da República"
                },
                {
                    "id": "job_id",
                    "label": "Job ID (Optional)",
                    "type": "text",
                    "required": False,
                    "placeholder": "UUID for job tracking",
                    "help_text": "Optional UUID for background job status tracking"
                }
            ],
            "output": "Creates/updates one source record with full metadata and associated document chunks"
        },
        {
            "id": "discover-sources",
            "name": "Discover New Sources",
            "description": "Scans a date range for new laws of a specific type and creates basic source records. This is a two-stage process: discovery creates sources, then use process-unchunked to extract content.",
            "workflow_number": 2,
            "inputs": [
                {
                    "id": "start_date",
                    "label": "Start Date",
                    "type": "date",
                    "required": True,
                    "placeholder": "YYYY-MM-DD",
                    "help_text": "Start date for the search range (inclusive)"
                },
                {
                    "id": "end_date",
                    "label": "End Date",
                    "type": "date",
                    "required": True,
                    "placeholder": "YYYY-MM-DD",
                    "help_text": "End date for the search range (inclusive)"
                },
                {
                    "id": "law_type",
                    "label": "Law Type",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "Lei", "label": "Lei (Law)"},
                        {"value": "Decreto-Lei", "label": "Decreto-Lei (Decree-Law)"},
                        {"value": "Portaria", "label": "Portaria (Ordinance)"},
                        {"value": "Resolução", "label": "Resolução (Resolution)"},
                        {"value": "Despacho", "label": "Despacho (Dispatch)"},
                        {"value": "Decreto", "label": "Decreto (Decree)"}
                    ],
                    "help_text": "Type of legal document to search for"
                },
                {
                    "id": "job_id",
                    "label": "Job ID (Optional)",
                    "type": "text",
                    "required": False,
                    "placeholder": "UUID for job tracking",
                    "help_text": "Optional UUID for background job status tracking"
                }
            ],
            "output": "Multiple source records with basic metadata (no content chunks yet)"
        },
        {
            "id": "process-unchunked",
            "name": "Process Unchunked Sources",
            "description": "Finds sources in the database without content chunks and extracts them. Use this after discover-sources or to retry failed extractions in batch.",
            "workflow_number": 3,
            "inputs": [
                {
                    "id": "limit",
                    "label": "Number of Sources",
                    "type": "number",
                    "required": True,
                    "default": 100,
                    "min": 1,
                    "max": 1000,
                    "placeholder": "100",
                    "help_text": "Maximum number of sources to process in this batch"
                },
                {
                    "id": "job_id",
                    "label": "Job ID (Optional)",
                    "type": "text",
                    "required": False,
                    "placeholder": "UUID for job tracking",
                    "help_text": "Optional UUID for background job status tracking"
                }
            ],
            "output": "Extracts content for multiple sources, creating document chunks for each"
        },
        {
            "id": "retry-extraction",
            "name": "Retry Extraction for Source",
            "description": "Re-runs the full extraction process for a specific source ID. Updates the source metadata and re-extracts all content chunks. Useful for fixing failed extractions or updating outdated content.",
            "workflow_number": 4,
            "inputs": [
                {
                    "id": "source_id",
                    "label": "Source ID",
                    "type": "text",
                    "required": True,
                    "placeholder": "UUID of the source",
                    "help_text": "The UUID of the source to retry extraction for (found in agora.sources table)"
                },
                {
                    "id": "job_id",
                    "label": "Job ID (Optional)",
                    "type": "text",
                    "required": False,
                    "placeholder": "UUID for job tracking",
                    "help_text": "Optional UUID for background job status tracking"
                }
            ],
            "output": "Updates existing source record and re-creates all document chunks"
        }
    ]
    
    # Output the manifest as JSON
    print(json.dumps(workflows, indent=2))
    return True


async def handle_extract_url(args):
    """Handle the extract-url command (Workflow 1)"""
    url = args.url
    
    print(f"🔗 Starting direct URL extraction: {url}")
    
    try:
        success = await run_single_url_crawl(url)
        print(f"🔍 DEBUG: run_single_url_crawl returned: {success} (type: {type(success)})")
        if success:
            print("✅ Direct URL extraction completed successfully!")
            return True
        else:
            print("❌ Direct URL extraction failed!")
            return False
    except Exception as e:
        print(f"❌ Error during direct URL extraction: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def handle_discover_sources(args):
    """Handle the discover-sources command (Workflow 2)"""
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    law_type = args.type
    validate_date_range(start_date, end_date)
    
    print(f"🗺️  Starting source discovery from {start_date} to {end_date} for type: {law_type}")
    
    try:
        discovered_count = await run_discovery_crawl(start_date, end_date, law_type)
        print(f"✅ Source discovery completed! Discovered {discovered_count} sources.")
        return True
    except Exception as e:
        print(f"❌ Error during source discovery: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def handle_process_unchunked(args):
    """Handle the process-unchunked command (Workflow 3)"""
    limit = args.limit
    
    print(f"⚙️  Starting unchunked processing (limit: {limit})")
    
    try:
        processed_count = await run_unchunked_processing(limit)
        print(f"✅ Unchunked processing completed! Processed {processed_count} sources.")
        return True
    except Exception as e:
        print(f"❌ Error during unchunked processing: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def handle_retry_extraction(args):
    """Handle the retry-extraction command (Workflow 4)"""
    source_id = args.source_id
    
    print(f"🔄 Starting retry extraction for source ID: {source_id}")
    
    try:
        success = await run_retry_extraction(source_id)
        if success:
            print("✅ Retry extraction completed successfully!")
            return True
        else:
            print("❌ Retry extraction failed!")
            return False
    except Exception as e:
        print(f"❌ Error during retry extraction: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def setup_parser():
    """Set up the command-line argument parser with sub-commands for PROD5 workflows"""
    
    # Main parser
    parser = argparse.ArgumentParser(
        description='Agora DRE Crawler - Multi-Workflow CLI Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s extract-url --url "https://diariodarepublica.pt/dr/detalhe/lei/2-2025-902120309" --job-id "uuid-here"
  %(prog)s discover-sources --start-date 2025-04-03 --end-date 2025-04-03 --type "Lei" --job-id "uuid-here"
  %(prog)s process-unchunked --limit 100 --job-id "uuid-here"
  %(prog)s retry-extraction --source-id "a1b2c3d4-e5f6-7890-abcd-ef1234567890" --job-id "uuid-here"
        """)
    
    # Create sub-parsers for different workflows
    subparsers = parser.add_subparsers(
        dest='command',
        help='Available crawling workflows',
        required=True
    )
    
    # Sub-parser for describe-workflows (Manifest Generator)
    parser_describe = subparsers.add_parser(
        'describe-workflows',
        help='Output the workflow manifest as JSON'
    )
    parser_describe.set_defaults(func=handle_describe_workflows)
    
    # Sub-parser for extract-url (Workflow 1)
    parser_extract_url = subparsers.add_parser(
        'extract-url',
        help='Extract content from a specific law detail URL'
    )
    parser_extract_url.add_argument(
        '--url',
        type=str,
        required=True,
        help='Direct URL to a law detail page'
    )
    parser_extract_url.add_argument(
        '--job-id',
        type=str,
        required=False,
        help='UUID of the background job (for status tracking)'
    )
    parser_extract_url.set_defaults(func=handle_extract_url)
    
    # Sub-parser for discover-sources (Workflow 2)
    parser_discover_sources = subparsers.add_parser(
        'discover-sources',
        help='Discover and populate sources within a date range and law type'
    )
    parser_discover_sources.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date in YYYY-MM-DD format'
    )
    parser_discover_sources.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='End date in YYYY-MM-DD format'
    )
    parser_discover_sources.add_argument(
        '--type',
        type=str,
        required=True,
        choices=['Lei', 'Decreto-Lei', 'Portaria', 'Despacho', 'Resolução'],
        help='Type of law document'
    )
    parser_discover_sources.add_argument(
        '--job-id',
        type=str,
        required=False,
        help='UUID of the background job (for status tracking)'
    )
    parser_discover_sources.set_defaults(func=handle_discover_sources)
    
    # Sub-parser for process-unchunked (Workflow 3)
    parser_process_unchunked = subparsers.add_parser(
        'process-unchunked',
        help='Process sources that have not yet had their content extracted'
    )
    parser_process_unchunked.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Maximum number of sources to process (default: 100)'
    )
    parser_process_unchunked.add_argument(
        '--job-id',
        type=str,
        required=False,
        help='UUID of the background job (for status tracking)'
    )
    parser_process_unchunked.set_defaults(func=handle_process_unchunked)
    
    # Sub-parser for retry-extraction (Workflow 4)
    parser_retry_extraction = subparsers.add_parser(
        'retry-extraction',
        help='Retry extraction for a specific source that failed previously'
    )
    parser_retry_extraction.add_argument(
        '--source-id',
        type=str,
        required=True,
        help='UUID of the source to retry extraction for'
    )
    parser_retry_extraction.add_argument(
        '--job-id',
        type=str,
        required=False,
        help='UUID of the background job (for status tracking)'
    )
    parser_retry_extraction.set_defaults(func=handle_retry_extraction)
    
    return parser


async def main():
    """Main entry point for the CLI application"""
    
    # Set up argument parsing
    parser = setup_parser()
    args = parser.parse_args()
    
    # Special case: describe-workflows is synchronous and outputs JSON only
    if args.command == 'describe-workflows':
        args.func(args)
        return
    
    # Print header
    print("🚀 Agora DRE Crawler - Multi-Workflow CLI Tool")
    print("=" * 50)
    
    # Initialize job tracking variables
    job_id = getattr(args, 'job_id', None)
    job_status = "FAILED"
    result_message = ""
    
    try:
        # Execute the appropriate handler based on the command
        result = await args.func(args)
        
        # Handle workflow-specific success/failure logic
        if args.command == 'extract-url':
            if not result:
                result_message = "Workflow 1 (extract-url) failed"
                print(f"❌ {result_message}")
                sys.exit(1)
            else:
                result_message = "Workflow 1 (extract-url) completed successfully"
        elif args.command == 'discover-sources':
            if not result:
                result_message = "Workflow 2 (discover-sources) failed"
                print(f"❌ {result_message}")
                sys.exit(1)
            else:
                result_message = "Workflow 2 (discover-sources) completed successfully"
        elif args.command == 'process-unchunked':
            if not result:
                result_message = "Workflow 3 (process-unchunked) failed"
                print(f"❌ {result_message}")
                sys.exit(1)
            else:
                result_message = "Workflow 3 (process-unchunked) completed successfully"
        elif args.command == 'retry-extraction':
            if not result:
                result_message = "Workflow 4 (retry-extraction) failed"
                print(f"❌ {result_message}")
                sys.exit(1)
            else:
                result_message = "Workflow 4 (retry-extraction) completed successfully"
        
        # If we reached here, the workflow succeeded
        job_status = "SUCCESS"
        print("🎉 All operations completed successfully!")
        
    except KeyboardInterrupt:
        result_message = "Crawling interrupted by user"
        print(f"\n❌ {result_message}")
        sys.exit(1)
        
    except Exception as e:
        result_message = f"Unexpected error during crawling: {str(e)}"
        print(f"❌ {result_message}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        # Always update job status if job_id was provided
        if job_id:
            update_job_status(job_id, job_status, result_message)


if __name__ == "__main__":
    asyncio.run(main())
