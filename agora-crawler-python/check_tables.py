#!/usr/bin/env python3
import os
from dotenv import load_dotenv
load_dotenv()
from lib.supabase_client import get_supabase_client

supabase = get_supabase_client()

tables_to_check = [
    'government_entities', 'law_types', 'source_types', 'sources', 'laws',
    'law_emitting_entities', 'law_articles', 'law_article_versions'
]

for table in tables_to_check:
    try:
        result = supabase.table(table).select('*').limit(1).execute()
        print(f'✅ Table {table}: {len(result.data)} records')
    except Exception as e:
        if 'PGRST205' in str(e):
            print(f'❌ Table {table}: Not found')
        else:
            print(f'⚠️  Table {table}: {str(e)[:50]}...')