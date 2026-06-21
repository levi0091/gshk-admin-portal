import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routers import auth, users, roles, cases_audit, audit

app = FastAPI(title="G-FlowDesk Admin API", version="0.1.0")

origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(roles.router, prefix="/roles", tags=["roles"])
app.include_router(cases_audit.router, prefix="/cases", tags=["cases"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])


@app.get("/health")
def health():
    return {"status": "ok"}
