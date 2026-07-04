from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from etl.config import get_viewpoint_conn_str, get_supabase_conn_str

_viewpoint_engine: Engine | None = None
_supabase_engine: Engine | None = None


def get_viewpoint_engine() -> Engine:
    global _viewpoint_engine
    if _viewpoint_engine is None:
        _viewpoint_engine = create_engine(get_viewpoint_conn_str())
    return _viewpoint_engine


def get_supabase_engine() -> Engine:
    global _supabase_engine
    if _supabase_engine is None:
        _supabase_engine = create_engine(get_supabase_conn_str())
    return _supabase_engine
