"""
Agora DRE Crawler - PROD5 Multi-Workflow Implementation
======================================================

This module provides four distinct workflows for crawling Portuguese legal documents:

1. run_single_url_crawl(url) - Direct URL extraction (Workflow 1)
2. run_discovery_crawl(start_date, end_date, law_type) - Source discovery (Workflow 2)
3. run_unchunked_processing(limit) - Process unchunked sources (Workflow 3)
4. run_retry_extraction(source_id) - Retry extraction for existing sources (Workflow 4)

All workflows use shared functions for translation and content extraction.

Content Extraction Architecture:
--------------------------------
The extractor supports multiple URL types through a selector-based system:
- dr_detail: Regular law detail pages (/dr/detalhe/...)
- dr_legislation: Consolidated legislation pages (/dr/legislacao-consolidada/...)

Each selector implements specific extraction rules optimized for its URL pattern.
"""

import asyncio
import re
import sys
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

from crawlee.crawlers import PlaywrightCrawler
from crawlee.router import Router
from playwright.async_api import async_playwright

# Add the project root to Python path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from lib.supabase_client import get_supabase_client, get_agora_table


# ============================================================================
# URL TYPE DETECTION & SELECTOR ROUTING
# ============================================================================

def detect_url_type(url: str) -> str:
    """
    Detect the type of DRE URL to determine which extraction selector to use.
    
    Args:
        url: The URL to analyze
        
    Returns:
        Selector type: 'dr_detail', 'dr_legislation', or 'unknown'
    """
    if not url:
        return 'unknown'
    
    # Normalize URL
    url_lower = url.lower()
    
    # Check for consolidated legislation URLs
    if '/legislacao-consolidada/' in url_lower:
        return 'dr_legislation'
    
    # Check for regular detail URLs
    if '/detalhe/' in url_lower:
        return 'dr_detail'
    
    # Default to unknown
    return 'unknown'


# ============================================================================
# SELECTOR-SPECIFIC EXTRACTION IMPLEMENTATIONS
# ============================================================================

async def extract_with_dr_detail_selector(page) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Extract content using dr_detail selector for regular law detail pages.
    URL pattern: /dr/detalhe/...
    
    Args:
        page: Playwright page object
        
    Returns:
        Tuple of (law_metadata, articles_list)
    """
    print("🔍 Using dr_detail selector for extraction")
    
    try:
        # Extract metadata using current implementation
        law_data = await _extract_law_metadata_dr_detail(page)
        if not law_data or not law_data.get('official_title'):
            print("⚠️  Could not extract law title with dr_detail selector")
            return None, []
        
        # Extract articles using current implementation
        articles = await _extract_articles_dr_detail(page)
        
        print(f"✅ dr_detail selector extracted {len(articles)} articles")
        return law_data, articles
        
    except Exception as e:
        print(f"❌ Error in dr_detail selector: {str(e)}")
        return None, []


async def extract_with_dr_legislation_selector(page) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Extract content using dr_legislation selector for consolidated legislation pages.
    URL pattern: /dr/legislacao-consolidada/...
    
    Args:
        page: Playwright page object
        
    Returns:
        Tuple of (law_metadata, articles_list)
    """
    print("🔍 Using dr_legislation selector for extraction")
    
    try:
        # Extract metadata from consolidated legislation page
        law_data = await _extract_law_metadata_dr_legislation(page)
        if not law_data or not law_data.get('official_title'):
            print("⚠️  Could not extract law title with dr_legislation selector")
            return None, []
        
        # Extract articles from consolidated legislation structure
        articles = await _extract_articles_dr_legislation(page)
        
        print(f"✅ dr_legislation selector extracted {len(articles)} articles")
        return law_data, articles
        
    except Exception as e:
        print(f"❌ Error in dr_legislation selector: {str(e)}")
        return None, []


# ============================================================================
# SHARED TRANSLATION FUNCTIONALITY
# ============================================================================
async def _translate_text(text: str) -> dict:
    """
    Translate text to English using googletrans-py library.

    Args:
        text: The Portuguese text to translate

    Returns:
        Dictionary with 'en' and 'pt' keys containing translations
    """
    if not text or not text.strip():
        return {'en': '', 'pt': ''}

    try:
        # TODO: Implement actual translation with googletrans-py
        # For now, return Portuguese text as-is and mark English as [Translation needed]
        return {
            'en': f'[EN] {text}',  # Placeholder - should be actual translation
            'pt': text
        }
    except Exception as e:
        print(f"⚠️  Translation error: {str(e)}")
        return {
            'en': text,  # Fallback to original text
            'pt': text
        }


async def _extract_and_save_law_details(page, url: str) -> bool:
    """
    Core extractor function with multi-selector routing.
    
    This function detects the URL type and routes to the appropriate
    extraction selector (dr_detail or dr_legislation).
    
    Used by Workflow 1, Workflow 3, and Workflow 4.
    
    Args:
        page: Playwright page object positioned on a law detail page
        url: The URL of the page being processed
        
    Returns:
        True if successful, False otherwise
    """
    print(f"📖 Extracting law details from: {url}")

    try:
        # Wait for content to load
        await page.wait_for_load_state('networkidle', timeout=60000)
        await page.wait_for_timeout(5000)

        # Try to wait for any dynamic content
        try:
            await page.wait_for_selector('h1, h2, .document-title', timeout=10000)
        except:
            print("⚠️  No expected selectors found, continuing anyway")

        # Detect URL type and route to appropriate selector
        url_type = detect_url_type(url)
        print(f"🔍 Detected URL type: {url_type}")
        
        law_data = None
        articles = []
        
        if url_type == 'dr_detail':
            law_data, articles = await extract_with_dr_detail_selector(page)
        elif url_type == 'dr_legislation':
            law_data, articles = await extract_with_dr_legislation_selector(page)
        else:
            print(f"⚠️  Unknown URL type: {url_type}, attempting dr_detail selector as fallback")
            law_data, articles = await extract_with_dr_detail_selector(page)
        
        if not law_data or not law_data.get('official_title'):
            print("⚠️  Could not extract law title with any selector")
            return False

        print(f"📋 Found title: {law_data['official_title'][:80]}...")
        print(f"📄 Extracted {len(articles)} articles")

        # Save to database
        success = await _save_law_to_database(law_data, articles, url)

        if success:
            print(f"✅ Successfully processed: {law_data['official_title'][:50]}...")
            print(f"📄 Saved {len(articles)} content chunks")
            return True
        else:
            print(f"❌ Failed to save: {law_data['official_title'][:50]}...")
            return False

    except Exception as e:
        print(f"❌ Error extracting law details from {url}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def _extract_law_metadata_dr_detail(page) -> Optional[Dict]:
    """
    Extract law metadata from dr_detail pages (regular law detail pages).
    This is the original implementation for /dr/detalhe/ URLs.
    """
    law_data = {}
    
    # Extract official title
    title_selectors = [
        'h1[data-advancedhtml] span[data-expression]',
        'h1.document-title', 
        'h1',
        '.document-title'
    ]
    
    for selector in title_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                law_data['official_title'] = await page.locator(selector).nth(0).text_content()
                break
        except:
            continue
    
    if not law_data.get('official_title'):
        return None
    
    # Extract emitting entity
    emitting_selectors = [
        'div#b7-Emissor2 span[data-expression]',
        '.emitting-entity',
        '.entity'
    ]
    
    for selector in emitting_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                law_data['emitting_entity_name'] = await page.locator(selector).nth(0).text_content()
                break
        except:
            continue
    
    # Extract publication date
    date_selectors = [
        'div#b7-DataPublicacao2 span[data-expression]',
        '.publication-date',
        '.date'
    ]
    
    for selector in date_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                law_data['publication_date'] = await page.locator(selector).nth(0).text_content()
                break
        except:
            continue
    
    # Extract summary
    summary_selectors = [
        'div#b7-Sumario_Conteudo4 div[data-container]',
        '.summary',
        '.sumario'
    ]
    
    for selector in summary_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                law_data['summary'] = await page.locator(selector).nth(0).text_content()
                break
        except:
            continue
    
    # Parse law type from title
    title = law_data['official_title']
    if 'Decreto-Lei' in title:
        law_data['law_type_name'] = 'Decreto-Lei'
    elif 'Lei' in title:
        law_data['law_type_name'] = 'Lei'
    elif 'Portaria' in title:
        law_data['law_type_name'] = 'Portaria'
    elif 'Despacho' in title:
        law_data['law_type_name'] = 'Despacho'
    
    # Parse official number from title
    number_match = re.search(r'n\.º\s*([\d/]+[A-Z]?)', title, re.IGNORECASE)
    if number_match:
        law_data['official_number'] = number_match.group(1)
    
    return law_data


async def _extract_law_metadata_dr_legislation(page) -> Optional[Dict]:
    """
    Extract law metadata from dr_legislation pages (consolidated legislation pages).
    URL pattern: /dr/legislacao-consolidada/...
    
    These pages have a different structure focused on consolidated versions.
    """
    law_data = {}
    
    # Extract official title from consolidated legislation page
    title_selectors = [
        # Main title in header section
        'div#Designacao h1 span[data-expression]',
        'h1 span.heading1',
        'h1',
    ]
    
    for selector in title_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                law_data['official_title'] = await page.locator(selector).nth(0).text_content()
                if law_data['official_title']:
                    break
        except:
            continue
    
    if not law_data.get('official_title'):
        return None
    
    # For consolidated legislation, extract the base law type from title
    title = law_data['official_title']
    if 'Decreto' in title and 'Aprovação' in title:
        law_data['law_type_name'] = 'Decreto de Aprovação da Constituição'
    elif 'Constituição' in title:
        law_data['law_type_name'] = 'Constituição'
    elif 'Decreto-Lei' in title:
        law_data['law_type_name'] = 'Decreto-Lei'
    elif 'Lei' in title:
        law_data['law_type_name'] = 'Lei'
    
    # Extract publication info from metadata section
    date_selectors = [
        'div#Modificado span[data-expression]',
        '.publication-info'
    ]
    
    for selector in date_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                pub_info = await page.locator(selector).nth(0).text_content()
                law_data['publication_date'] = pub_info
                break
        except:
            continue
    
    # Extract the document type from page structure
    doc_type_selectors = [
        'div#ConteudoTitle span[data-expression]',
        'div.document-type'
    ]
    
    for selector in doc_type_selectors:
        try:
            if (await page.locator(selector).count()) > 0:
                doc_type = await page.locator(selector).nth(0).text_content()
                if doc_type and not law_data.get('law_type_name'):
                    law_data['law_type_name'] = doc_type
                break
        except:
            continue
    
    return law_data


# ============================================================================
# DR_DETAIL SELECTOR: Article Extraction (Original Implementation)
# ============================================================================

async def _extract_articles_dr_detail(page) -> List[Dict]:
    """
    Extract articles using dr_detail selector.
    This is the original _extract_article_content_smart implementation.
    """
    return await _extract_article_content_smart(page)


async def _extract_article_content_smart(page) -> List[Dict]:
    """
    Enhanced article content extraction following ParseDR.md guidelines.
    
    Implements semantic HTML parsing with proper table detection,
    article structure recognition, and Markdown conversion.
    
    Returns:
        List of article dictionaries with structured content
    """
    articles = []

    try:
        # Phase 1: Semantic HTML Detection - Find the main content wrapper
        # Try multiple OutSystems InjectHTMLWrapper patterns (different versions use different IDs)
        wrapper_selectors = [
            'div#b7-b11-InjectHTMLWrapper',  # Modern DRE pages
            'div#b7-b7-InjectHTMLWrapper',   # Older/alternate DRE pages
            'div[id$="-InjectHTMLWrapper"]', # Any InjectHTMLWrapper
            'div.texto_sumario',              # Summary text container
            '.content-wrapper',
            '.law-content',
            '#content',
            'main'
        ]
        
        wrapper_selector = None
        for selector in wrapper_selectors:
            if (await page.locator(selector).count()) > 0:
                wrapper_selector = selector
                print(f"✅ Found content wrapper: {selector}")
                break
        
        if not wrapper_selector:
            print("❌ No suitable content wrapper found")
            return []

        print(f"📋 Using content wrapper: {wrapper_selector}")

        # Phase 2: Extract structured content following ParseDR.md patterns
        structured_content = await _extract_structured_content(page, wrapper_selector)
        
        # Phase 3: Process into articles
        if structured_content:
            articles = await _process_content_into_articles(structured_content)
        
        print(f"📄 Extracted {len(articles)} articles using enhanced ParseDR methodology")
        return articles

    except Exception as e:
        print(f"❌ Error in enhanced content extraction: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


async def _extract_structured_content(page, wrapper_selector: str) -> str:
    """
    Extract and convert content to structured Markdown following ParseDR.md guidelines.
    
    Args:
        page: Playwright page object
        wrapper_selector: CSS selector for the content wrapper
        
    Returns:
        Structured Markdown content
    """
    try:
        markdown_content = []
        
        # Get all elements within the wrapper
        all_elements = await page.locator(f'{wrapper_selector} *').all()
        
        # Fallback: If wrapper has no child elements, get its direct text content
        # This handles older documents that contain plain text without structured HTML
        if not all_elements:
            print("📝 No child elements found, extracting plain text content")
            wrapper_text = await page.locator(wrapper_selector).text_content()
            if wrapper_text and wrapper_text.strip():
                return wrapper_text.strip()
            return ""
        
        for element in all_elements:
            try:
                # Get element details
                tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                class_name = await element.get_attribute('class') or ''
                text_content = await element.text_content()
                
                if not text_content or not text_content.strip():
                    continue
                
                text_content = text_content.strip()
                
                # Phase 1: Table Detection (class="Tbl1")
                if tag_name == 'table' and 'Tbl1' in class_name:
                    table_markdown = await _convert_table_to_markdown(element)
                    if table_markdown:
                        markdown_content.append(table_markdown)
                    continue
                
                # Phase 2: Document Structure Extraction
                if tag_name == 'p':
                    markdown_line = await _convert_paragraph_to_markdown(element, class_name, text_content)
                    if markdown_line:
                        markdown_content.append(markdown_line)
                        
            except Exception as e:
                print(f"⚠️  Error processing element: {str(e)}")
                continue
        
        # If no structured content was found but we have elements, try getting direct text
        result = '\n\n'.join(markdown_content) if markdown_content else ""
        if not result:
            print("⚠️  No structured content extracted, trying direct text fallback")
            wrapper_text = await page.locator(wrapper_selector).text_content()
            if wrapper_text and wrapper_text.strip():
                return wrapper_text.strip()
        
        return result
        
    except Exception as e:
        print(f"❌ Error extracting structured content: {str(e)}")
        return ""


async def _convert_paragraph_to_markdown(element, class_name: str, text_content: str) -> str:
    """Convert paragraph elements to appropriate Markdown format based on ParseDR.md patterns."""
    try:
        # Title Level 1 (Document Title)
        if 'paragraph-title-bold-center-18px' in class_name:
            return f"# {text_content}"
        
        # Title Level 2 (Subtitle)
        elif 'paragraph-bold-center' in class_name:
            return f"## {text_content}"
        
        # Title Level 3 (Article Number)
        elif 'paragraph-center' in class_name and text_content.startswith('Artigo'):
            return f"### {text_content}"
        
        # Title Level 4 (Article Subtitle)
        elif 'paragraph-bold-center-14px' in class_name:
            return f"#### {text_content}"
        
        # Italic right (reference numbers)
        elif 'paragraph-italic-right' in class_name:
            return f"*{text_content}*"
        
        # Normal paragraphs
        elif 'paragraph-normal-text' in class_name or 'paragraph' in class_name:
            # Check for links within the paragraph
            links = await element.locator('a').all()
            if links:
                # Process links and convert to Markdown format
                processed_text = text_content
                for link in links:
                    try:
                        link_text = await link.text_content()
                        href = await link.get_attribute('href')
                        title = await link.get_attribute('title')
                        
                        if href and link_text:
                            # Convert to absolute URL if relative
                            if href.startswith('/'):
                                href = f"https://diariodarepublica.pt{href}"
                            
                            # Create Markdown link
                            if title:
                                markdown_link = f"[{link_text}]({href} \"{title}\")"
                            else:
                                markdown_link = f"[{link_text}]({href})"
                            
                            processed_text = processed_text.replace(link_text, markdown_link)
                    except:
                        continue
                
                return processed_text
            else:
                return text_content
        
        # Fallback for other paragraph types
        elif text_content and len(text_content) > 10:
            return text_content
        
        return ""
        
    except Exception as e:
        print(f"⚠️  Error converting paragraph: {str(e)}")
        return text_content


async def _convert_table_to_markdown(table_element) -> str:
    """Convert HTML table to Markdown format following ParseDR.md guidelines."""
    try:
        # Extract table structure
        rows = await table_element.locator('tr').all()
        if not rows:
            return ""
        
        markdown_rows = []
        header_processed = False
        
        for row in rows:
            cells = await row.locator('td, th').all()
            if not cells:
                continue
            
            cell_contents = []
            for cell in cells:
                cell_text = await cell.text_content()
                cell_text = (cell_text or "").strip().replace('\n', ' ')
                cell_contents.append(cell_text)
            
            # Create markdown row
            markdown_row = "| " + " | ".join(cell_contents) + " |"
            markdown_rows.append(markdown_row)
            
            # Add header separator after first row
            if not header_processed:
                separator = "| " + " | ".join(["---"] * len(cell_contents)) + " |"
                markdown_rows.append(separator)
                header_processed = True
        
        return '\n'.join(markdown_rows)
        
    except Exception as e:
        print(f"⚠️  Error converting table: {str(e)}")
        return ""


async def _process_content_into_articles(structured_content: str) -> List[Dict]:
    """Process structured Markdown content into individual articles."""
    try:
        articles = []
        
        # Split content by article markers
        article_sections = structured_content.split('### Artigo')
        
        # If no article markers found, treat entire content as a single chunk
        # This handles older documents or summaries without article structure
        if len(article_sections) == 1 and article_sections[0].strip():
            print("📝 No article markers found, treating content as single document chunk")
            return [{
                'article_number': 0,
                'content': article_sections[0].strip()
            }]
        
        # Handle content before first article (introduction, title, etc.)
        if article_sections[0].strip():
            articles.append({
                'article_number': 0,
                'content': article_sections[0].strip()
            })
        
        # Process each article
        for i, section in enumerate(article_sections[1:], 1):
            if section.strip():
                # Re-add the article marker that was removed by split
                article_content = f"### Artigo{section}"
                articles.append({
                    'article_number': i,
                    'content': article_content.strip()
                })
        
        return articles
        
    except Exception as e:
        print(f"❌ Error processing articles: {str(e)}")
        # Fallback: return all content as single article
        return [{
            'article_number': 0,
            'content': structured_content
        }] if structured_content.strip() else []


# ============================================================================
# DR_LEGISLATION SELECTOR: Article Extraction (New Implementation)
# ============================================================================

async def _extract_articles_dr_legislation(page) -> List[Dict]:
    """
    Extract articles from consolidated legislation pages.
    URL pattern: /dr/legislacao-consolidada/...
    
    These pages display articles in a table structure with specific classes:
    - Fragmento_Titulo: Article number (e.g., "Artigo 12.º")
    - Fragmento_Epigrafe: Article title/epigraph
    - Fragmento_Texto: Article content
    """
    articles = []
    
    try:
        print("📋 Extracting articles from consolidated legislation table structure")
        
        # Find all article blocks within the table
        # Each article is in a table row with the FragmentoDetailTextoCompleto block
        article_blocks = await page.locator('div[data-block="LegislacaoConsolidada.FragmentoDetailTextoCompleto"]').all()
        
        if not article_blocks:
            print("⚠️  No article blocks found with FragmentoDetailTextoCompleto selector")
            return []
        
        print(f"📄 Found {len(article_blocks)} potential article blocks")
        
        for idx, block in enumerate(article_blocks):
            try:
                # Extract article number
                article_number = ""
                article_number_locator = block.locator('.Fragmento_Titulo span[data-expression]')
                if await article_number_locator.count() > 0:
                    article_number = await article_number_locator.first.text_content() or ""
                    article_number = article_number.strip()
                
                # Extract article title/epigraph
                article_title = ""
                article_title_locator = block.locator('.Fragmento_Epigrafe')
                if await article_title_locator.count() > 0:
                    article_title = await article_title_locator.first.text_content() or ""
                    article_title = article_title.strip()
                
                # Extract article content
                article_content = ""
                article_content_locator = block.locator('.Fragmento_Texto')
                if await article_content_locator.count() > 0:
                    article_content = await article_content_locator.first.text_content() or ""
                    article_content = article_content.strip()
                
                # Skip if no meaningful content
                if not article_content and not article_title and not article_number:
                    continue
                
                # Build structured markdown content
                markdown_parts = []
                
                if article_number:
                    markdown_parts.append(f"### {article_number}")
                
                if article_title:
                    markdown_parts.append(f"**{article_title}**")
                
                if article_content:
                    markdown_parts.append(article_content)
                
                full_content = "\n\n".join(markdown_parts)
                
                # Parse article number for database storage
                parsed_article_num = idx + 1  # Default to sequential numbering
                if article_number:
                    # Try to extract numeric part from "Artigo 12.º" format
                    num_match = re.search(r'(\d+)', article_number)
                    if num_match:
                        parsed_article_num = int(num_match.group(1))
                
                articles.append({
                    'article_number': parsed_article_num,
                    'content': full_content
                })
                
            except Exception as e:
                print(f"⚠️  Error processing article block {idx}: {str(e)}")
                continue
        
        print(f"✅ Successfully extracted {len(articles)} articles from consolidated legislation page")
        return articles
        
    except Exception as e:
        print(f"❌ Error in dr_legislation article extraction: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


# ============================================================================
# SHARED DATABASE PERSISTENCE
# ============================================================================

async def _save_law_to_database(law_data: Dict, articles: List[Dict], source_url: str) -> bool:
    """Save law and articles to database according to PROD5 specification"""
    try:
        print(f"💾 Starting database persistence for: {law_data['official_title'][:50]}...")
        
        supabase = get_supabase_client()
        
        # Translate content for multilingual support
        title_translations = await _translate_text(law_data['official_title'])
        summary_translations = await _translate_text(law_data.get('summary', ''))
        
        # Construct translations JSONB
        translations = {
            'pt': {
                'title': title_translations['pt'],
                'description': summary_translations['pt']
            },
            'en': {
                'title': title_translations['en'],
                'description': summary_translations['en']
            }
        }
        
        # UPSERT into agora.sources
        source_data = {
            'main_url': source_url,
            'type_id': 'OFFICIAL_PUBLICATION',
            'author': law_data.get('emitting_entity_name'),
            'published_at': law_data.get('publication_date'),
            'credibility_score': 1.0,
            'is_official_document': True,
            'translations': translations,
            'is_active': True
        }
        
        source_result = supabase.schema('agora').table('sources').upsert(source_data).execute()
        
        if not source_result.data:
            print("❌ Failed to create/update source")
            return False
        
        source_id = source_result.data[0]['id']
        print(f"✅ Upserted source with ID: {source_id}")
        
        # Save articles as document chunks
        chunks_saved = 0
        for article in articles:
            chunk_data = {
                'source_id': source_id,
                'chunk_index': article['article_number'],
                'content': article['content']
            }
            
            try:
                supabase.schema('agora').table('document_chunks').insert(chunk_data).execute()
                chunks_saved += 1
            except Exception as e:
                print(f"⚠️  Could not save chunk {article['article_number']}: {str(e)}")
        
        print(f"✅ Saved {chunks_saved} document chunks")
        print(f"🎉 Successfully completed database persistence!")
        return True
        
    except Exception as e:
        print(f"❌ Error in database persistence: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# WORKFLOW 1: Direct URL Extractor
# =============================================================================

async def run_single_url_crawl(url: str) -> bool:
    """
    Workflow 1: Direct URL extraction for immediate, deep content extraction.

    Args:
        url: Direct URL to a law detail page

    Returns:
        True if successful, False otherwise
    """
    print(f"🔗 Starting single URL crawl: {url}")

    success = False
    try:
        # Use direct Playwright instance (no Crawlee needed for single URL)
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )

            page = await browser.new_page()

            try:
                # Navigate to the URL
                await page.goto(url, timeout=60000)

                # Call the shared extraction function
                success = await _extract_and_save_law_details(page, url)

                if success:
                    print("✅ Successfully processed single URL")
                else:
                    print("❌ Failed to process single URL")

            except Exception as e:
                print(f"❌ Error during page processing: {str(e)}")
                success = False
            finally:
                await page.close()

    except Exception as e:
        print(f"❌ Error in single URL crawl setup: {str(e)}")
        success = False

    return success


# =============================================================================
# WORKFLOW 2: Source Discoverer
# =============================================================================

async def run_discovery_crawl(start_date: date, end_date: date, law_type: str) -> int:
    """
    Workflow 2: Discover and populate sources with high-level metadata.
    
    This workflow follows the proper DRE search interaction flow:
    1. Navigate to advanced search page
    2. Check "Atos da 1ª Série" checkbox
    3. Fill in the form with law type and date range
    4. Submit the form to get results
    5. Extract law links and metadata from results
    6. Handle pagination
    
    Args:
        start_date: Start date for discovery
        end_date: End date for discovery
        law_type: Type of law to search for
        
    Returns:
        Number of sources discovered
    """
    print(f"🗺️  Workflow 2: Source Discovery")
    print(f"📅 Date range: {start_date} to {end_date}")
    print(f"📋 Law type: {law_type}")
    
    discovered_count = 0
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Linux; x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            
            print("🔍 Step 1: Navigating to advanced search page...")
            await page.goto('https://diariodarepublica.pt/dr/pesquisa-avancada', wait_until='networkidle')
            
            print("🔍 Step 2: Checking 'Atos da 1ª Série' checkbox...")
            # The checkbox is already checked in the HTML, but let's ensure it's checked
            atos_checkbox = page.locator('#CheckboxAtos5')
            if not await atos_checkbox.is_checked():
                await atos_checkbox.click()
            
            # Wait for the form to be visible
            await page.wait_for_selector('#Input_Tipo', timeout=10000)
            
            print("🔍 Step 3: Filling the search form...")
            
            # Clear and fill the type field
            await page.locator('#Input_Tipo').clear()
            await page.locator('#Input_Tipo').fill(f'"{law_type}"')
            
            # Fill date fields
            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            await page.locator('#Input_DataPublicacaoVar').clear()
            await page.locator('#Input_DataPublicacaoVar').fill(start_date_str)
            
            await page.locator('#Input_DataPublicacaoAteVar').clear()
            await page.locator('#Input_DataPublicacaoAteVar').fill(end_date_str)
            
            print("🔍 Step 4: Submitting the search form...")
            # Click the search button
            await page.locator('button:has-text("Efetuar Pesquisa")').click()
            
            # Wait for results to load
            await page.wait_for_load_state('networkidle')
            
            print("🔍 Step 5: Processing search results...")
            
            # Process multiple pages of results
            page_num = 1
            while True:
                print(f"📄 Processing results page {page_num}...")
                
                # Extract law links from current page
                page_results = await _extract_law_links_from_results_page(page)
                
                if not page_results:
                    print("ℹ️  No more results found")
                    break
                
                # Save discoveries to database
                for law_data in page_results:
                    try:
                        # Perform translation
                        title_translations = await _translate_text(law_data['title'])
                        description_translations = await _translate_text(law_data.get('description', ''))
                        
                        # Construct translations
                        translations = {
                            'pt': {
                                'title': title_translations['pt'],
                                'description': description_translations['pt']
                            },
                            'en': {
                                'title': title_translations['en'],
                                'description': description_translations['en']
                            }
                        }
                        
                        # UPSERT into agora.sources
                        supabase = get_supabase_client()
                        source_data = {
                            'main_url': law_data['url'],
                            'type_id': 'OFFICIAL_PUBLICATION',
                            'author': law_data.get('emitting_entity'),
                            'published_at': law_data.get('publication_date'),
                            'credibility_score': 1.0,
                            'is_official_document': True,
                            'translations': translations,
                            'is_active': True
                        }
                        
                        result = supabase.schema('agora').table('sources').upsert(source_data).execute()
                        
                        if result.data:
                            discovered_count += 1
                            print(f"✅ Discovered ({discovered_count}): {law_data['title'][:60]}...")
                        
                    except Exception as e:
                        print(f"⚠️  Failed to save source: {str(e)}")
                
                # Check for next page
                next_page_found = await _handle_pagination_on_results(page)
                if not next_page_found:
                    break
                
                page_num += 1
                await page.wait_for_load_state('networkidle')
            
            await browser.close()
        
        return discovered_count
        
    except Exception as e:
        print(f"❌ Error in discovery crawl: {str(e)}")
        return discovered_count


async def _extract_law_links_from_results_page(page) -> List[Dict]:
    """Extract law links and metadata from search results page"""
    law_links = []
    
    try:
        # Wait for results to load
        await page.wait_for_timeout(2000)
        
        # First, validate the search results by checking the result count
        result_count = 0
        try:
            result_count_text = await page.locator('span:has-text("resultado(s) encontrado(s)")').text_content()
            if result_count_text:
                import re
                match = re.search(r'(\d+)\s+resultado\(s\)\s+encontrado\(s\)', result_count_text)
                if match:
                    result_count = int(match.group(1))
                    print(f"📊 Expected results: {result_count}")
        except Exception as e:
            print(f"⚠️  Could not parse result count: {e}")
        
        # Target the specific search result links (not navigation/footer links)
        # Based on the HTML analysis, actual results are in table rows with law detail links
        result_links = []
        
        # Look for links within the search results table that point to law details
        table_rows = await page.locator('table tbody tr').all()
        
        for row in table_rows:
            try:
                # Find law detail links within this row - use broader pattern to catch all law types
                links = await row.locator('a[href*="/dr/detalhe/"]').all()
                
                for link in links:
                    href = await link.get_attribute('href')
                    if href and '/dr/detalhe/' in href:
                        # Extract title from the link text or nearby elements
                        title_element = link.locator('span[data-expression]').first
                        if await title_element.count() > 0:
                            title = await title_element.text_content()
                        else:
                            title = await link.text_content()
                        
                        if title and title.strip():
                            # Extract description from the same row
                            description = ""
                            try:
                                # Look for summary/description in the row
                                desc_elements = await row.locator('.info, p, div:has-text(".")').all()
                                for desc_el in desc_elements:
                                    desc_text = await desc_el.text_content()
                                    if desc_text and len(desc_text.strip()) > 20:
                                        # Clean the description by removing the title if it's prepended
                                        clean_desc = desc_text.strip()
                                        if clean_desc.startswith(title.strip()):
                                            # Remove the title part and clean up
                                            clean_desc = clean_desc[len(title.strip()):].strip()
                                            # Remove common separators
                                            clean_desc = clean_desc.lstrip('-').lstrip('—').lstrip('–').strip()
                                        
                                        if clean_desc and len(clean_desc) > 10 and clean_desc != title.strip():
                                            description = clean_desc
                                            break
                            except:
                                pass
                            
                            # Extract publication date from the title/link
                            published_at = None
                            try:
                                import re
                                # Look for date pattern in the title like "Série I de 2025-07-22"
                                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', title)
                                if date_match:
                                    published_at = date_match.group(1)
                                else:
                                    # Try to find date in nearby elements
                                    date_elements = await row.locator('*:has-text("2025-"), *:has-text("2024-")').all()
                                    for date_el in date_elements:
                                        date_text = await date_el.text_content()
                                        if date_text:
                                            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                                            if date_match:
                                                published_at = date_match.group(1)
                                                break
                            except Exception as e:
                                print(f"⚠️  Could not extract date: {e}")
                            
                            # Extract emitting entity
                            emitting_entity = None
                            try:
                                entity_elements = await row.locator('span:has-text("República"), *:has-text("Assembleia"), *:has-text("Governo")').all()
                                for entity_el in entity_elements:
                                    entity_text = await entity_el.text_content()
                                    if entity_text and len(entity_text.strip()) > 5:
                                        emitting_entity = entity_text.strip()
                                        break
                            except:
                                pass
                            
                            # Make absolute URL
                            absolute_url = href if href.startswith('http') else f"https://diariodarepublica.pt{href}"
                            
                            result_links.append({
                                'url': absolute_url,
                                'title': title.strip(),
                                'description': description,
                                'emitting_entity': emitting_entity,
                                'publication_date': published_at
                            })
                            
            except Exception as e:
                print(f"⚠️  Error processing table row: {str(e)}")
                continue
        
        # Remove duplicates while preserving order
        seen_urls = set()
        for law_data in result_links:
            if law_data['url'] not in seen_urls:
                law_links.append(law_data)
                seen_urls.add(law_data['url'])
        
        print(f"🔍 Extracted {len(law_links)} unique law links from results page")
        
        # Validate result count if we extracted any
        if result_count > 0 and len(law_links) != result_count:
            print(f"⚠️  Warning: Expected {result_count} results but extracted {len(law_links)} links")
        
        # Log discovered sources
        for i, law_data in enumerate(law_links, 1):
            title_preview = law_data['title'][:50] + "..." if len(law_data['title']) > 50 else law_data['title']
            print(f"✅ Discovered ({i}): {title_preview}")
            if law_data['publication_date']:
                print(f"📅 Publication date: {law_data['publication_date']}")
        
        return law_links
        
        print(f"🔍 Extracted {len(law_links)} unique law links from results page")
        return law_links
        
    except Exception as e:
        print(f"❌ Error extracting law links: {str(e)}")
        return law_links


async def _handle_pagination_on_results(page) -> bool:
    """Handle pagination on results page, returns True if next page found"""
    try:
        # Look for next page button with various selectors
        next_selectors = [
            'a[title*="seguinte"]',
            'a[title*="Seguinte"]',
            'a[title*="Next"]',
            'a:has-text("Seguinte")',
            'a:has-text(">")',
            '.pagination a.next',
            '.pagination li.next a',
            'a[aria-label*="next"]'
        ]
        
        for selector in next_selectors:
            if await page.locator(selector).count() > 0:
                next_link = page.locator(selector).first
                if await next_link.is_visible() and await next_link.is_enabled():
                    print(f"📄 Found next page button, clicking...")
                    await next_link.click()
                    return True
        
        print("📄 No next page button found")
        return False
        
    except Exception as e:
        print(f"⚠️  Error handling pagination: {str(e)}")
        return False


# =============================================================================
# WORKFLOW 3: Unchunked Processor
# =============================================================================

async def run_unchunked_processing(limit: int = 100) -> int:
    """
    Workflow 3: Process DRE sources that have not yet had their content extracted.
    
    Only processes sources from the DRE domain (diariodarepublica.pt) to ensure
    we're working with official Portuguese legislative documents.
    
    Args:
        limit: Maximum number of sources to process
        
    Returns:
        Number of sources processed
    """
    print(f"⚙️  Workflow 3: Enhanced Unchunked Processing")
    print(f"📊 Processing limit: {limit}")
    
    processed_count = 0
    
    try:
        # Query for sources that need processing
        supabase = get_supabase_client()
        
        # Find sources without document chunks - only process DRE domain URLs
        query = """
        SELECT s.id, s.main_url 
        FROM sources s
        LEFT JOIN document_chunks dc ON s.id = dc.source_id
        WHERE dc.id IS NULL AND s.main_url LIKE '%diariodarepublica.pt%'
        LIMIT %s
        """ % limit
        
        # Use a direct SQL query through RPC or table query
        result = supabase.schema('agora').table('sources').select('id, main_url').like('main_url', '%diariodarepublica.pt%').limit(limit).execute()
        
        # Filter out sources that already have chunks by checking manually
        sources_to_process = []
        for source in result.data:
            # Check if this source has any document chunks
            chunks = supabase.schema('agora').table('document_chunks').select('id').eq('source_id', source['id']).limit(1).execute()
            if not chunks.data:
                sources_to_process.append(source)
                if len(sources_to_process) >= limit:
                    break
        
        print(f"📊 Found {len(sources_to_process)} sources to process")
        
        if not sources_to_process:
            print("✅ No unchunked sources found")
            return 0
        
        # Process each source with appropriate method based on domain
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            
            for source in sources_to_process:
                url = source['main_url']
                print(f"⚙️  Processing source: {url}")
                
                page = await browser.new_page()
                try:
                    # Process DRE source with enhanced extraction
                    print(f"🏛️  Processing DRE source: {url}")
                    await page.goto(url, timeout=60000)
                    success = await _extract_and_save_law_details(page, url)
                    
                    if success:
                        processed_count += 1
                        print(f"✅ Processed {processed_count}/{len(sources_to_process)}: {url}")
                    else:
                        print(f"❌ Failed to process: {url}")
                        
                except Exception as e:
                    print(f"❌ Error processing {url}: {str(e)}")
                finally:
                    await page.close()
            
            await browser.close()
        
        return processed_count
        
    except Exception as e:
        print(f"❌ Error in unchunked processing: {str(e)}")
        return 0


# =============================================================================
# WORKFLOW 4: Retry Extraction for Existing Source
# =============================================================================

async def run_retry_extraction(source_id: str) -> bool:
    """
    Workflow 4: Retry extraction for a source that already exists but has no document chunks.
    
    This workflow is designed for retry scenarios where a source was created
    but content extraction failed, leaving the source without any document chunks.
    Unlike Workflow 1, this workflow does NOT create a new source, but instead
    uses the provided source_id to associate extracted content.
    
    Args:
        source_id: UUID of the existing source to retry extraction for
        
    Returns:
        True if successful, False otherwise
    """
    print(f"🔄 Workflow 4: Retry Extraction")
    print(f"📋 Source ID: {source_id}")
    
    try:
        # Fetch the source from database to get its main_url
        supabase = get_supabase_client()
        
        source_result = supabase.schema('agora').table('sources').select('id, main_url').eq('id', source_id).execute()
        
        if not source_result.data or len(source_result.data) == 0:
            print(f"❌ Source with ID {source_id} not found in database")
            return False
        
        source = source_result.data[0]
        url = source['main_url']
        
        print(f"🔗 Found source URL: {url}")
        
        # Check if source already has document chunks
        chunks_result = supabase.schema('agora').table('document_chunks').select('id').eq('source_id', source_id).limit(1).execute()
        
        if chunks_result.data and len(chunks_result.data) > 0:
            print(f"⚠️  Warning: Source already has {len(chunks_result.data)} document chunks")
            print("This workflow will extract and add new chunks, potentially creating duplicates")
        
        # Extract content using Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            
            page = await browser.new_page()
            
            try:
                # Navigate to the URL
                await page.goto(url, timeout=60000)
                
                # Extract law details using the same extraction logic as Workflow 1
                success = await _extract_and_save_law_details_for_retry(page, url, source_id)
                
                if success:
                    print(f"✅ Successfully retried extraction for source {source_id}")
                else:
                    print(f"❌ Failed to retry extraction for source {source_id}")
                
                return success
                
            except Exception as e:
                print(f"❌ Error during page processing: {str(e)}")
                import traceback
                traceback.print_exc()
                return False
            finally:
                await page.close()
                await browser.close()
        
    except Exception as e:
        print(f"❌ Error in retry extraction: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def _extract_and_save_law_details_for_retry(page, url: str, source_id: str) -> bool:
    """
    Extract law details and save to database for retry scenario.
    
    This is similar to _extract_and_save_law_details but uses an existing source_id
    instead of creating/upserting a new source.
    
    Args:
        page: Playwright page object positioned on a law detail page
        url: The URL of the page being processed
        source_id: The existing source ID to associate chunks with
        
    Returns:
        True if successful, False otherwise
    """
    print(f"📖 Extracting law details for retry from: {url}")

    try:
        # Wait for content to load
        await page.wait_for_load_state('networkidle', timeout=60000)
        await page.wait_for_timeout(5000)

        # Try to wait for any dynamic content
        try:
            await page.wait_for_selector('h1, h2, .document-title', timeout=10000)
        except:
            print("⚠️  No expected selectors found, continuing anyway")

        # Detect URL type and route to appropriate selector
        url_type = detect_url_type(url)
        print(f"🔍 Detected URL type for retry: {url_type}")
        
        law_data = None
        articles = []
        
        if url_type == 'dr_detail':
            law_data, articles = await extract_with_dr_detail_selector(page)
        elif url_type == 'dr_legislation':
            law_data, articles = await extract_with_dr_legislation_selector(page)
        else:
            print(f"⚠️  Unknown URL type: {url_type}, attempting dr_detail selector as fallback")
            law_data, articles = await extract_with_dr_detail_selector(page)
        
        if not law_data or not law_data.get('official_title'):
            print("⚠️  Could not extract law title with any selector")
            return False

        print(f"📋 Found title: {law_data['official_title'][:80]}...")
        print(f"📄 Extracted {len(articles)} articles")

        # Save to database using existing source_id
        success = await _save_chunks_for_existing_source(source_id, articles)

        if success:
            print(f"✅ Successfully processed retry: {law_data['official_title'][:50]}...")
            print(f"📄 Saved {len(articles)} content chunks")
            return True
        else:
            print(f"❌ Failed to save chunks: {law_data['official_title'][:50]}...")
            return False
        
    except Exception as e:
        print(f"❌ Error extracting law details for retry: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def _save_chunks_for_existing_source(source_id: str, articles: List[Dict]) -> bool:
    """
    Save document chunks for an existing source.
    
    This function only saves chunks and does NOT modify the source record.
    
    Args:
        source_id: UUID of the existing source
        articles: List of article dictionaries with 'article_number' and 'content'
        
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"💾 Saving {len(articles)} chunks for existing source {source_id}...")
        
        supabase = get_supabase_client()
        
        # Save articles as document chunks
        chunks_saved = 0
        for article in articles:
            chunk_data = {
                'source_id': source_id,
                'chunk_index': article['article_number'],
                'content': article['content']
            }
            
            try:
                supabase.schema('agora').table('document_chunks').insert(chunk_data).execute()
                chunks_saved += 1
            except Exception as e:
                print(f"⚠️  Could not save chunk {article['article_number']}: {str(e)}")
        
        print(f"✅ Saved {chunks_saved}/{len(articles)} document chunks")
        
        if chunks_saved > 0:
            print(f"🎉 Successfully completed chunk persistence for retry!")
            return True
        else:
            print(f"❌ Failed to save any chunks")
            return False
        
    except Exception as e:
        print(f"❌ Error saving chunks for existing source: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def run_date_range_crawl(start_date: date, end_date: date):
    """
    Mode 1: Crawl laws published within a specific date range.
    
    Uses interactive form automation to search for laws on each date
    and then extracts content from discovered law detail pages.
    
    Args:
        start_date: Start date for crawling
        end_date: End date for crawling (inclusive)
    """
    print(f"🗓️  Starting date range crawl: {start_date} to {end_date}")
    
    # Generate list of dates to process
    date_list = []
    current_date = start_date
    while current_date <= end_date:
        date_list.append(current_date)
        current_date += timedelta(days=1)
    
    print(f"📅 Processing {len(date_list)} dates")
    
    # Process each date
    for date_to_crawl in date_list:
        print(f"\n=== Processing date: {date_to_crawl} ===")
        await process_single_date(date_to_crawl)


async def process_single_date(date_to_crawl: date):
    """Process a single date using interactive form automation"""
    
    # Set up router for form interaction
    form_router = Router()
    
    @form_router.default_handler
    async def handle_search_form(context):
        await handle_search_form_interaction(context, date_to_crawl)
    
    # Create crawler for form interaction
    form_crawler = PlaywrightCrawler(
        max_requests_per_crawl=10,
        browser_launch_options={
            'headless': True,
            'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        }
    )
    form_crawler.router = form_router
    
    # Start with advanced search page
    search_url = "https://diariodarepublica.pt/dr/pesquisa-avancada"
    await form_crawler.run([search_url])


async def handle_search_form_interaction(context, date_to_crawl: date):
    """Handle the advanced search form interaction for a specific date"""
    page = context.page
    
    print(f"🔍 Interacting with search form for date: {date_to_crawl}")
    
    try:
        # Wait for page to load
        await page.wait_for_load_state('networkidle', timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Convert date to form format (DD-MM-YYYY)
        date_str = date_to_crawl.strftime('%d-%m-%Y')
        print(f"📅 Setting date filter to: {date_str}")
        
        # Fill date fields
        await fill_date_fields(page, date_str)
        
        # Select Serie I
        await select_serie_i(page)
        
        # Select document types (Lei and Decreto-Lei)
        await select_document_types(page)
        
        # Submit form
        await submit_search_form(page)
        
        # Wait for results and extract law URLs
        await process_search_results(page)
        
    except Exception as e:
        print(f"❌ Error in search form interaction: {str(e)}")


async def fill_date_fields(page, date_str: str):
    """Fill the date input fields in the search form"""
    try:
        date_selectors = [
            'input[placeholder*="Data"]',
            'input[type="date"]',
            'input[name*="data"]',
            'input[id*="data"]'
        ]
        
        for selector in date_selectors:
            date_inputs = await page.locator(selector).all()
            if len(date_inputs) >= 2:
                print(f"📅 Found date inputs with selector: {selector}")
                await date_inputs[0].fill(date_str)  # From date
                await date_inputs[1].fill(date_str)  # To date
                return
        
        print("⚠️  Could not find date input fields")
        
    except Exception as e:
        print(f"❌ Error filling date fields: {str(e)}")


async def select_serie_i(page):
    """Select Serie I checkbox in the search form"""
    try:
        serie_selectors = [
            'text="Série"',
            'button:has-text("Série")',
            '.accordion-header:has-text("Série")'
        ]
        
        # Try to open Serie section
        for selector in serie_selectors:
            if (await page.locator(selector).count()) > 0:
                await page.locator(selector).nth(0).click()
                await page.wait_for_timeout(1000)
                break
        
        # Select Serie I
        serie_i_selectors = [
            'label:has-text("I")',
            'input[value="I"]',
            'label:has-text("1ª Série")'
        ]
        
        for selector in serie_i_selectors:
            if (await page.locator(selector).count()) > 0:
                print(f"✅ Selecting Série I")
                await page.locator(selector).nth(0).click()
                break
                
    except Exception as e:
        print(f"❌ Error selecting Serie I: {str(e)}")


async def select_document_types(page):
    """Select Lei and Decreto-Lei document types"""
    try:
        # Try to open Tipo de Ato section
        tipo_selectors = [
            'text="Tipo de Ato"',
            'button:has-text("Tipo de Ato")',
            '.accordion-header:has-text("Tipo")'
        ]
        
        for selector in tipo_selectors:
            if (await page.locator(selector).count()) > 0:
                await page.locator(selector).nth(0).click()
                await page.wait_for_timeout(1000)
                break
        
        # Select document types
        document_types = ['Lei', 'Decreto-Lei']
        for doc_type in document_types:
            type_selectors = [
                f'label:has-text("{doc_type}")',
                f'input[value*="{doc_type}"]'
            ]
            
            for selector in type_selectors:
                if (await page.locator(selector).count()) > 0:
                    print(f"✅ Selecting {doc_type}")
                    await page.locator(selector).nth(0).click()
                    await page.wait_for_timeout(500)
                    break
                    
    except Exception as e:
        print(f"❌ Error selecting document types: {str(e)}")


async def submit_search_form(page):
    """Submit the search form"""
    try:
        submit_selectors = [
            'button:has-text("Aplicar")',
            'button:has-text("Pesquisar")',
            'input[type="submit"]',
            '.btn-primary'
        ]
        
        for selector in submit_selectors:
            if (await page.locator(selector).count()) > 0:
                print(f"🔍 Submitting search form")
                await page.locator(selector).nth(0).click()
                return
        
        # Fallback: try Enter key
        await page.keyboard.press('Enter')
        
    except Exception as e:
        print(f"❌ Error submitting form: {str(e)}")


async def process_search_results(page):
    """Process search results and extract law URLs"""
    try:
        # Wait for search results
        await page.wait_for_timeout(5000)
        
        # Look for result links
        result_selectors = [
            '.resultados-pesquisa a',
            '.results a',
            '.search-results a',
            'a[href*="/dr/detalhe/"]'
        ]
        
        law_links = []
        
        for selector in result_selectors:
            links = await page.locator(selector).all()
            if links:
                print(f"🔗 Found {len(links)} links with selector: {selector}")
                
                for link in links:
                    try:
                        href = await link.get_attribute('href')
                        text = await link.text_content()
                        
                        if href and text and any(keyword in text for keyword in ['Lei n.º', 'Decreto-Lei n.º']):
                            absolute_url = href if href.startswith('http') else f"https://diariodarepublica.pt{href}"
                            law_links.append({
                                'url': absolute_url,
                                'text': text.strip()
                            })
                            print(f"📋 Found law: {text.strip()[:80]}...")
                    except:
                        continue
                break
        
        print(f"✅ Total laws found: {len(law_links)}")
        
        # Process each law URL
        for law_link in law_links:
            await process_law_url(law_link['url'])
            
    except Exception as e:
        print(f"❌ Error processing search results: {str(e)}")


async def process_law_url(url: str):
    """Process a single law URL using a direct Playwright instance"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            
            page = await browser.new_page()
            await page.goto(url, timeout=60000)
            
            # Extract law details using shared function
            success = await _extract_and_save_law_details(page, url)
            
            await browser.close()
            
            return success
            
    except Exception as e:
        print(f"❌ Error processing law URL {url}: {str(e)}")
        return None


# NOTE: Legacy code below is kept for reference but should not be used
# Use the multi-workflow implementations at the top of this file instead

async def run_reference_crawl_legacy(law_number: str, law_type: str):
    """
    Mode 3: Crawl by law reference (number and type).
    
    Navigates to the DRE advanced search page, fills the form with the specific
    law reference, and extracts the resulting law content.
    
    Args:
        law_number: Law number (e.g., "7/2009", "123/2024")
        law_type: Type of law document (e.g., "Lei", "Decreto-Lei")
    """
    print(f"📋 Starting reference crawl for {law_type} n.º {law_number}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            
            page = await browser.new_page()
            
            # Navigate to advanced search page
            await page.goto("https://diariodarepublica.pt/dr/pesquisa-avancada", timeout=60000)
            await page.wait_for_load_state('networkidle', timeout=30000)
            
            # Fill reference search form
            await fill_reference_form(page, law_number, law_type)
            
            # Submit and wait for results
            await submit_search_form(page)
            await page.wait_for_timeout(5000)
            
            # Find and click the first result
            result_link = await find_reference_result(page, law_number, law_type)
            
            if result_link:
                await page.goto(result_link, timeout=60000)
                success = await _extract_and_save_law_details(page, result_link)
                
                if success:
                    print(f"✅ Successfully processed reference search")
                else:
                    print(f"❌ Failed to extract law details")
            else:
                print(f"❌ No results found for {law_type} n.º {law_number}")
            
            await browser.close()
            
    except Exception as e:
        print(f"❌ Error in reference crawl: {str(e)}")


async def fill_reference_form(page, law_number: str, law_type: str):
    """Fill the reference search form with specific law number and type"""
    try:
        # Try to find and fill number input
        number_selectors = [
            'input[placeholder*="número"]',
            'input[name*="number"]',
            'input[id*="number"]'
        ]
        
        for selector in number_selectors:
            if (await page.locator(selector).count()) > 0:
                await page.locator(selector).nth(0).fill(law_number)
                print(f"📋 Filled number field with: {law_number}")
                break
        
        # Select law type
        await select_law_type(page, law_type)
        
    except Exception as e:
        print(f"❌ Error filling reference form: {str(e)}")


async def select_law_type(page, law_type: str):
    """Select the specific law type in the form"""
    try:
        # Try to open document type section
        await select_document_types(page)
        
        # Specifically select the requested type
        type_selector = f'label:has-text("{law_type}")'
        if (await page.locator(type_selector).count()) > 0:
            await page.locator(type_selector).nth(0).click()
            print(f"✅ Selected law type: {law_type}")
            
    except Exception as e:
        print(f"❌ Error selecting law type: {str(e)}")


async def find_reference_result(page, law_number: str, law_type: str) -> Optional[str]:
    """Find the specific law result matching the reference"""
    try:
        # Look for links containing the law reference
        links = await page.locator('a[href*="/dr/detalhe/"]').all()
        
        for link in links:
            text = await link.text_content()
            href = await link.get_attribute('href')
            
            if text and href and law_number in text and law_type in text:
                absolute_url = href if href.startswith('http') else f"https://diariodarepublica.pt{href}"
                print(f"🎯 Found matching result: {text.strip()[:80]}...")
                return absolute_url
        
        print(f"⚠️  No matching result found for {law_type} n.º {law_number}")
        return None
        
    except Exception as e:
        print(f"❌ Error finding reference result: {str(e)}")
        return None


# Utility functions for content extraction

async def extract_law_metadata(page) -> Optional[Dict]:
    """Extract law metadata from the page"""
    try:
        # Wait for content to load
        await page.wait_for_load_state('networkidle', timeout=30000)
        await page.wait_for_timeout(3000)  # Additional wait for dynamic content
        
        # Extract title
        title_selectors = ['h1', 'h1.title', '.titulo-principal', '.title', '.law-title', '.documento-titulo', '[class*="titulo"]', '[class*="title"]']
        title = None
        
        for selector in title_selectors:
            if (await page.locator(selector).count()) > 0:
                title = await page.locator(selector).nth(0).text_content()
                break
        
        if not title:
            print("⚠️  Could not find law title")
            return None
        
        # Extract law number from title
        law_number_match = re.search(r'(Lei|Decreto-Lei)\s+n\.º\s*(\d+[A-Z]?/\d+)', title, re.IGNORECASE)
        official_number = law_number_match.group(0) if law_number_match else None
        
        # Determine law type
        law_type = None
        if 'decreto-lei' in title.lower():
            law_type = 'DECRETO_LEI'
        elif 'lei' in title.lower():
            law_type = 'LEI'
        elif 'portaria' in title.lower():
            law_type = 'PORTARIA'
        elif 'despacho' in title.lower():
            law_type = 'DESPACHO'
        
        # Extract emitting entity
        emitting_entity = "Assembleia da República"  # Default
        if 'decreto-lei' in title.lower():
            emitting_entity = "Presidência do Conselho de Ministros"
        
        return {
            'title': title.strip(),
            'official_number': official_number,
            'law_type': law_type,
            'emitting_entity': emitting_entity
        }
        
    except Exception as e:
        print(f"❌ Error extracting metadata: {str(e)}")
        return None


async def extract_article_content_smart(page) -> List[Dict]:
    """
    Extract article content using smart chunking algorithm from PROD2_v2.md.

    The articles are inside div#b7-b11-InjectHTMLWrapper.
    This function implements the smart chunking algorithm:
    - Select all child elements within the InjectHTMLWrapper
    - Loop through elements, starting new article when text starts with "Artigo"
    - Append text content to current article

    Returns:
        List of article dictionaries with content
    """
    articles = []

    try:
        # Check if the wrapper exists
        wrapper_selector = 'div#b7-b11-InjectHTMLWrapper'
        if (await page.locator(wrapper_selector).count()) == 0:
            print("⚠️  Could not find article content wrapper")
            return articles

        # Get all child elements within the wrapper
        child_elements = await page.locator(f'{wrapper_selector} > *').all()

        current_article_text = ""
        article_number = 0

        for element in child_elements:
            try:
                # Get text content of current element
                element_text = await element.text_content()
                if not element_text:
                    continue

                element_text = element_text.strip()

                # Check if this starts a new article
                if element_text.startswith("Artigo"):
                    # Save previous article if it exists
                    if current_article_text.strip():
                        articles.append({
                            'article_number': article_number,
                            'content': current_article_text.strip()
                        })
                        article_number += 1

                    # Start new article
                    current_article_text = element_text
                else:
                    # Append to current article
                    if current_article_text:
                        current_article_text += "\n" + element_text
                    else:
                        current_article_text = element_text

            except Exception as e:
                print(f"⚠️  Error processing element: {str(e)}")
                continue

        # Save the final article
        if current_article_text.strip():
            articles.append({
                'article_number': article_number,
                'content': current_article_text.strip()
            })

        print(f"📄 Extracted {len(articles)} articles using smart chunking")
        return articles

    except Exception as e:
        print(f"❌ Error in smart article extraction: {str(e)}")
        return articles


async def save_law_to_database(law_data: Dict, articles: List[Dict], source_url: str) -> bool:
    """Save law and articles to database according to PROD4.md specification"""
    try:
        print(f"💾 Starting database persistence for: {law_data['official_title'][:50]}...")
        
        # Get Supabase client
        supabase = get_supabase_client()
        
        # Step 1: Find Foreign Keys
        emitting_entity_id = None
        law_type_id = None
        
        # Find emitting_entity_id
        if law_data.get('emitting_entity_name'):
            entity_result = supabase.table('government_entities').select('id').eq('name', law_data['emitting_entity_name']).execute()
            if entity_result.data:
                emitting_entity_id = entity_result.data[0]['id']
                print(f"✅ Found Emitting Entity ID: {emitting_entity_id}")
            else:
                print(f"⚠️  Emitting entity not found: {law_data['emitting_entity_name']}")
        
        # Find law_type_id
        if law_data.get('law_type_name'):
            type_result = supabase.table('law_types').select('id').eq('name', law_data['law_type_name']).execute()
            if type_result.data:
                law_type_id = type_result.data[0]['id']
                print(f"✅ Found Law Type ID: {law_type_id}")
            else:
                print(f"⚠️  Law type not found: {law_data['law_type_name']}")
        
        # Step 2: Translate content for multilingual support
        english_title = await _translate_text(law_data['official_title'])
        english_summary = await _translate_text(law_data.get('summary', ''))
        
        # Construct translations JSONB
        translations = {
            'pt': {
                'title': law_data['official_title'],
                'description': law_data.get('summary', '')
            },
            'en': {
                'title': english_title,
                'description': english_summary
            }
        }
        
        # Step 3: UPSERT into agora.sources
        source_data = {
            'main_url': source_url,
            'type_id': 'OFFICIAL_PUBLICATION',  # This should match a valid source type
            'source_entity_id': emitting_entity_id,
            'author': law_data.get('emitting_entity_name'),
            'published_at': law_data.get('publication_date'),
            'credibility_score': 1.0,  # Official government publications
            'is_official_document': True,
            'translations': translations,
            'is_active': True,
            'archived_url': source_url,
            'archive_status': 'ARCHIVED'
        }
        
        source_result = supabase.schema('agora').table('sources').upsert(source_data).execute()
        
        if not source_result.data:
            print("❌ Failed to create/update source")
            return False
        
        source_id = source_result.data[0]['id']
        print(f"✅ Upserted source with ID: {source_id}")
        
        # Step 4: Generate slug for law
        slug = f"dre-{law_data.get('official_number', 'unknown').replace('/', '-').replace(' ', '-')}"
        
        # Step 5: UPSERT into agora.laws
        law_record = {
            'government_entity_id': emitting_entity_id,
            'official_number': law_data.get('official_number'),
            'slug': slug,
            'type_id': law_type_id,
            'enactment_date': law_data.get('publication_date'),
            'official_title': law_data['official_title'],
            'source_id': source_id,
            'translations': translations
        }
        
        law_result = supabase.table('laws').upsert(law_record, on_conflict='slug').execute()
        
        if not law_result.data:
            print("❌ Failed to create/update law")
            return False
        
        law_id = law_result.data[0]['id']
        print(f"✅ Upserted law with ID: {law_id}")
        
        # Step 6: INSERT into agora.law_emitting_entities (junction table)
        if emitting_entity_id:
            junction_data = {
                'law_id': law_id,
                'government_entity_id': emitting_entity_id
            }
            supabase.table('law_emitting_entities').upsert(junction_data, on_conflict='law_id,government_entity_id').execute()
            print(f"✅ Created law-entity relationship")
        
        # Step 7: UPSERT into agora.law_articles & agora.law_article_versions
        articles_saved = 0
        for article in articles:
            # UPSERT into agora.law_articles
            article_record = {
                'law_id': law_id,
                'article_number': article['article_number'],
                'title': f"Artigo {article['article_number']}"
            }
            
            article_result = supabase.table('law_articles').upsert(article_record, on_conflict='law_id,article_number').execute()
            
            if article_result.data:
                article_id = article_result.data[0]['id']
                
                # UPSERT into agora.law_article_versions
                version_record = {
                    'article_id': article_id,
                    'official_text': article['content'],
                    'status_id': 'ACTIVE',  # Default status
                    'valid_from': law_data.get('publication_date'),
                    'source_id': source_id
                }
                
                supabase.table('law_article_versions').upsert(version_record, on_conflict='article_id,valid_from').execute()
                articles_saved += 1
        
        print(f"✅ Saved {articles_saved} article chunks")
        print(f"🎉 Successfully completed database persistence!")
        return True
        
    except Exception as e:
        print(f"❌ Error in database persistence: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
