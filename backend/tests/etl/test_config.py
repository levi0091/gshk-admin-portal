import os
import pytest
from etl.config import get_viewpoint_conn_str, get_supabase_conn_str


def test_get_viewpoint_conn_str_builds_trusted_connection_url(monkeypatch):
    monkeypatch.setenv("VIEWPOINT_SERVER", "localhost")
    monkeypatch.setenv("VIEWPOINT_DATABASE", "ViewPoint")
    conn_str = get_viewpoint_conn_str()
    assert conn_str.startswith("mssql+pyodbc://@localhost/ViewPoint")
    assert "trusted_connection=yes" in conn_str


def test_get_viewpoint_conn_str_raises_when_unset(monkeypatch):
    monkeypatch.delenv("VIEWPOINT_SERVER", raising=False)
    monkeypatch.delenv("VIEWPOINT_DATABASE", raising=False)
    with pytest.raises(RuntimeError):
        get_viewpoint_conn_str()


def test_get_supabase_conn_str_reads_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    assert get_supabase_conn_str() == "postgresql://u:p@host:5432/db"
