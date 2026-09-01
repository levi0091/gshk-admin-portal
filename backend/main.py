import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routers import (auth, users, roles, cases, cases_audit, audit, companies,
                     persons, documents, lookups, public_approval, tpsi)
from services.app_env import is_production

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
app.include_router(cases.router, prefix="/cases", tags=["cases"])
app.include_router(cases_audit.router, prefix="/cases", tags=["cases"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])
app.include_router(companies.router, prefix="/companies", tags=["companies"])
app.include_router(persons.router, prefix="/persons", tags=["persons"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(lookups.router, prefix="/lookups", tags=["lookups"])
app.include_router(tpsi.router, prefix="/tpsi", tags=["tpsi"])
# THE ONLY UNAUTHENTICATED ROUTER (spec §5). Mounted under its own prefix so
# `/public/...` is visibly separate from everything require_permission guards --
# a route added to any router above inherits that router's gate, and a route
# added here inherits none. See routers/public_approval.py for why this one is
# safe without a user, and why it must stay the only one.
app.include_router(public_approval.router, prefix="/public", tags=["public"])


@app.get("/health")
def health():
    return {
        "status": "ok",
        # WHICH INTERLOCK THIS DEPLOYMENT IS RUNNING UNDER.
        #
        # APP_ENV is invisible from outside Railway, and one wrong value
        # silently disarms the non-production mail lock -- which is exactly
        # what happened to DEV (Levi 2026-08-30: "there was still nothing in
        # the top right of the page to show it is test env"). The missing
        # badge was the only symptom of a backend that believed it was
        # production while sitting on a database of 4,398 real director
        # addresses.
        #
        # The DERIVED answer, never the raw APP_ENV string: this is the same
        # reading services/app_env.py hands the mail lock and the TEST badge,
        # so it cannot agree with one and not the other. Nothing else about
        # the configuration is exposed.
        "environment": "production" if is_production() else "non-production",
    }
