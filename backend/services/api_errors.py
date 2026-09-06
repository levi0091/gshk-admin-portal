"""What the browser is told when a request fails for a reason nobody wrote code for.

WHY THIS EXISTS. A FastAPI app with no `Exception` handler answers an unhandled
error from Starlette's own `ServerErrorMiddleware`, which sits OUTSIDE
`CORSMiddleware`. That reply carries no `Access-Control-Allow-Origin`, so the
browser refuses to hand it to the page at all: `fetch` REJECTS instead of
resolving, and `lib/api.js` prints its offline message --

    "Could not reach the server. Check your connection and try again -- if it
     keeps happening the API may be down or still starting up."

-- for a server that answered in 40ms. Levi hit exactly this on 2026-09-04
adding a shareholder: the Share Class field took free text, "1" reached a `uuid`
column, PostgREST raised `22P02`, and the screen said the API was down. The
message named the wrong thing to check, in the one place it could not be
checked.

REGISTERING AN `Exception` HANDLER IS NOT ENOUGH, and this is the part that is
easy to get wrong. Starlette hands the handler registered for `Exception` to
`ServerErrorMiddleware` itself -- which is the OUTERMOST layer, above the user
middleware -- so the nicer reply is produced in exactly the same place as the
bare one and still never passes back through `CORSMiddleware`. The fix has to be
a middleware that sits INSIDE CORS:

    ServerErrorMiddleware        (Starlette's, still the last resort)
      CORSMiddleware             <- adds the header on the way out
        ErrorEnvelopeMiddleware  <- this file: catches, and returns a response
          ExceptionMiddleware
            router

Because `add_middleware` inserts at the front of the list, that ordering means
`install()` must be called BEFORE the CORS middleware is added. `main.py` does,
with a comment saying so.

WHAT IT SAYS. A Postgres constraint violation is a fact about the SUBMITTED
DATA, not about the server, so those are 422s that quote the constraint --
"22P02 invalid input syntax for type uuid" is unfriendly but it is about the
value that was typed, and an operator who can see it will fix the field. Every
other exception is a bug: the caller gets a fixed sentence and the traceback
goes to stderr, where Railway keeps it, because a stack trace on screen tells
the operator nothing they can act on and may quote a row they should not see.
"""
import traceback
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:  # pragma: no cover - import shape differs across postgrest releases
    from postgrest.exceptions import APIError
except Exception:  # pragma: no cover
    APIError = None  # type: ignore[assignment]


#: SQLSTATEs that mean "the request said something the database will not accept".
#: Each is a 422 because re-sending the identical request cannot succeed -- the
#: operator has to change a value first.
_DATA_FAULT_CODES = {
    "22001": "A value is longer than the column allows.",
    "22003": "A number is outside the range the column allows.",
    "22007": "A date is not in a format the database recognises.",
    "22P02": "A value is not of the type the column requires.",
    "23502": "A required value was left empty.",
    "23503": "A referenced record does not exist.",
    "23505": "A record with that value already exists.",
    "23514": "A value breaks a rule the database enforces.",
}

_GENERIC = ("The server could not complete this request. Nothing was saved. "
            "If it keeps happening, quote the time and what you were doing.")


def _data_fault(exc: Any) -> Optional[dict]:
    """The 422 body for a constraint violation, or None if this isn't one."""
    code = getattr(exc, "code", None)
    if code not in _DATA_FAULT_CODES:
        return None
    # PostgREST's own words alongside ours: the summary says WHAT KIND of
    # problem it is, the detail says which value. Neither alone is enough --
    # "A value is not of the type the column requires" does not say which, and
    # `invalid input syntax for type uuid: "1"` does not say what to do.
    parts = [p for p in (getattr(exc, "message", None),
                         getattr(exc, "details", None),
                         getattr(exc, "hint", None)) if p]
    return {"message": _DATA_FAULT_CODES[code],
            "problems": parts or [_DATA_FAULT_CODES[code]]}


def to_response(request: Request, exc: BaseException) -> JSONResponse:
    """The reply for one unhandled exception."""
    body = _data_fault(exc) if APIError and isinstance(exc, APIError) else None
    if body is not None:
        # Still logged: a constraint the API should have checked itself is a
        # gap in the API, and it is only visible here.
        print(f"[api] data fault on {request.method} {request.url.path}: {exc!r}",
              flush=True)
        return JSONResponse(status_code=422, content={"detail": body})

    print(f"[api] unhandled on {request.method} {request.url.path}: {exc!r}",
          flush=True)
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": _GENERIC})


class ErrorEnvelopeMiddleware(BaseHTTPMiddleware):
    """Turns an unhandled exception into a response, inside the CORS layer."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 - this is the catch-all
            return to_response(request, exc)


def install(app: FastAPI) -> None:
    """Install the catch-all. MUST be called BEFORE the CORS middleware.

    `add_middleware` inserts at the front, so whatever is added last ends up
    outermost -- and CORS has to be outermost or it never sees this response.
    """
    app.add_middleware(ErrorEnvelopeMiddleware)

    # Belt and braces for anything that escapes the middleware (an error raised
    # while the response is being sent, say). This one is answered by
    # ServerErrorMiddleware, ABOVE CORS, so the browser will still refuse it --
    # it exists so the log line and the status code are right, not so the page
    # can read it.
    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # noqa: ANN202
        return to_response(request, exc)
