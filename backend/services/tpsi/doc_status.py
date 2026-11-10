"""What CR may call a NAR1 in a `docStatusEnquiry` row.

The CR status poll that used to live here -- six `cr_*` codes, their labels, the
vocabulary normaliser -- was REMOVED (Levi 2026-10-17; migration 054): CR will not
report a document's status after filing, so the workflow ends at the receipt and
nothing polls CR. It stays removed (Levi 2026-10-27).

What is left is the one decision `filings.verify_lodged` needs. The resolve route
(`POST /tpsi/filings/{id}/resolve`, migration 056) calls the free
`docStatusEnquiry` ONCE, on an operator's request, to prove a return CR may have
lodged before it is marked `submitted`. That is a read on demand, not a poll.
"""
from __future__ import annotations

#: What CR may call a NAR1 in a docStatusEnquiry row -- matched case-insensitively
#: against `documentName` AND `documentRefNo`, by `filings.verify_lodged`, to check
#: that a receipt an operator typed is for this return. CR's own published example
#: is `documentName "Annual Return"` with `documentRefNo "NAR1(731)"` (TPSI API
#: Interface v1.0.14, 6.5.5), and nothing specifies the wording, so a stricter test
#: would refuse a genuine return (code review 02, B3). Never used to reject a row
#: that says nothing.
NAR1_DOCUMENT_HINTS = ("NAR1", "ANNUAL RETURN")
