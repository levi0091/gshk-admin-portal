"""HTTP transport for TPSI.

The auth-failure rule is enforced here and nowhere else: EXACTLY ONE
authentication attempt. CR locks accounts after repeated failures — account
RYANYIUHK was already locked this way — so an automatic retry turns one bad
password into a locked filing identity, and inside the Mon-Fri 10:00-16:00 test
window that costs a day.

The single permitted retry is re-acquiring once when a CACHED token is rejected;
`_retrying` makes sure that path cannot recurse.
"""
import httpx

from services.tpsi import tokens
from services.tpsi.config import get_config
from services.tpsi.errors import (
    TpsiAuthError,
    TpsiError,
    TpsiPasswordExpiredError,
    TpsiUnavailableError,
)
from services.tpsi.secrets import sha256_hex

#: EVERY phase is named (code review 02, N-7). `httpx.Timeout(60.0, connect=15.0)`
#: also set write and pool to 60 -- and, for the submit, to 180 -- so a stalled
#: upload could take as long as the answer, and the bound the stale-claim
#: cut-off is built on only held if the unnamed phases were ignored. Each call
#: opens its own client, so pool never really waits; the budget is small and
#: counted anyway.
_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=5.0)

#: submitForm, and ONLY submitForm, waits three minutes (Levi 2026-10-26).
#: CR's chargeable call answers in 25-56 s normally (n=144 on PROD, median
#: 29 s), and 16 of 160 PROD submits hit the 60 s read above at 63-64 s —
#: while CR, as often as not, went on to lodge and charge. A longer wait turns
#: most of those into a receipt instead of an unknown outcome. It is safe only
#: because the submit now runs after the HTTP response (routers/tpsi.py): the
#: edge in front of the API gives up at 100 s. Every other call keeps 60 s,
#: since none of them spends money and a slow validate should fail fast.
_SUBMIT_TIMEOUT = httpx.Timeout(connect=15.0, read=180.0, write=15.0, pool=5.0)

#: The operations that get `_SUBMIT_TIMEOUT`.
_LONG_WAIT_OPERATIONS = frozenset({"submitForm"})


def worst_case_seconds(timeout: httpx.Timeout) -> float:
    """The longest one HTTP exchange can take under `timeout`: ALL FOUR phases,
    connect + write + read + pool, back to back. `filings.STALE_CLAIM_SECONDS`
    is built from this, and a test fails if a timeout is raised without it.

    A ceiling, not an expectation -- the sum is what makes it a bound. httpx
    limits each phase separately, and read is the gap BETWEEN CHUNKS rather than
    the whole response, so a reply that drips could in principle run longer
    still. That is harmless for the money -- a late receipt is always kept
    (`filings.finish_submit`) -- and not a realistic way for CR to behave.
    """
    return float(timeout.connect + timeout.write + timeout.read + timeout.pool)


#: What `submitForm` can take in the worst case: authenticating first (a client
#: with no cached token) and then the 180 s post — and no second post, since a
#: 401 is not retried. See `filings.STALE_CLAIM_SECONDS`.
SUBMIT_WORST_CASE_SECONDS = (worst_case_seconds(_TIMEOUT)
                             + worst_case_seconds(_SUBMIT_TIMEOUT))


class TpsiClient:
    def __init__(self, account_id: str, tpsi_password: str):
        self.account_id = account_id
        self._password = tpsi_password
        self._token_cache: str | None = None
        self._transport: httpx.BaseTransport | None = None  # tests inject here
        # Set only when THIS client actually logged in (not on cache reuse), so
        # the caller can audit TPSI_AUTH and persist password_expires_in.
        self.last_auth: tokens.AuthResult | None = None

    # ---- transport -------------------------------------------------------
    def _http(self, timeout: httpx.Timeout = _TIMEOUT) -> httpx.Client:
        cfg = get_config()
        return httpx.Client(
            transport=self._transport,
            verify=cfg.tls_verify,
            timeout=timeout,
        )

    def _url(self, path: str) -> str:
        return f"{get_config().base_url}{path}"

    # ---- authentication --------------------------------------------------
    def _basic_header(self) -> str:
        import base64

        raw = f"{self.account_id}:{sha256_hex(self._password)}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    def authenticate(self) -> tokens.AuthResult:
        """One attempt. Never retried."""
        try:
            with self._http() as http:
                response = http.get(
                    self._url("/oauth/token.do?scope=tpsi"),
                    headers={"Authorization": self._basic_header()},
                )
        except httpx.HTTPError as exc:
            # NOT the test window, on either environment: CR's test login and
            # balance endpoints answer 24/7 and only the FORM APIs are windowed,
            # so a call that never completed did not hit a closed window.
            raise TpsiUnavailableError(f"cannot reach TPSI: {exc}",
                                       kind="unreachable") from exc

        if response.status_code == 401:
            body = response.text or ""
            if "password expired" in body.lower():
                raise TpsiPasswordExpiredError(
                    "TPSI password expired (180-day policy) — change it before filing"
                )
            raise TpsiAuthError(
                "TPSI rejected the credentials. NOT retried: repeated failures "
                "lock the CR account."
            )
        if response.status_code >= 400:
            raise TpsiUnavailableError(f"TPSI auth returned {response.status_code}")

        data = response.json()
        result = tokens.AuthResult(
            access_token=data["access_token"],
            expires_in=int(data.get("expires_in", 1800)),
            password_expires_in=data.get("password_expires_in"),
        )
        self.last_auth = result
        return result

    def token(self) -> str:
        if self._token_cache:
            return self._token_cache
        self._token_cache = tokens.acquire_token(self.account_id, self.authenticate)
        return self._token_cache

    # ---- calls -----------------------------------------------------------
    def post_form(self, operation: str, form_code: str, submission_xml: str) -> bytes:
        """Post a form operation: path is {operation}{FormCode}, body is the
        operation wrapper around <cr:submission>.

        The wrapper element is not always the path segment — e-Drive is
        uploadToEdriveForm in the URL and uploadToEdrive in the body — so both
        come from soap.OPERATIONS rather than being concatenated here.
        """
        from services.tpsi.soap import build_envelope

        long_wait = operation in _LONG_WAIT_OPERATIONS
        return self.post_soap(
            f"/tpsi/{operation}{form_code}",
            _prebuilt=build_envelope(operation, submission_xml),
            _timeout=_SUBMIT_TIMEOUT if long_wait else _TIMEOUT,
            # A CHARGEABLE CALL IS POSTED ONCE. The re-login-and-retry below is
            # right for a free call whose cached token went stale, and wrong
            # here for two reasons: the retry would re-post under a fresh 180 s
            # wait, outside every bound `filings.STALE_CLAIM_SECONDS` relies on
            # (code review 01, B1); and a 401 means CR never looked at the
            # form, so there is nothing to retry on — it is a plain refusal
            # (`submission_failed`, kind "auth") and the operator submits again
            # with a freshly acquired token.
            _single_shot=long_wait,
        )

    def post_soap(
        self,
        path: str,
        body_xml: str = "",
        _retrying: bool = False,
        _prebuilt: bytes | None = None,
        _timeout: httpx.Timeout = _TIMEOUT,
        _single_shot: bool = False,
    ) -> bytes:
        from services.tpsi.soap import wrap_envelope

        payload = _prebuilt if _prebuilt is not None else wrap_envelope(body_xml)
        try:
            with self._http(_timeout) as http:
                response = http.post(
                    self._url(path),
                    content=payload,
                    headers={
                        "Authorization": f"Bearer {self.token()}",
                        "Content-Type": "text/xml; charset=utf-8",
                    },
                )
        except httpx.HTTPError as exc:
            raise TpsiUnavailableError(f"cannot reach TPSI: {exc}",
                                       kind="unreachable") from exc

        if response.status_code == 401:
            if _single_shot:
                tokens.invalidate(self.account_id)
                self._token_cache = None
                raise TpsiAuthError(
                    "TPSI rejected the token for this submission, so CR "
                    "processed nothing and nothing was charged. Submit again.")
            if _retrying:
                # Second 401 in a row. Stop — do not loop against a locking API.
                # Clear the cache too: leaving the rejected token in
                # _token_cache would make the NEXT call on this instance
                # re-send it, 401, and re-run the whole invalidate/re-auth/
                # retry cycle — compounding auth attempts against an
                # account-locking API, which is exactly what this file exists
                # to prevent.
                tokens.invalidate(self.account_id)
                self._token_cache = None
                raise TpsiAuthError("TPSI rejected the token twice; giving up")
            # The one permitted retry: the cached token was stale.
            tokens.invalidate(self.account_id)
            self._token_cache = None
            return self.post_soap(path, body_xml, _retrying=True, _prebuilt=payload,
                                  _timeout=_timeout)

        if response.status_code >= 500:
            # CR returns FIELD-LEVEL VALIDATION FAULTS as HTTP 500, carrying
            # <detail><webServiceFaultBeans><faultString>. Verified live on
            # 2026-08-21: "Please check selectPersonId field.", "HKID No. length
            # must be at most 5", and so on all arrive this way. Raising a
            # hardcoded "outside the window" here threw every one of those away
            # and, worse, asserted a cause that was false — those faults were
            # returned at 11:30 HKT on a Friday, squarely inside the window.
            #
            # raise_for_fault already parses this exact shape and raises the
            # right TpsiError subclass with .faults populated, which
            # filings.validate persists to cr_error. So try it first and only
            # fall back when the body is genuinely not a SOAP fault.
            from services.tpsi.errors import raise_for_fault

            try:
                raise_for_fault(response.content)
            except TpsiUnavailableError:
                pass  # unparseable body — the generic message below is right
            # The window is named ONLY when this deployment actually files
            # against CR's test host. TPSI_ENV overrides APP_ENV so that PROD
            # can run against CR test during the pilot, so neither the badge in
            # the header nor APP_ENV can answer this -- `cfg.env` can.
            # Asserting a cause that is false is the mistake recorded above.
            if get_config().env == "test":
                raise TpsiUnavailableError(
                    f"TPSI returned {response.status_code} with no SOAP fault; "
                    "the TEST form APIs run Mon-Fri 10:00-16:00 HKT only",
                    kind="test_window",
                )
            raise TpsiUnavailableError(
                f"TPSI returned {response.status_code} with no SOAP fault",
                kind="service_error",
            )
        if response.status_code >= 400:
            raise TpsiError(f"TPSI returned {response.status_code}")

        return response.content

    def logout(self) -> None:
        try:
            # Only revoke a token we actually have in-process. self.token()
            # would call acquire_token() and, absent a live DB row, perform a
            # genuine login just to get something to immediately revoke — a
            # wasted real login against an account-locking API. If there is
            # nothing cached, there is nothing to revoke; skip the call.
            if self._token_cache:
                with self._http() as http:
                    http.post(
                        self._url("/oauth/revoke.do"),
                        headers={"Authorization": f"Bearer {self._token_cache}"},
                    )
        except (httpx.HTTPError, TpsiError):
            pass  # best-effort; the token expires on its own in 30 minutes
        finally:
            tokens.invalidate(self.account_id)
            self._token_cache = None

    def change_password(self, new_password: str) -> str:
        """existPassword = SHA-256 hash; newPassword = RSA with the CR public key."""
        import base64

        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        key = load_pem_public_key(get_config().cr_public_key_pem.encode())
        encrypted = base64.b64encode(
            key.encrypt(new_password.encode(), padding.PKCS1v15())
        ).decode()

        body = (
            "<changeTpsiPassword>"
            f"<existPassword>{sha256_hex(self._password)}</existPassword>"
            f"<newPassword>{encrypted}</newPassword>"
            "</changeTpsiPassword>"
        )
        from services.tpsi.soap import parse_response, text_of

        raw = self.post_soap("/tpsi/changeTpsiPassword", body)
        element = parse_response(raw, "changeTpsiPasswordResponse")
        return text_of(element, "result") or ""
