"""Shared test setup: an in-memory stand-in for the DynamoDB table and a small API caller."""

import json
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

# Make `import handler` work whether pytest runs from api/ or from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _matches(item, condition):
    """Evaluate the boto3 Key(...) conditions the handler builds (=, begins_with, AND)."""
    expression = condition.get_expression()
    operator = expression["operator"]
    left, right = expression["values"]
    if operator == "AND":
        return _matches(item, left) and _matches(item, right)
    value = item.get(left.name)
    if operator == "=":
        return value == right
    if operator == "begins_with":
        return isinstance(value, str) and value.startswith(right)
    raise NotImplementedError(operator)


class FakeTable:
    """Just enough of a DynamoDB Table for the handler. Items live in a dict."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def delete_item(self, Key, ConditionExpression=None):
        key = (Key["pk"], Key["sk"])
        if ConditionExpression and key not in self.items:
            error = {"Error": {"Code": "ConditionalCheckFailedException"}}
            raise ClientError(error, "DeleteItem")
        self.items.pop(key, None)

    def query(self, KeyConditionExpression, **_):
        # The merchant index (IndexName) is served by the same dict: items carry gsi1pk/gsi1sk.
        return {
            "Items": [dict(i) for i in self.items.values() if _matches(i, KeyConditionExpression)]
        }


@pytest.fixture
def table(monkeypatch):
    import handler

    fake = FakeTable()
    monkeypatch.setattr(handler, "_table", fake)
    return fake


@pytest.fixture
def api(table):
    """Call the Lambda like API Gateway would. Returns (status_code, parsed_json_or_None)."""
    import handler

    def call(method, path, body=None, query=None, user="user-1"):
        event = {
            "rawPath": path,
            "body": None if body is None else json.dumps(body),
            "queryStringParameters": query,
            "requestContext": {"http": {"method": method}},
        }
        if user:
            event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": user}}}
        response = handler.lambda_handler(event, None)
        text = response["body"]
        return response["statusCode"], (json.loads(text) if text else None)

    return call
