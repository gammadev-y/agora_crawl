#!/usr/bin/env python3
"""
Script to execute SQL migrations for the DRE crawler database setup.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_db_connection():
    """Get database connection using Supabase credentials"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    # Extract project ref from URL
    import re
    match = re.search(r'https://(.+)\.supabase\.co', url)
    if not match:
        raise ValueError("Invalid SUPABASE_URL format")

    project_ref = match.group(1)
    db_url = f'postgresql://postgres:{key}@{project_ref}.supabase.co:5432/postgres'

    return psycopg2.connect(db_url)

def execute_sql_file(file_path: str):
    """Execute SQL commands from a file"""
    try:
        conn = get_db_connection()
        conn.autocommit = True
        cursor = conn.cursor()

        with open(file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        # Split SQL commands by semicolon and execute them
        commands = []
        current_command = ""
        in_multiline_comment = False

        for line in sql_content.split('\n'):
            line = line.strip()

            # Handle multi-line comments
            if line.startswith('/*'):
                in_multiline_comment = True
            if in_multiline_comment:
                if '*/' in line:
                    in_multiline_comment = False
                continue

            # Skip single-line comments and empty lines
            if line.startswith('--') or not line:
                continue

            current_command += line + " "

            # Check if command ends with semicolon
            if line.endswith(';'):
                commands.append(current_command.strip())
                current_command = ""

        # Execute each command
        for command in commands:
            if command:
                print(f"Executing: {command[:60]}...")
                cursor.execute(command)
                print("✅ Executed successfully")

        cursor.close()
        conn.close()
        print("🎉 All SQL commands executed successfully!")

    except Exception as e:
        print(f"❌ Error executing SQL: {str(e)}")
        import traceback
        traceback.print_exc()

def check_tables():
    """Check if the required tables exist"""
    try:
        from lib.supabase_client import get_supabase_client
        supabase = get_supabase_client()

        tables_to_check = [
            'government_entities',
            'law_types',
            'source_types',
            'sources',
            'laws',
            'law_emitting_entities',
            'law_articles',
            'law_article_versions'
        ]

        for table in tables_to_check:
            try:
                result = supabase.table(table).select('id').limit(1).execute()
                print(f"✅ Table '{table}' exists")
            except Exception as e:
                print(f"❌ Table '{table}' does not exist or is not accessible: {str(e)[:100]}...")

    except Exception as e:
        print(f"❌ Error checking tables: {str(e)}")

if __name__ == "__main__":
    print("🔍 Checking existing tables...")
    check_tables()

    sql_file = "populate_crawler_lookups.sql"
    if os.path.exists(sql_file):
        print(f"\n📄 Executing SQL file: {sql_file}")
        execute_sql_file(sql_file)

        print("\n🔍 Checking tables after execution...")
        check_tables()
    else:
        print(f"❌ SQL file not found: {sql_file}")