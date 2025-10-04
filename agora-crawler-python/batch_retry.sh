#!/bin/bash

# =============================================================================
# Batch Retry Extraction Script
# =============================================================================
# This script helps you retry extraction for multiple sources that failed
# to have their content extracted during initial crawling.
#
# Usage:
#   ./batch_retry.sh [options]
#
# Options:
#   -f, --file FILE       Read source IDs from file (one per line)
#   -l, --limit N         Process only first N sources (default: all)
#   -d, --delay SECONDS   Delay between retries in seconds (default: 2)
#   -v, --verbose         Enable verbose output
#   -h, --help            Show this help message
#
# Example:
#   ./batch_retry.sh --file source_ids.txt --limit 10 --delay 3
# =============================================================================

set -e  # Exit on error

# Default values
SOURCE_FILE=""
LIMIT=0
DELAY=2
VERBOSE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--file)
            SOURCE_FILE="$2"
            shift 2
            ;;
        -l|--limit)
            LIMIT="$2"
            shift 2
            ;;
        -d|--delay)
            DELAY="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        -h|--help)
            echo "Batch Retry Extraction Script"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  -f, --file FILE       Read source IDs from file (one per line)"
            echo "  -l, --limit N         Process only first N sources (default: all)"
            echo "  -d, --delay SECONDS   Delay between retries in seconds (default: 2)"
            echo "  -v, --verbose         Enable verbose output"
            echo "  -h, --help            Show this help message"
            echo ""
            echo "Example:"
            echo "  $0 --file source_ids.txt --limit 10 --delay 3"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Function to print colored messages
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Validate inputs
if [[ -z "$SOURCE_FILE" ]]; then
    log_error "Source file is required. Use --file to specify."
    log_info "Example: $0 --file source_ids.txt"
    exit 1
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
    log_error "Source file not found: $SOURCE_FILE"
    exit 1
fi

# Check if Python script exists
if [[ ! -f "$SCRIPT_DIR/main.py" ]]; then
    log_error "main.py not found in $SCRIPT_DIR"
    exit 1
fi

# Count total sources
TOTAL_SOURCES=$(wc -l < "$SOURCE_FILE" | tr -d ' ')

if [[ $TOTAL_SOURCES -eq 0 ]]; then
    log_warning "Source file is empty: $SOURCE_FILE"
    exit 0
fi

# Apply limit if specified
if [[ $LIMIT -gt 0 ]] && [[ $LIMIT -lt $TOTAL_SOURCES ]]; then
    PROCESS_COUNT=$LIMIT
else
    PROCESS_COUNT=$TOTAL_SOURCES
fi

# Print configuration
log_info "=========================================="
log_info "Batch Retry Extraction Configuration"
log_info "=========================================="
log_info "Source file: $SOURCE_FILE"
log_info "Total sources in file: $TOTAL_SOURCES"
log_info "Sources to process: $PROCESS_COUNT"
log_info "Delay between retries: ${DELAY}s"
log_info "Verbose mode: $([[ $VERBOSE -eq 1 ]] && echo "enabled" || echo "disabled")"
log_info "=========================================="
echo ""

# Confirm before proceeding
read -p "Proceed with batch retry? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warning "Batch retry cancelled by user"
    exit 0
fi

# Initialize counters
SUCCESS_COUNT=0
FAILURE_COUNT=0
PROCESSED_COUNT=0

# Create log file
LOG_FILE="batch_retry_$(date +%Y%m%d_%H%M%S).log"
log_info "Logging to: $LOG_FILE"
echo ""

# Process each source ID
while IFS= read -r source_id || [[ -n "$source_id" ]]; do
    # Skip empty lines and comments
    if [[ -z "$source_id" ]] || [[ "$source_id" =~ ^[[:space:]]*# ]]; then
        continue
    fi
    
    # Trim whitespace
    source_id=$(echo "$source_id" | xargs)
    
    # Check limit
    PROCESSED_COUNT=$((PROCESSED_COUNT + 1))
    if [[ $LIMIT -gt 0 ]] && [[ $PROCESSED_COUNT -gt $LIMIT ]]; then
        log_info "Reached limit of $LIMIT sources"
        break
    fi
    
    # Print progress
    log_info "[$PROCESSED_COUNT/$PROCESS_COUNT] Processing source: $source_id"
    
    # Run retry extraction
    if [[ $VERBOSE -eq 1 ]]; then
        python "$SCRIPT_DIR/main.py" retry-extraction --source-id "$source_id" 2>&1 | tee -a "$LOG_FILE"
        RESULT=${PIPESTATUS[0]}
    else
        python "$SCRIPT_DIR/main.py" retry-extraction --source-id "$source_id" >> "$LOG_FILE" 2>&1
        RESULT=$?
    fi
    
    # Check result
    if [[ $RESULT -eq 0 ]]; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        log_success "Successfully processed source: $source_id"
    else
        FAILURE_COUNT=$((FAILURE_COUNT + 1))
        log_error "Failed to process source: $source_id (see log for details)"
    fi
    
    # Delay between requests (except for last one)
    if [[ $PROCESSED_COUNT -lt $PROCESS_COUNT ]]; then
        if [[ $VERBOSE -eq 1 ]]; then
            log_info "Waiting ${DELAY}s before next retry..."
        fi
        sleep "$DELAY"
    fi
    
    echo ""
    
done < "$SOURCE_FILE"

# Print summary
echo ""
log_info "=========================================="
log_info "Batch Retry Extraction Summary"
log_info "=========================================="
log_info "Total processed: $PROCESSED_COUNT"
log_success "Successful: $SUCCESS_COUNT"
log_error "Failed: $FAILURE_COUNT"
log_info "Success rate: $(awk "BEGIN {printf \"%.1f\", ($SUCCESS_COUNT/$PROCESSED_COUNT)*100}")%"
log_info "Log file: $LOG_FILE"
log_info "=========================================="

# Exit with error code if any failures
if [[ $FAILURE_COUNT -gt 0 ]]; then
    exit 1
else
    exit 0
fi
