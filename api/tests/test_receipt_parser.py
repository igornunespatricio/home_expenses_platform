import json
from decimal import Decimal

import pytest
from receipt_fixtures import CNPJ, ISSUER, make_key, make_mht, receipt_html

from receipt_parser import (
    MAX_BYTES,
    ReceiptParseError,
    is_valid_access_key,
    parse_receipt,
    redact_personal_data,
)

RICE = ("ARROZ 5KG", "101", "1", "UN", "25,90", "25,90")
BEANS = ("FEIJAO 1KG", "102", "2", "UN", "8,50", "17,00")
CARD = ("Cartão de Crédito", "42,90")


def simple(**changes):
    args = {"items": [RICE, BEANS], "due": "42,90", "payments": [CARD]}
    return receipt_html(**{**args, **changes})


def parse(html, **mht):
    return parse_receipt(make_mht(html, **mht))


# ---------- the happy path
def test_parses_a_simple_receipt():
    receipt = parse(simple())

    assert receipt.issuer_name == ISSUER
    assert receipt.issuer_cnpj == "12.345.678/0001-95"
    assert (receipt.number, receipt.series) == (1234, 1)
    assert receipt.date == "2026-10-13"
    assert receipt.issued_at == "2026-10-13T16:37:40-03:00"
    assert receipt.protocol == "233262447712396"
    assert receipt.emission == "normal"
    assert receipt.total_paid == Decimal("42.90")
    assert receipt.subtotal is None
    assert receipt.discount == 0
    assert [(p.method, p.amount) for p in receipt.payments] == [("Cartão de Crédito", Decimal("42.90"))]
    assert receipt.change is None
    assert receipt.warnings == []
    assert is_valid_access_key(receipt.access_key)


def test_every_item_is_returned_with_all_its_fields():
    receipt = parse(simple())

    assert [(i.line, i.kind, i.code, i.name, i.quantity, i.unit, i.unit_price, i.total) for i in receipt.items] == [
        (1, "product", "101", "ARROZ 5KG", Decimal(1), "UN", Decimal("25.90"), Decimal("25.90")),
        (2, "product", "102", "FEIJAO 1KG", Decimal(2), "UN", Decimal("8.50"), Decimal("17.00")),
    ]


def test_repeated_identical_lines_are_all_kept():
    line = ("SAL ENO REG 2X5G", "76449", "1", "UN", "5,43", "5,43")
    receipt = parse(simple(items=[line, line, line], due="16,29", payments=[("Cartão de Crédito", "16,29")]))

    assert [i.line for i in receipt.items] == [1, 2, 3]
    assert receipt.warnings == []


def test_weighed_items_and_prices_without_decimals():
    tomato = ("TOMATE KG", "179", "0,41", "KG", "15,99", "6,55")  # 0.41 x 15.99 = 6.5559, printed 6.55
    food = ("RACAO", "016603", "1", "UN", "135", "135,00")
    receipt = parse(simple(items=[tomato, food], due="141,55", payments=[("Cartão de Crédito", "141,55")]))

    assert receipt.items[0].quantity == Decimal("0.41")
    assert receipt.items[0].total == Decimal("6.55")
    assert receipt.items[1].unit_price == Decimal(135)
    assert receipt.to_dict()["items"][1]["unit_price"] == "135.00"
    assert receipt.warnings == []


# ---------- discount
def test_discount_becomes_a_negative_item_so_lines_add_up_to_the_amount_paid():
    shampoo = ("SHAMPOO", "1", "1", "UN", "20,00", "20,00")
    soap = ("SABONETE", "2", "3", "UN", "3,50", "10,50")
    receipt = parse(
        simple(items=[shampoo, soap], subtotal="30,50", discount="2,50", due="28,00", payments=[("Cartão de Débito", "28,00")])
    )

    assert receipt.subtotal == Decimal("30.50")
    assert receipt.discount == Decimal("2.50")
    assert [i.kind for i in receipt.items] == ["product", "product", "discount"]
    last = receipt.items[-1]
    assert (last.line, last.name, last.quantity, last.total) == (3, "Desconto", 1, Decimal("-2.50"))
    assert sum(i.total for i in receipt.items) == receipt.total_paid
    assert receipt.warnings == []


# ---------- payments
def test_payment_with_change():
    ten = ("AGUA", "9", "1", "UN", "10,00", "10,00")
    receipt = parse(simple(items=[ten], due="10,00", payments=[("Dinheiro", "20,00")], change="10,00"))

    assert receipt.payments[0].amount == Decimal("20.00")
    assert receipt.change == Decimal("10.00")
    assert receipt.warnings == []


def test_several_payment_methods():
    item = ("CAFE", "7", "1", "UN", "30,00", "30,00")
    receipt = parse(simple(items=[item], due="30,00", payments=[("Cartão de Crédito", "10,00"), ("Dinheiro", "20,00")]))

    assert [(p.method, p.amount) for p in receipt.payments] == [
        ("Cartão de Crédito", Decimal("10.00")),
        ("Dinheiro", Decimal("20.00")),
    ]
    assert receipt.warnings == []


def test_contingency_receipts_are_flagged():
    assert parse(simple(contingency=True)).emission == "contingency"


# ---------- file formats
def test_quoted_printable_container():
    assert parse(simple(), quoted_printable=True).items[0].name == "ARROZ 5KG"


def test_plain_html_file():
    receipt = parse_receipt(simple().encode("utf-8"))

    assert receipt.total_paid == Decimal("42.90")


def test_script_content_is_ignored():
    # the fixture page has a script containing "Valor a pagar R$: 999,99"
    assert parse(simple()).total_paid == Decimal("42.90")


# ---------- privacy
def test_cpf_and_consumer_are_not_in_the_output():
    receipt = parse(simple(cpf="111.222.333-44"))

    dumped = json.dumps(receipt.to_dict(), ensure_ascii=False)
    assert "111.222.333-44" not in dumped
    assert "MARIA EXEMPLO" not in dumped
    assert "OPERADOR" not in dumped


def test_redact_personal_data_masks_cpf_only():
    raw = make_mht(simple(cpf="111.222.333-44"))

    redacted = redact_personal_data(raw)

    assert b"111.222.333-44" not in redacted
    assert b"XXX.XXX.XXX-XX" in redacted
    assert b"12.345.678/0001-95" in redacted  # the CNPJ is not a CPF
    assert parse_receipt(redacted).total_paid == Decimal("42.90")


# ---------- output
def test_to_dict_is_json_safe_with_money_as_strings():
    data = parse(simple()).to_dict()

    assert json.loads(json.dumps(data)) == data
    assert data["total_paid"] == "42.90"
    assert data["items"][1]["quantity"] == "2"
    assert data["items"][1]["total"] == "17.00"
    assert data["subtotal"] is None


# ---------- warnings: the file is readable but something does not add up
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"due": "40,00", "payments": [("Cartão de Crédito", "40,00")]}, "items add up to 42.90"),
        ({"declared": 5}, "5 items but 2 were found"),
        ({"payments": [("Cartão de Crédito", "10,00")]}, "payments add up to 10.00"),
        ({"items": [RICE, ("FEIJAO 1KG", "102", "2", "UN", "8,50", "19,00")], "due": "44,90", "payments": [("Cartão de Crédito", "44,90")]}, "Item 2"),
        ({"day": "13/11/2026", "key": make_key(yymm="2610")}, "issue month"),
    ],
)
def test_inconsistencies_are_warnings_not_errors(changes, expected):
    receipt = parse(simple(**changes))

    assert any(expected in warning for warning in receipt.warnings), receipt.warnings


# ---------- errors: not a usable receipt
@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"hello", "does not look like"),
        (b"", "does not look like"),
        (make_mht("<html><body>no receipt</body></html>"), "does not look like"),
        (b"x" * (MAX_BYTES + 1), "too large"),
    ],
)
def test_files_that_are_not_receipts(data, message):
    with pytest.raises(ReceiptParseError, match=message):
        parse_receipt(data)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"key": make_key(corrupt=True)}, "access key"),
        ({"key": make_key(model="55")}, "not a consumer receipt"),
        ({"cnpj_printed": "99.999.999/0001-99"}, "CNPJ"),
        ({"number": 1234, "key": make_key(number=999)}, "number"),
        ({"environment": "Homologação"}, "test"),
        ({"items": [], "due": "0,00", "payments": []}, "No items"),
        ({"day": "31/02/2026", "key": make_key(yymm="2602")}, "valid date"),
    ],
)
def test_unusable_receipts_are_rejected(changes, message):
    with pytest.raises(ReceiptParseError, match=message):
        parse(simple(**changes))


def test_cnpj_constant_matches_the_fixture():
    assert CNPJ == "12345678000195"
