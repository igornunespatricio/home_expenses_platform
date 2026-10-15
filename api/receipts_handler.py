"""Receipts API: import an NFC-e page, review it, save it. A second Lambda behind the same HTTP API.

  POST /api/receipts/import   {"file": "<base64 of the .mht or .html>"}
      Parses the file and answers with the draft for review. Writes nothing.
      409 if this receipt was already imported.

  POST /api/receipts          {"file": "<base64>", "receipt": {"merchant", "category", "date", "items": [...]}}
      Re-reads the file (the access key always comes from the file, never from the client),
      stores the original in S3 with CPFs masked, then writes one expense row per item
      (the discount is an item with a negative amount) and finally a RECEIPT#<access key>
      row that marks the receipt as imported.

Item rows use the same shape as /api/expenses rows, so listing, filtering and totals keep working:
  sk = EXP#<date>#<access key>-<line>   (deterministic, so a retry overwrites instead of duplicating)
The owner is always the JWT 'sub' claim.
"""

import base64
import binascii
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import boto3

from handler import (
    HttpError,
    clean,
    get_body,
    get_user,
    parse_date,
    public,
    response,
    table,
)
from receipt_parser import (
    MAX_BYTES,
    ReceiptParseError,
    parse_receipt,
    redact_personal_data,
)

BUCKET = os.environ.get("RECEIPTS_BUCKET", "")
BASE_PATH = "/api/receipts"
MAX_ITEMS = 300
CENT = Decimal("0.01")

_s3 = None


def s3():
    """Create the S3 client lazily (keeps imports/tests free of AWS calls)."""
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


# ---------- input ----------
def read_file(body):
    value = body.get("file")
    if not isinstance(value, str) or not value:
        raise HttpError(400, "'file' is required (base64 of the saved receipt page)")
    if len(value) > MAX_BYTES * 4 // 3 + 8:
        raise HttpError(413, "The file is too large to be a receipt")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HttpError(400, "'file' must be valid base64") from None


def parse(raw):
    try:
        return parse_receipt(raw)
    except ReceiptParseError as err:
        raise HttpError(422, str(err)) from None


def number(value, label):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HttpError(400, f"{label} must be a number") from None
    if isinstance(value, bool) or not result.is_finite():
        raise HttpError(400, f"{label} must be a number")
    return result


def text(value, label, limit, required=True):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise HttpError(400, f"{label} is required")
    value = value.strip()
    if len(value) > limit:
        raise HttpError(400, f"{label} is too long (max {limit} characters)")
    return value


def parse_edited(body, receipt):
    """Validate what the user reviewed. Raises HttpError(400) before anything is written."""
    draft = body.get("receipt")
    if not isinstance(draft, dict):
        raise HttpError(400, "'receipt' is required")
    merchant = clean(draft.get("merchant"), "merchant")
    day = parse_date(draft.get("date") or receipt.date)
    raw_items = draft.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise HttpError(400, "'items' must be a non-empty list")
    if len(raw_items) > MAX_ITEMS:
        raise HttpError(400, f"A receipt can have at most {MAX_ITEMS} items")

    items = []
    for n, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise HttpError(400, f"Item {n} must be an object")
        kind = raw.get("kind", "product")
        if kind not in ("product", "discount"):
            raise HttpError(400, f"Item {n}: kind must be 'product' or 'discount'")

        total = number(raw.get("total"), f"Item {n} total").quantize(CENT)
        if kind == "product":
            if total <= 0:
                raise HttpError(400, f"Item {n}: total must be greater than 0")
            quantity = number(raw.get("quantity"), f"Item {n} quantity")
            unit_price = number(raw.get("unit_price"), f"Item {n} unit price")
            if quantity <= 0 or unit_price < 0:
                raise HttpError(400, f"Item {n}: quantity must be above 0 and unit price cannot be negative")
        else:
            if total >= 0:
                raise HttpError(400, f"Item {n}: a discount must be a negative amount")
            quantity, unit_price = Decimal(1), total

        items.append(
            {
                "kind": kind,
                "name": text(raw.get("name"), f"Item {n} name", 200),
                "code": text(raw.get("code"), f"Item {n} code", 30, required=False),
                "unit": text(raw.get("unit"), f"Item {n} unit", 10, required=False) or "UN",
                "category": clean(raw.get("category") or draft.get("category"), f"Item {n} category"),
                "quantity": quantity,
                "unit_price": unit_price,
                "total": total,
            }
        )
    return merchant, day, items


# ---------- rows ----------
def expense_row(user, receipt_key, merchant, day, line, item):
    pk = f"USER#{user}"
    expense_id = f"{receipt_key}-{line:03d}"
    return {
        "pk": pk,
        "sk": f"EXP#{day}#{expense_id}",
        "amount": item["total"],
        "date": day,
        "category": item["category"],
        "merchant": merchant,
        "description": item["name"],
        "gsi1pk": f"{pk}#MERCHANT#{merchant}",
        "gsi1sk": f"{day}#{expense_id}",
        "kind": item["kind"],
        "line": line,
        "code": item["code"],
        "quantity": item["quantity"],
        "unit": item["unit"],
        "unit_price": item["unit_price"],
        "receipt_key": receipt_key,
    }


def header_row(user, receipt, merchant, day, rows, s3_key):
    return {
        "pk": f"USER#{user}",
        "sk": f"RECEIPT#{receipt.access_key}",
        "kind": "receipt",
        "merchant": merchant,
        "date": day,
        "issuer_name": receipt.issuer_name,
        "issuer_cnpj": receipt.issuer_cnpj,
        "number": receipt.number,
        "series": receipt.series,
        "issued_at": receipt.issued_at,
        "protocol": receipt.protocol,
        "emission": receipt.emission,
        "subtotal": receipt.subtotal,
        "discount": receipt.discount,
        "total_paid": receipt.total_paid,
        "saved_total": sum((r["amount"] for r in rows), Decimal(0)),
        "payments": [{"method": p.method, "amount": p.amount} for p in receipt.payments],
        "change": receipt.change,
        "item_count": len(rows),
        "s3_key": s3_key,
        "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def find_header(user, receipt_key):
    return table().get_item(Key={"pk": f"USER#{user}", "sk": f"RECEIPT#{receipt_key}"}).get("Item")


def already_imported(header):
    return response(
        409,
        {
            "error": "This receipt was already imported.",
            "receipt_key": header["sk"].split("#", 1)[1],
            "imported_at": header.get("imported_at"),
        },
    )


# ---------- operations ----------
def import_receipt(user, event):
    receipt = parse(read_file(get_body(event)))
    header = find_header(user, receipt.access_key)
    if header:
        return already_imported(header)
    return response(200, {"receipt": receipt.to_dict()})


def save(user, event):
    body = get_body(event)
    raw = read_file(body)
    receipt = parse(raw)
    header = find_header(user, receipt.access_key)
    if header:
        return already_imported(header)
    merchant, day, items = parse_edited(body, receipt)  # all validation happens before the first write

    is_html = raw.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<")
    s3_key = f"receipts/{user}/{receipt.access_key}.{'html' if is_html else 'mht'}"
    # Same key for the same receipt: a retry overwrites the file instead of adding another.
    s3().put_object(
        Bucket=BUCKET,
        Key=s3_key,
        Body=redact_personal_data(raw),
        ContentType="text/html" if is_html else "multipart/related",
        ServerSideEncryption="AES256",
    )

    rows = [expense_row(user, receipt.access_key, merchant, day, n, item) for n, item in enumerate(items, start=1)]
    written = []
    try:
        for row in rows:
            table().put_item(Item=row)
            written.append(row)
        table().put_item(Item=header_row(user, receipt, merchant, day, rows, s3_key))  # last: the "committed" marker
    except Exception:
        for row in written:  # leave no half-saved receipt behind
            table().delete_item(Key={"pk": row["pk"], "sk": row["sk"]})
        raise

    saved_total = sum((r["amount"] for r in rows), Decimal(0))
    warnings = []
    if saved_total != receipt.total_paid:
        warnings.append(f"The saved amounts add up to {saved_total} but the receipt says {receipt.total_paid}.")
    return response(
        201,
        {
            "receipt_key": receipt.access_key,
            "count": len(rows),
            "total": saved_total,
            "warnings": warnings,
            "items": [public(r) for r in rows],
        },
    )


# ---------- entrypoint ----------
def lambda_handler(event, context):
    try:
        user = get_user(event)
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "").rstrip("/")

        if path == BASE_PATH + "/import":
            if method != "POST":
                raise HttpError(405, "Method not allowed")
            return import_receipt(user, event)
        if path == BASE_PATH:
            if method != "POST":
                raise HttpError(405, "Method not allowed")
            return save(user, event)
        raise HttpError(404, "Not found")

    except HttpError as err:
        return response(err.status, {"error": err.message})
    except Exception:  # noqa: BLE001 - last-resort handler: always answer with JSON
        print("Unhandled error", flush=True)
        import traceback

        traceback.print_exc()
        return response(500, {"error": "Internal server error"})
