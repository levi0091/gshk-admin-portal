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

_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


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
    def _http(self) -> httpx.Client:
        cfg = get_config()
        return httpx.Client(
            transport=self._transport,
            verify=cfg.tls_verify,
            timeout=_TIMEOUT,
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
            raise TpsiUnavailableError(f"cannot reach TPSI: {exc}") from exc

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

        return self.post_soap(
            f"/tpsi/{operation}{form_code}",
            _prebuilt=build_envelope(operation, submission_xml),
        )

    def post_soap(
        self,
        path: str,
        body_xml: str = "",
        _retrying: bool = False,
        _prebuilt: bytes | None = None,
    ) -> bytes:
        from services.tpsi.soap import wrap_envelope

        payload = _prebuilt if _prebuilt is not None else wrap_envelope(body_xml)
        try:
            with self._http() as http:
                response = http.post(
                    self._url(path),
                    content=payload,
                    headers={
                        "Authorization": f"Bearer {self.token()}",
                        "Content-Type": "text/xml; charset=utf-8",
                    },
                )
        except httpx.HTTPError as exc:
            raise TpsiUnavailableError(f"cannot reach TPSI: {exc}") from exc

        if response.status_code == 401:
            if _retrying:
                # Second 401 in a row. Stop — do not loop against a locking API.
                tokens.invalidate(self.account_id)
                raise TpsiAuthError("TPSI rejected the token twice; giving up")
            # The one permitted retry: the cached token was stale.
            tokens.invalidate(self.account_id)
            self._token_cache = None
            return self.post_soap(path, body_xml, _retrying=True, _prebuilt=payload)

        if response.status_code >= 500:
            raise TpsiUnavailableError(
                f"TPSI returned {response.status_code} — the TEST form APIs run "
                "Mon-Fri 10:00-16:00 HKT only"
            )
        if response.status_code >= 400:
            raise TpsiError(f"TPSI returned {response.status_code}")

        return response.content

    def logout(self) -> None:
        try:
            with self._http() as http:
                http.post(
                    self._url("/oauth/revoke.do"),
                    headers={"Authorization": f"Bearer {self.token()}"},
                )
        except httpx.HTTPError:
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
