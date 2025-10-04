import asyncio
import argparse
import sys
import os
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
    
    Args:
        job_id: UUID of the job to update
        status: Job status ('SUCCESS' or 'FAILED')
        result_message: Message describing the result
    """
    if not job_id:
        return  # No job ID provided, skip update
    
    try:
        supabase = get_supabase_client()
        supabase.table("background_jobs").update({
            "status": status,
            "result_message": result_message,
            "updated_at": "now()"
        }).eq("id", job_id).execute()
        print(f"📝 Updated job {job_id} to status: {status}")
    except Exception as e:
        print(f"⚠️  Warning: Failed to update job status: {str(e)}")


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
