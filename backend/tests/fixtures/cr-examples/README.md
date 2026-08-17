# CR's shipped TPSI examples — test fixtures

Verbatim copy of the `Web Form Example/` tree that the Companies Registry ships
with **TPSI API Interface v1.0.14**. 73 files, ~796 KB.

## Why these are committed

The tests that matter most in `backend/tests/tpsi/` diff our XML against CR's
own instances. Before this directory existed those tests globbed a local,
`.gitignore`d `docs/` folder, so in CI the globs matched nothing, the
`parametrize` lists collected zero cases and the tests silently ceased to exist
while the suite still reported green. Committing the fixtures is what makes
them run everywhere.

## What is here

| Path | Contents |
|------|----------|
| `validateForm/` | 33 `validateForm` request instances — one or more per form code |
| `pinSigning/` | 13 `verifyPinSigning` request instances |
| `submission/` | 13 `submitForm` request instances |
| `submitting to eDrive/` | 13 `uploadToEdrive` request instances |
| `Worksheet in TPSI API Interface v1.0.14.xlsx` | CR's field worksheet: per-form field tables plus the `Country & Region`, `Capacity (Individual)`, `Capacity (Body Coporate)`, `District`, `Business Nature` and `Currency` lookup sheets |

Only `NAR1` is implemented today; the other form codes are kept because they
came in the same pack and are the reference for NNC1 (R3) and the ND* forms.

## Rank-1 source of truth — do not hand-edit

Per `memory/gshk` and the round-3 review, the source-of-truth order for XML
shape is:

1. **these example `*.xml` files** — what CR actually accepts;
2. the `§7.2` worksheet (`*.xlsx`, also here);
3. `TPSI API Interface v1.0.14.docx`, whose embedded examples are *wrong* in
   places.

Where 1 and 2 disagree the examples win — `EForm` vs `Eform`, `indvTcspNo` vs
`tcspNo`, and the interposed `<share>` level all come from that rule.

Treat this directory as vendor material:

- **Never hand-edit a file here.** A test failing against these files means our
  code is wrong, not the fixture. Editing one to make a test pass destroys the
  only independent check we have on a chargeable, irreversible submission.
- Replace the whole tree only when CR ships a new worksheet version, and update
  the version in this README and in
  `backend/services/tpsi/forms/cr_vocabularies.py` at the same time.

## Provenance and content

CR publishes these to every TPSI presenter as API documentation. They carry
placeholder data throughout — `TEST COMPANY LIMITED` / `測試有限公司`,
`陳大文` / `CHAN, TAI MAN`, `brNo 00000001`, `selectPersonId TEST1234`,
`test@cr.gov.hk`, `telNo 99999999`. They contain no GSHK client data and no
G-FlowDesk or TPSI credentials.

Two things worth knowing before you read them:

- The `pinSigning/` and `submission/` instances carry a `ds:Signature` block
  with CR's own **expired UAT public certificate** (`CN=ICRIS REVAMP UAT One`,
  issued by `Hongkong Post Trial e-Cert CA 2 - 17`, valid 2021-04-28 to
  2022-04-28). Public certificate only — no private key, and nothing usable.
- `validateForm/validate_ND8.xml` is the one file with a `brNo` other than
  `00000001`/`00000002`. It is CR's value in CR's published example; every other
  field in that file is the standard placeholder set, and no NAR1 test reads it.

The parent `docs/` folder stays `.gitignore`d — it holds genuinely sensitive
siblings (confidential internal operations PDF, `VP Database.sql`, client
document templates, and a spreadsheet named for the live TPSI account). Only
this subtree is committed.
