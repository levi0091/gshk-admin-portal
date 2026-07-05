import os
from dotenv import load_dotenv

load_dotenv()


def get_viewpoint_conn_str() -> str:
    server = os.environ.get("VIEWPOINT_SERVER")
    database = os.environ.get("VIEWPOINT_DATABASE")
    if not server or not database:
        raise RuntimeError(
            "VIEWPOINT_SERVER and VIEWPOINT_DATABASE must be set in backend/.env"
        )
    return (
        f"mssql+pyodbc://@{server}/{database}"
        "?driver=ODBC+Driver+18+for+SQL+Server"
        "&trusted_connection=yes"
        "&Encrypt=no"
    )


def get_supabase_conn_str() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be set in backend/.env")
    return url
