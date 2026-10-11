import json
from decimal import Decimal
from urllib.parse import quote

import pytest

NEW = {
    "amount": 42.9,
    "date": "2026-10-05",
    "category": "Supermarket",
    "merchant": "Guanabara",
    "description": "  Weekly groceries ",
}


def item_path(expense_id):
    return "/api/expenses/" + quote(expense_id, safe="")


def create(api, user="user-1", **changes):
    status, body = api("POST", "/api/expenses", {**NEW, **changes}, user=user)
    assert status == 201, body
    return body


# ---------- create ----------
def test_create_normalizes_and_stores_the_expense(api, table):
    status, body = api("POST", "/api/expenses", NEW)

    assert status == 201
    assert body["merchant"] == "guanabara"
    assert body["category"] == "supermarket"
    assert body["description"] == "Weekly groceries"
    assert body["amount"] == 42.9
    assert body["id"].startswith("EXP#2026-10-05#")
    # Internal keys never leave the API
    assert "pk" not in body and "gsi1pk" not in body

    stored = table.items[("USER#user-1", body["id"])]
    assert stored["gsi1pk"] == "USER#user-1#MERCHANT#guanabara"
    assert stored["amount"] == Decimal("42.90")


@pytest.mark.parametrize(
    "change",
    [
        {"amount": 0},
        {"amount": -5},
        {"amount": "abc"},
        {"date": "05/10/2026"},
        {"merchant": "  "},
        {"category": None},
    ],
)
def test_create_rejects_invalid_input(api, table, change):
    status, body = api("POST", "/api/expenses", {**NEW, **change})

    assert status == 400
    assert "error" in body
    assert table.items == {}


def test_request_without_a_user_is_unauthorized(api, table):
    status, _ = api("POST", "/api/expenses", NEW, user=None)

    assert status == 401
    assert table.items == {}


# ---------- list ----------
def test_list_returns_only_the_users_month_newest_first(api):
    create(api, date="2026-10-02")
    create(api, date="2026-10-20")
    create(api, date="2026-09-30")  # other month
    create(api, user="user-2", date="2026-10-10")  # other user

    status, body = api("GET", "/api/expenses", query={"month": "2026-10"})

    assert status == 200
    assert body["count"] == 2
    assert [e["date"] for e in body["items"]] == ["2026-10-20", "2026-10-02"]


def test_list_filters_by_merchant_ignoring_case(api):
    create(api, merchant="Guanabara")
    create(api, merchant="Nike")
    create(api, merchant="Nike", date="2026-10-07")

    status, body = api("GET", "/api/expenses", query={"merchant": "NIKE"})

    assert status == 200
    assert body["count"] == 2
    assert {e["merchant"] for e in body["items"]} == {"nike"}


def test_list_rejects_a_bad_month(api):
    status, body = api("GET", "/api/expenses", query={"month": "2026-13"})

    assert status == 400
    assert "month" in body["error"]


# ---------- get, update, delete ----------
def test_get_is_scoped_to_the_owner(api):
    expense = create(api)

    assert api("GET", item_path(expense["id"]))[0] == 200
    assert api("GET", item_path(expense["id"]), user="user-2")[0] == 404


def test_update_keeps_the_id_when_the_date_is_unchanged(api, table):
    expense = create(api)

    status, body = api("PUT", item_path(expense["id"]), {"amount": 50})

    assert status == 200
    assert body["id"] == expense["id"]
    assert body["amount"] == 50
    assert body["merchant"] == "guanabara"  # untouched fields stay
    assert len(table.items) == 1


def test_update_with_a_new_date_moves_the_expense(api, table):
    expense = create(api)

    status, body = api("PUT", item_path(expense["id"]), {"date": "2026-11-02"})

    assert status == 200
    assert body["id"].startswith("EXP#2026-11-02#")
    assert body["id"].split("#")[2] == expense["id"].split("#")[2]  # same uuid
    assert list(table.items) == [("USER#user-1", body["id"])]  # old key is gone


def test_delete_removes_the_expense_then_reports_not_found(api, table):
    expense = create(api)

    assert api("DELETE", item_path(expense["id"])) == (204, None)
    assert table.items == {}
    assert api("DELETE", item_path(expense["id"]))[0] == 404


# ---------- routing and errors ----------
@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/other", 404),
        ("PATCH", "/api/expenses", 405),
        ("GET", "/api/expenses/not-an-id", 400),
    ],
)
def test_routing_errors(api, method, path, expected):
    assert api(method, path)[0] == expected


def test_unexpected_errors_return_a_generic_500(api, table, monkeypatch):
    def boom(**_):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(table, "put_item", boom)

    status, body = api("POST", "/api/expenses", NEW)

    assert status == 500
    assert body == {"error": "Internal server error"}
    assert "secret" not in json.dumps(body)
