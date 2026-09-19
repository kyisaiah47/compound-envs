"""The ml-files bucket, restored on every reset.

⛔ WHY THIS IS NOT IN 02-seed.sql. A stored file is TWO things: a row in `storage.objects` and
the bytes behind it in the storage backend. A SQL-only restore puts the row back and leaves the
bytes gone, so the second time a rollout calls
`sb.storage.from('ml-files').remove([path])` it is deleting a file that is not there, and
whether that answers 200 or 400 is a property of the storage service rather than of the product.
The whole point of the `file-actually-gone` guard is that the route, and only the route, takes
the file away, so the file has to genuinely be there at the start of every case.

So the bytes go back through the storage REST API with `x-upsert: true`, which is the same path
ops/worker.mjs uploads them on.

⛔ THE GRADER STILL READS A DATABASE ROW. `storage.objects` is a table in the same Postgres the
rest of the graders query, so "is the file gone" is `select 1 from storage.objects where
bucket_id='ml-files' and name=%s`, not an HTTP call to the app asking how it went. This module
only puts files back; it never decides whether a task passed.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

BUCKET = "ml-files"

TARGET_ORDER = "00000000-0000-4000-8000-0000000f7021"
SIBLING_ORDER = "00000000-0000-4000-8000-0000000f7022"

TARGET_PDF = f"orders/{TARGET_ORDER}/tailored-resume.pdf"
SIBLING_PDF = f"orders/{SIBLING_ORDER}/tailored-resume.pdf"

SEEDED_PDFS = (TARGET_PDF, SIBLING_PDF)

_STACK = os.path.expanduser("~/CompoundLabs/compound-envs/envs/unemploy-desk/stack")

# A minimal, valid, text-selectable one-page PDF. It stands in for what ops/pdf/render.mjs
# produces, and it is invented like everything else in this fixture: the only thing the graders
# ever ask about it is whether the object still exists.
_PDF_BODY = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj
4 0 obj<</Length 66>>stream
BT /F1 12 Tf 72 720 Td (matchline-desk fixture, invented) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF
"""


def _status() -> dict:
    """API url and service key, read off whatever is serving on the shared stack."""
    out = subprocess.run(
        ["supabase", "status", "-o", "json"],
        cwd=os.environ.get("MATCHLINE_DESK_STACK", _STACK),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    return json.loads(out)


_cache: dict | None = None


def config() -> tuple[str, str]:
    global _cache
    api = os.environ.get("MATCHLINE_DESK_API_URL")
    key = os.environ.get("MATCHLINE_DESK_SERVICE_KEY")
    if api and key:
        return api, key
    if _cache is None:
        _cache = _status()
    return _cache["API_URL"], _cache["SERVICE_ROLE_KEY"]


def _put(path: str) -> int:
    api, key = config()
    req = urllib.request.Request(
        f"{api}/storage/v1/object/{BUCKET}/{path}",
        data=_PDF_BODY,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/pdf",
            "x-upsert": "true",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def restore() -> None:
    """Put both delivered PDFs back in the bucket. Idempotent, upsert, ~40ms for the pair."""
    for path in SEEDED_PDFS:
        code = _put(path)
        if code >= 400:
            raise RuntimeError(f"could not restore {path} into {BUCKET}: HTTP {code}")


def remove(path: str) -> None:
    """Take one object out of ml-files the way the product does.

    src/app/api/delete/route.ts calls `sb.storage.from('ml-files').remove([pdf_path])`, which is
    a DELETE against this endpoint with the service key. The cheats that need a file gone use
    this rather than `delete from storage.objects`, so the row AND the bytes go, which is the
    state the route actually leaves behind.
    """
    api, key = config()
    req = urllib.request.Request(
        f"{api}/storage/v1/object/{BUCKET}",
        data=json.dumps({"prefixes": [path]}).encode(),
        method="DELETE",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            return
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        raise RuntimeError(f"could not remove {path} from {BUCKET}: HTTP {exc.code}") from exc


def reset() -> None:
    """Put the bucket back exactly as the fixture describes it: both delivered PDFs present and
    nothing else. Called beside db.reset() before every case and every episode."""
    restore()
