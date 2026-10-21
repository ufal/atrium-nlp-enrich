#!/usr/bin/env python3
"""Zero-dependency client for the ATRIUM NLP Enrichment API.

Uploads ordered text lines (CSV/XLSX/TXT file, or plain lines on stdin) to a
running instance of the FastAPI service in `service/api.py` and returns the
enriched result: UDPipe morphology and NameTag named entities as TEITOK XML, and the
named entities of each page (local server by default, remote via --base-url or the
ATRIUM_NE_URL env variable). Keywords are not part of this service since 1.0.0: they
come from atrium-keyword-extract.

Only the Python 3 standard library is used - no pip installs required.

Usage:
    python3 scripts/atrium_enrich.py lines.csv
    python3 scripts/atrium_enrich.py notes.txt --format csv
    python3 scripts/atrium_enrich.py lines.csv --jobs           # async jobs API
    python3 scripts/atrium_enrich.py lines.csv --zip out.zip    # full workspace
    python3 scripts/atrium_enrich.py - --doc-id CTX1 < lines.txt
    python3 scripts/atrium_enrich.py --info

Exit codes:
    0 - success
    1 - client-side error (bad arguments, unreadable file)
    2 - server unreachable (connection refused / timeout)
    3 - server-side error (HTTP 4xx/5xx)
"""

import argparse
import csv
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

DEFAULT_BASE_URL = os.environ.get("ATRIUM_NE_URL", "http://localhost:8000")
INPUT_SUFFIXES = {".csv", ".txt", ".xlsx"}
MAX_UPLOAD_MB = 5  # mirrors the server's MAX_UPLOAD_MB default
RETRY_STATUS = {502, 503, 504}
# A 502 is retried only with one of these reasons (atrium_service.REASON_CODES); without one,
# `detail` names a cause that a retry does not change (atrium-nlp-enrich#41).
RETRY_502_REASONS = {"upstream_unavailable"}
RETRY_ATTEMPTS = 3
RETRY_WAIT_S = 10
JOB_POLL_INTERVAL_S = 5
JOB_POLL_TIMEOUT_S = 900


def build_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Encode form fields and one or more files as multipart/form-data using only the stdlib.

    `files` maps the multipart field name to a `Path` (e.g. `{"file": lines.csv,
    "document_json": baseline.json}` for the accretion contract).
    """
    boundary = uuid.uuid4().hex
    lines = []
    for name, value in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(str(value).encode())

    for field_name, file_path in files.items():
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"'.encode()
        )
        lines.append(f"Content-Type: {mime}".encode())
        lines.append(b"")
        lines.append(file_path.read_bytes())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")

    body = b"\r\n".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def is_retryable(status: int, body: str) -> bool:
    """A 503/504 is. A 502 in the service's error body is retried only with a reason in
    RETRY_502_REASONS; a 502 without that body came from a proxy in front of the service and is."""
    if status != 502:
        return True
    try:
        error = json.loads(body)
    except ValueError:
        return True  # not the service's answer: a proxy or gateway page
    if not isinstance(error, dict) or "reason" not in error:
        return True
    return error["reason"] in RETRY_502_REASONS


def http_raw(url: str, data: bytes = None, content_type: str = None, timeout: int = 900) -> bytes:
    """POST (or GET when data is None) and return raw bytes, with retry on 502/503/504."""
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in RETRY_STATUS and attempt < RETRY_ATTEMPTS and is_retryable(e.code, detail):
                print(
                    f"[retry {attempt}/{RETRY_ATTEMPTS}] HTTP {e.code}, waiting {RETRY_WAIT_S}s...",
                    file=sys.stderr,
                )
                time.sleep(RETRY_WAIT_S)
                last_error = f"HTTP {e.code}: {detail}"
                continue
            if e.code == 429:
                print(
                    "Server busy (HTTP 429): the concurrent-job limit is reached. "
                    "Retry later or submit through the async jobs API with --jobs.",
                    file=sys.stderr,
                )
            else:
                print(f"Server error - HTTP {e.code}: {detail}", file=sys.stderr)
            sys.exit(3)
        except (urllib.error.URLError, TimeoutError) as e:
            print(
                f"Cannot reach the API at {url} ({e}).\nIs the server running? Start it with: bash scripts/server.sh",
                file=sys.stderr,
            )
            sys.exit(2)
    print(f"Server error after {RETRY_ATTEMPTS} attempts - {last_error}", file=sys.stderr)
    sys.exit(3)


def http_json(url: str, data: bytes = None, content_type: str = None, timeout: int = 900) -> dict:
    return json.loads(http_raw(url, data=data, content_type=content_type, timeout=timeout).decode("utf-8"))


def check_input(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in INPUT_SUFFIXES:
        print(f"Unsupported file type '{suffix}' for {path}. Allowed: .csv, .xlsx, .txt", file=sys.stderr)
        sys.exit(1)
    size = path.stat().st_size
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        print(
            f"{path}: {size} bytes exceeds the {MAX_UPLOAD_MB} MB server upload limit - "
            "split the file into smaller documents first",
            file=sys.stderr,
        )
        sys.exit(1)


def enrich_file(
    base_url: str,
    path: Path,
    lang: str,
    fmt: str,
    document_json: Optional[Path] = None,
) -> dict:
    """Synchronous enrichment of one uploaded file via POST /enrich."""
    fields = {"lang": lang, "format": fmt}
    files = {"file": path}
    if document_json is not None:
        files["document_json"] = document_json
    body, content_type = build_multipart(fields, files)
    if fmt == "zip":
        return {"_zip_bytes": http_raw(f"{base_url}/enrich", data=body, content_type=content_type)}
    return http_json(f"{base_url}/enrich", data=body, content_type=content_type)


def enrich_stdin(
    base_url: str,
    doc_id: str,
    lang: str,
    document_json: Optional[Path] = None,
) -> dict:
    """Read plain text lines from stdin and enrich them via POST /enrich_text."""
    lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    if not lines:
        print("No text lines on stdin.", file=sys.stderr)
        sys.exit(1)
    payload_dict = {"doc_id": doc_id, "lines": lines, "lang": lang}
    if document_json is not None:
        payload_dict["document_json"] = json.loads(document_json.read_text(encoding="utf-8"))
    payload = json.dumps(payload_dict).encode("utf-8")
    return http_json(f"{base_url}/enrich_text", data=payload, content_type="application/json")


def enrich_via_jobs(base_url: str, path: Path, lang: str) -> dict:
    """Asynchronous enrichment: submit to POST /jobs, poll, fetch the result."""
    fields = {"lang": lang}
    body, content_type = build_multipart(fields, {"file": path})
    submitted = http_json(f"{base_url}/jobs", data=body, content_type=content_type)
    job_id = submitted.get("job_id")
    if not job_id:
        print(f"Job submission failed: {submitted}", file=sys.stderr)
        sys.exit(3)
    print(f"Job {job_id} queued; polling every {JOB_POLL_INTERVAL_S}s...", file=sys.stderr)

    deadline = time.monotonic() + JOB_POLL_TIMEOUT_S
    while True:
        status = http_json(f"{base_url}/jobs/{job_id}", timeout=60)
        state = status.get("status")
        if state == "done":
            result = http_json(f"{base_url}/jobs/{job_id}/result", timeout=60)
            http_raw_delete(f"{base_url}/jobs/{job_id}")
            return result
        if state == "failed":
            print(f"Job {job_id} failed: {status.get('error')}", file=sys.stderr)
            sys.exit(3)
        if time.monotonic() > deadline:
            print(f"Job {job_id} still '{state}' after {JOB_POLL_TIMEOUT_S}s - giving up.", file=sys.stderr)
            sys.exit(3)
        time.sleep(JOB_POLL_INTERVAL_S)


def http_raw_delete(url: str) -> None:
    """Best-effort DELETE (job cleanup) - failures are not fatal."""
    try:
        request = urllib.request.Request(url, method="DELETE")
        urllib.request.urlopen(request, timeout=30).read()
    except Exception:
        pass


def result_rows(name: str, envelope: dict) -> list[tuple]:
    """Flatten an enrichment envelope into (doc, page, entity, type, count) rows."""
    rows = []
    doc = envelope.get("doc_id", name)
    for page in envelope.get("ne_summary") or []:
        for entity in page.get("entities") or []:
            rows.append((doc, page.get("page") or "", entity.get("text", ""), entity.get("type") or "", entity.get("count") or ""))
    return rows


def print_table(rows: list[tuple], as_csv: bool) -> None:
    """Aligned table, or CSV through the csv module (entity texts can hold commas)."""
    header = ("DOC", "PAGE", "ENTITY", "TYPE", "COUNT")
    if as_csv:
        writer = csv.writer(sys.stdout)
        writer.writerow(header)
        writer.writerows(rows)
        return
    widths = [max(len(str(value)) for value in column) for column in zip(header, *rows)]
    for row in (header, *rows):
        print("  ".join(str(value).ljust(width) for value, width in zip(row, widths)).rstrip())


def summarize(envelope: dict) -> None:
    entities = sum(len(p.get("entities") or []) for p in envelope.get("ne_summary") or [])
    valid = envelope.get("teitok_schema_valid")
    print(
        f"# doc_id={envelope.get('doc_id')} pages={envelope.get('pages')} entities={entities} "
        f"layout={envelope.get('layout_source')} teitok_valid={'unknown' if valid is None else valid}",
        file=sys.stderr,
    )


class UsageParser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; the client contract keeps 2 for "server unreachable"."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = UsageParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help="CSV/XLSX/TXT line file(s) to enrich, or '-' for stdin lines")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help=f"API base URL (default: {DEFAULT_BASE_URL}, env: ATRIUM_NE_URL)"
    )
    parser.add_argument("--lang", default="cs", help="text language (default: cs; Czech-pinned in v1)")
    parser.add_argument("--doc-id", default="document", help="document id for stdin input (default: document)")
    parser.add_argument(
        "--jobs", action="store_true", help="use the async jobs API (submit, poll, fetch) instead of a sync call"
    )
    parser.add_argument(
        "--zip", metavar="OUT.zip", default=None, help="download the full workspace ZIP to this path (sync only)"
    )
    parser.add_argument(
        "--format", choices=["table", "csv", "json"], default="table", help="output format (default: table)"
    )
    parser.add_argument("--info", action="store_true", help="print service capabilities and limits, then exit")
    parser.add_argument(
        "--document-json",
        metavar="PATH",
        help="baseline ATRIUM Document JSON to accrete this tool's entities[]/pages[].teitok_surface "
        "onto (docs/document_schema.md); requires exactly one input file, no --jobs/--zip",
    )
    parser.add_argument(
        "--document-json-out-file",
        metavar="PATH",
        help="save the returned document_json record to PATH (default: only embedded in --format json output)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    if args.info:
        print(json.dumps(http_json(f"{base_url}/info", timeout=60), indent=2))
        return

    if not args.files:
        parser.error("no input files given (or use --info)")
    if args.zip and (args.jobs or len(args.files) != 1 or args.files[0] == "-"):
        parser.error("--zip needs exactly one input file and a synchronous call (no --jobs, no stdin)")

    document_json_path = None
    if args.document_json:
        if args.jobs or args.zip or len(args.files) != 1:
            parser.error("--document-json requires exactly one input file and no --jobs/--zip")
        document_json_path = Path(args.document_json)
        if not document_json_path.is_file():
            print(f"--document-json file not found: {document_json_path}", file=sys.stderr)
            sys.exit(1)
    if args.document_json_out_file and document_json_path is None:
        parser.error("--document-json-out-file requires --document-json")

    envelopes = {}
    rows = []
    document_record = None
    for name in args.files:
        if name == "-":
            envelope = enrich_stdin(base_url, args.doc_id, args.lang, document_json_path)
        else:
            path = Path(name)
            if not path.is_file():
                print(f"File not found: {path}", file=sys.stderr)
                sys.exit(1)
            check_input(path)
            if args.jobs:
                envelope = enrich_via_jobs(base_url, path, args.lang)
            elif args.zip:
                result = enrich_file(base_url, path, args.lang, fmt="zip")
                Path(args.zip).write_bytes(result["_zip_bytes"])
                print(f"Workspace ZIP saved to {args.zip}")
                return
            else:
                envelope = enrich_file(
                    base_url,
                    path,
                    args.lang,
                    fmt="json",
                    document_json=document_json_path,
                )
        envelopes[name] = envelope
        summarize(envelope)
        rows.extend(result_rows(name, envelope))
        if envelope.get("document_json") is not None:
            document_record = envelope["document_json"]

    if args.document_json_out_file and document_record is not None:
        Path(args.document_json_out_file).write_text(json.dumps(document_record, indent=2), encoding="utf-8")
        print(f"Document JSON record written to {args.document_json_out_file}", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(envelopes if len(envelopes) > 1 else next(iter(envelopes.values())), indent=2))
    else:
        if not rows:
            print("No named entities found. Use --format json for the TEITOK XML and the full envelope.", file=sys.stderr)
            return
        print_table(rows, as_csv=(args.format == "csv"))


if __name__ == "__main__":
    main()
