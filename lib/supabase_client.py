import os
from supabase import create_client, Client

_supabase_client: Client | None = None

def get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is None:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment variables")
        _supabase_client = create_client(supabase_url, supabase_key)
    return _supabase_client

def get_agora_table(table_name: str):
    """Get a table from the agora schema"""
    client = get_supabase_client()
    return client.schema('agora').table(table_name)