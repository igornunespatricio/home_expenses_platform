import base64
import json
from decimal import Decimal

import pytest
from receipt_fixtures import make_mht, receipt_html

import receipts_handler
from receipt_parser import parse_receipt

RICE = ("ARROZ 5KG", "101", "1", "UN", "25,90", "25,90")
BEANS = ("FEIJAO 1KG", "102", "2", "UN", "8,50", "17,00")
SOAP = ("SABONETE", "2", "3", "UN", "3,50", "10,50")


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = {"body": Body, **kwargs}


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(receipts_handler, "_s3", fake)
    monkeypatch.setattr(receipts_handler, "BUCKET", "test-bucket")
    return fake


@pytest.fixture
def call(table, s3):
    """Call the receipts Lambda like API Gateway would. Returns (status, parsed_json_or_None)."""

    def run(method, path, body=None, user="user-1"):
        event = {
            "rawPath": path,
            "body": None if body is None else json.dumps(body),
            "requestContext": {"http": {"method": method}},
        }
        if user:
            event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": user}}}
        result = receipts_handler.lambda_handler(event, None)
        text = result["body"]
        return result["statusCode"], (json.loads(text) if text else None)

    return run


def page(**changes):
    args = {"items": [RICE, BEANS], "due": "42,90", "payments": [("Cartão de Crédito", "42,90")]}
    return make_mht(receipt_html(**{**args, **changes}))


def b64(raw):
    return base64.b64encode(raw).decode()


def draft(raw, **changes):
    """What the app sends back after the user reviewed the parsed receipt."""
    parsed = parse_receipt(raw).to_dict()
    receipt = {"merchant": "Mercado", "category": "Groceries", "date": parsed["date"], "items": parsed["items"]}
    return {"file": b64(raw), "receipt": {**receipt, **changes}}


# ---------- import: parse and check, never write
def test_import_returns_the_draft_and_writes_nothing(call, table, s3):
    status, body = call("POST", "/api/receipts/import", {"file": b64(page())})

    assert status == 200
    assert body["receipt"]["total_paid"] == "42.90"
    assert [i["name"] for i in body["receipt"]["items"]] == ["ARROZ 5KG", "FEIJAO 1KG"]
    assert table.items == {}
    assert s3.objects == {}


def test_import_of_an_already_saved_receipt_is_a_conflict(call):
    raw = page()
    call("POST", "/api/receipts", draft(raw))

    status, body = call("POST", "/api/receipts/import", {"file": b64(raw)})

    assert status == 409
    assert body["receipt_key"] == parse_receipt(raw).access_key


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({}, 400),
        ({"file": 123}, 400),
        ({"file": "not base64!!"}, 400),
        ({"file": b64(b"hello")}, 422),
        ({"file": "A" * 3_000_000}, 413),
    ],
)
def test_import_rejects_bad_files(call, body, status):
    assert call("POST", "/api/receipts/import", body)[0] == status


def test_import_gives_the_parser_message_for_unreadable_receipts(call):
    status, body = call("POST", "/api/receipts/import", {"file": b64(b"hello")})

    assert status == 422
    assert "does not look like" in body["error"]


def test_requests_without_a_user_are_unauthorized(call):
    assert call("POST", "/api/receipts/import", {"file": b64(page())}, user=None)[0] == 401
    assert call("POST", "/api/receipts", {}, user=None)[0] == 401


# ---------- save
def test_save_stores_the_file_item_rows_and_the_receipt_row(call, table, s3):
    raw = page(cpf="111.222.333-44")
    key = parse_receipt(raw).access_key

    status, body = call("POST", "/api/receipts", draft(raw))

    assert status == 201
    assert (body["receipt_key"], body["count"], body["total"], body["warnings"]) == (key, 2, 42.9, [])

    stored = s3.objects[("test-bucket", f"receipts/user-1/{key}.mht")]
    assert b"111.222.333-44" not in stored["body"]  # CPF masked
    assert b"XXX.XXX.XXX-XX" in stored["body"]
    assert stored["ServerSideEncryption"] == "AES256"

    rice = table.items[("USER#user-1", f"EXP#2026-10-13#{key}-001")]
    assert rice["amount"] == Decimal("25.90")
    assert rice["description"] == "ARROZ 5KG"
    assert (rice["merchant"], rice["category"]) == ("mercado", "groceries")  # normalized like /api/expenses
    assert (rice["quantity"], rice["unit"], rice["unit_price"], rice["code"]) == (1, "UN", Decimal("25.90"), "101")
    assert (rice["kind"], rice["line"], rice["receipt_key"]) == ("product", 1, key)
    assert rice["gsi1pk"] == "USER#user-1#MERCHANT#mercado"
    assert rice["gsi1sk"] == f"2026-10-13#{key}-001"

    header = table.items[("USER#user-1", f"RECEIPT#{key}")]
    assert header["item_count"] == 2
    assert header["total_paid"] == Decimal("42.90")
    assert header["saved_total"] == Decimal("42.90")
    assert header["issuer_cnpj"] == "12.345.678/0001-95"
    assert header["s3_key"] == f"receipts/user-1/{key}.mht"
    assert header["payments"] == [{"method": "Cartão de Crédito", "amount": Decimal("42.90")}]
    assert len(table.items) == 3


def test_the_discount_is_saved_as_a_negative_item(call, table):
    raw = page(items=[RICE, SOAP], subtotal="36,40", discount="3,40", due="33,00", payments=[("Dinheiro", "33,00")])

    status, body = call("POST", "/api/receipts", draft(raw))

    assert status == 201
    assert body["count"] == 3
    discount = next(i for i in body["items"] if i["kind"] == "discount")
    assert (discount["amount"], discount["description"], discount["quantity"]) == (-3.4, "Desconto", 1)
    assert body["total"] == 33.0


def test_edits_made_during_review_are_what_gets_saved(call, table):
    raw = page()
    parsed = parse_receipt(raw).to_dict()
    items = parsed["items"]
    items[0] = {**items[0], "name": "Arroz integral 5kg", "total": "27.90", "unit_price": "27.90", "category": "Pantry"}

    status, body = call("POST", "/api/receipts", draft(raw, items=items))

    assert status == 201
    assert body["total"] == 44.9
    assert body["warnings"] == ["The saved amounts add up to 44.90 but the receipt says 42.90."]
    first, second = body["items"]
    assert (first["description"], first["amount"], first["category"]) == ("Arroz integral 5kg", 27.9, "pantry")
    assert second["category"] == "groceries"  # receipt-level category is the default


def test_saving_twice_is_a_conflict_and_keeps_the_first_save(call, table):
    raw = page()
    call("POST", "/api/receipts", draft(raw))
    before = {key: dict(value) for key, value in table.items.items()}

    status, _ = call("POST", "/api/receipts", draft(raw, merchant="Other"))

    assert status == 409
    assert table.items == before


def test_saved_rows_show_up_in_the_normal_expense_list_without_the_receipt_row(call, api):
    raw = page(items=[RICE, SOAP], subtotal="36,40", discount="3,40", due="33,00", payments=[("Dinheiro", "33,00")])
    call("POST", "/api/receipts", draft(raw))

    status, body = api("GET", "/api/expenses", query={"month": "2026-10"})

    assert status == 200
    assert body["count"] == 3
    assert round(sum(e["amount"] for e in body["items"]), 2) == 33.0  # the discount subtracts
    status, body = api("GET", "/api/expenses", query={"merchant": "mercado"})
    assert body["count"] == 3


def test_editing_a_saved_row_keeps_the_receipt_fields(call, api):
    raw = page()
    _, saved = call("POST", "/api/receipts", draft(raw))
    row = saved["items"][1]

    status, body = api("PUT", "/api/expenses/" + row["id"].replace("#", "%23"), {"category": "Pantry"})

    assert status == 200
    assert body["category"] == "pantry"
    assert (body["quantity"], body["unit_price"], body["receipt_key"], body["kind"]) == (
        2,
        8.5,
        saved["receipt_key"],
        "product",
    )


def test_a_saved_discount_row_can_only_be_edited_to_another_negative_amount(call, api):
    raw = page(items=[RICE, SOAP], subtotal="36,40", discount="3,40", due="33,00", payments=[("Dinheiro", "33,00")])
    _, saved = call("POST", "/api/receipts", draft(raw))
    row_id = saved["items"][-1]["id"].replace("#", "%23")

    assert api("PUT", "/api/expenses/" + row_id, {"amount": 5})[0] == 400
    status, body = api("PUT", "/api/expenses/" + row_id, {"amount": -4})
    assert (status, body["amount"]) == (200, -4)


# ---------- save: validation happens before any write
@pytest.mark.parametrize(
    "changes",
    [
        {"merchant": " "},
        {"category": None},
        {"date": "13/10/2026"},
        {"items": []},
        {"items": "nope"},
        {"items": [{"name": "X", "quantity": "1", "unit_price": "1", "total": "0"}]},
        {"items": [{"name": " ", "quantity": "1", "unit_price": "1", "total": "1"}]},
        {"items": [{"name": "X", "quantity": "abc", "unit_price": "1", "total": "1"}]},
        {"items": [{"name": "X", "quantity": "0", "unit_price": "1", "total": "1"}]},
        {"items": [{"name": "X", "quantity": "1", "unit_price": "1", "total": "1", "kind": "gift"}]},
        {"items": [{"kind": "discount", "name": "Desconto", "total": "2.00"}]},
        {"items": [{"name": "X", "quantity": "1", "unit_price": "1", "total": "1"}] * 301},
    ],
)
def test_invalid_review_data_is_rejected_and_nothing_is_written(call, table, s3, changes):
    raw = page()

    status, body = call("POST", "/api/receipts", draft(raw, **changes))

    assert status == 400
    assert "error" in body
    assert table.items == {}
    assert s3.objects == {}


def test_missing_review_data_is_rejected(call, table):
    assert call("POST", "/api/receipts", {"file": b64(page())})[0] == 400
    assert table.items == {}


# ---------- save: a failure leaves nothing half-saved, and a retry works
def test_a_failed_write_removes_the_rows_already_written_and_a_retry_succeeds(call, table, monkeypatch):
    raw = page()
    real_put = table.put_item
    calls = {"n": 0}

    def flaky(Item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("throttled")
        real_put(Item)

    monkeypatch.setattr(table, "put_item", flaky)

    assert call("POST", "/api/receipts", draft(raw))[0] == 500
    assert table.items == {}

    monkeypatch.setattr(table, "put_item", real_put)
    status, body = call("POST", "/api/receipts", draft(raw))
    assert (status, body["count"]) == (201, 2)
    assert len(table.items) == 3


# ---------- routing
@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/receipts", 405),
        ("GET", "/api/receipts/import", 405),
        ("PUT", "/api/receipts", 405),
        ("POST", "/api/receipts/other", 404),
        ("POST", "/api/expenses", 404),
    ],
)
def test_routing_errors(call, method, path, expected):
    assert call(method, path, {})[0] == expected


def test_a_trailing_slash_is_accepted(call):
    assert call("POST", "/api/receipts/import/", {"file": b64(page())})[0] == 200
