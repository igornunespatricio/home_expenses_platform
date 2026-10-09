"""Expense tracker API: Lambda behind API Gateway (HTTP API, payload v2) with a Cognito JWT authorizer.

Routes (all under /api/expenses):
  POST   /api/expenses        create
  GET    /api/expenses        list  (?month=YYYY-MM, ?merchant=nike)
  GET    /api/expenses/{id}   get one
  PUT    /api/expenses/{id}   update
  DELETE /api/expenses/{id}   delete

{id} is the item's sort key (EXP#<date>#<uuid>), URL-encoded.
The owner is always the JWT 'sub' claim, never something the client sends.
"""

import json
import os
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "")
GSI_NAME = os.environ.get("GSI_NAME", "gsi1")
BASE_PATH = "/api/expenses"

_table = None


def table():
    """Create the DynamoDB table handle lazily (keeps imports/tests free of AWS calls)."""
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


# ---------- helpers ----------
class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Not serializable: {type(value)}")


def response(status, body=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": "" if body is None else json.dumps(body, default=_json_default),
    }


def clean(value, field):
    if not isinstance(value, str) or not value.strip():
        raise HttpError(400, f"'{field}' is required")
    return value.strip().lower()


def parse_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HttpError(400, "'amount' must be a number")
    if not amount.is_finite() or amount <= 0:
        raise HttpError(400, "'amount' must be greater than 0")
    return amount.quantize(Decimal("0.01"))


def parse_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise HttpError(400, "'date' must be YYYY-MM-DD")


def parse_month(value):
    try:
        year, month = value.split("-")
        if len(year) != 4 or len(month) != 2 or not 1 <= int(month) <= 12:
            raise ValueError
        return f"{int(year):04d}-{int(month):02d}"
    except (AttributeError, ValueError):
        raise HttpError(400, "'month' must be YYYY-MM")


def build_item(user, expense_id, data):
    """Validate input and build the DynamoDB item."""
    expense_date = parse_date(data.get("date"))
    merchant = clean(data.get("merchant"), "merchant")
    pk = f"USER#{user}"
    description = data.get("description") or ""
    if not isinstance(description, str):
        raise HttpError(400, "'description' must be text")
    return {
        "pk": pk,
        "sk": f"EXP#{expense_date}#{expense_id}",
        "amount": parse_amount(data.get("amount")),
        "date": expense_date,
        "category": clean(data.get("category"), "category"),
        "merchant": merchant,
        "description": description.strip(),
        "gsi1pk": f"{pk}#MERCHANT#{merchant}",
        "gsi1sk": f"{expense_date}#{expense_id}",
    }


def public(item):
    """What the client sees: no internal keys, sk exposed as 'id'."""
    out = {k: v for k, v in item.items() if k not in ("pk", "sk", "gsi1pk", "gsi1sk")}
    out["id"] = item["sk"]
    return out


def get_user(event):
    try:
        return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except KeyError:
        raise HttpError(401, "Unauthorized")


def get_body(event):
    try:
        data = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        raise HttpError(400, "Body must be valid JSON")
    if not isinstance(data, dict):
        raise HttpError(400, "Body must be a JSON object")
    return data


def valid_id(expense_id):
    parts = expense_id.split("#")
    if len(parts) != 3 or parts[0] != "EXP" or not parts[2]:
        raise HttpError(400, "Invalid id")
    return expense_id


# ---------- operations ----------
def create(user, event):
    item = build_item(user, uuid.uuid4().hex, get_body(event))
    table().put_item(Item=item)
    return response(201, public(item))


def list_expenses(user, event):
    params = event.get("queryStringParameters") or {}
    month = parse_month(params["month"]) if params.get("month") else None
    pk = f"USER#{user}"

    if params.get("merchant"):
        merchant = clean(params["merchant"], "merchant")
        condition = Key("gsi1pk").eq(f"{pk}#MERCHANT#{merchant}")
        if month:
            condition &= Key("gsi1sk").begins_with(month)
        query = {"IndexName": GSI_NAME, "KeyConditionExpression": condition}
    else:
        condition = Key("pk").eq(pk) & Key("sk").begins_with(f"EXP#{month}" if month else "EXP#")
        query = {"KeyConditionExpression": condition}

    items = []
    while True:
        result = table().query(**query)
        items.extend(result["Items"])
        if "LastEvaluatedKey" not in result:
            break
        query["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    # Newest first
    items.sort(key=lambda i: i["sk"], reverse=True)
    return response(200, {"items": [public(i) for i in items], "count": len(items)})


def fetch(user, expense_id):
    result = table().get_item(Key={"pk": f"USER#{user}", "sk": expense_id})
    item = result.get("Item")
    if not item:
        raise HttpError(404, "Expense not found")
    return item


def get_one(user, expense_id):
    return response(200, public(fetch(user, expense_id)))


def update(user, expense_id, event):
    existing = fetch(user, expense_id)
    changes = get_body(event)
    merged = {
        "amount": existing["amount"],
        "date": existing["date"],
        "category": existing["category"],
        "merchant": existing["merchant"],
        "description": existing.get("description", ""),
    }
    merged.update({k: v for k, v in changes.items() if k in merged})

    suffix = expense_id.split("#", 2)[2]
    item = build_item(user, suffix, merged)
    table().put_item(Item=item)

    # The date is part of the sort key: if it changed, the old item must go.
    if item["sk"] != expense_id:
        table().delete_item(Key={"pk": item["pk"], "sk": expense_id})
    return response(200, public(item))


def delete(user, expense_id):
    try:
        table().delete_item(
            Key={"pk": f"USER#{user}", "sk": expense_id},
            ConditionExpression="attribute_exists(pk)",
        )
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise HttpError(404, "Expense not found")
        raise
    return response(204)


# ---------- entrypoint ----------
def lambda_handler(event, context):
    try:
        user = get_user(event)
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "")

        if path != BASE_PATH and not path.startswith(BASE_PATH + "/"):
            raise HttpError(404, "Not found")
        expense_id = unquote(path[len(BASE_PATH):].strip("/"))

        if not expense_id:
            if method == "POST":
                return create(user, event)
            if method == "GET":
                return list_expenses(user, event)
            raise HttpError(405, "Method not allowed")

        valid_id(expense_id)
        if method == "GET":
            return get_one(user, expense_id)
        if method == "PUT":
            return update(user, expense_id, event)
        if method == "DELETE":
            return delete(user, expense_id)
        raise HttpError(405, "Method not allowed")

    except HttpError as err:
        return response(err.status, {"error": err.message})
    except Exception:
        # Details go to CloudWatch, not to the client
        print("Unhandled error", flush=True)
        import traceback

        traceback.print_exc()
        return response(500, {"error": "Internal server error"})
