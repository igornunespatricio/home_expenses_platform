"""Parser for RJ NFC-e result pages (consultadfe.fazenda.rj.gov.br) saved as .mht or .html.

Standard library only, so the Lambda needs no extra packaging.

    receipt = parse_receipt(file_bytes)   # raises ReceiptParseError if it is not a readable receipt
    receipt.to_dict()                     # JSON-safe: money and quantities are strings

What comes back: the access key, issuer, number/series, issue date, every item line
(code, name, quantity, unit, unit price, line total), the payments and the totals.

A receipt-level discount is returned as one extra item with kind "discount" and a
negative total, so the lines always add up to the amount actually paid. Integrity
problems that do not make the file unusable (sums that do not match, ...) are listed in
`warnings` for the user to review instead of being rejected.

Not extracted on purpose: the consumer's CPF/name and the cashier's name. Use
`redact_personal_data` on the raw file before storing it.
"""

import email
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from email import policy
from html.parser import HTMLParser

MAX_BYTES = 2_000_000
CENT = Decimal("0.01")
NFCE_MODEL = "65"  # model code of the consumer receipt (NFC-e) inside the access key


class ReceiptParseError(ValueError):
    """The file is not a readable RJ NFC-e page. The message is safe to show to the user."""


@dataclass
class Item:
    line: int  # 1-based position on the receipt
    kind: str  # "product" or "discount"
    code: str
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total: Decimal  # negative for the discount line


@dataclass
class Payment:
    method: str
    amount: Decimal


@dataclass
class Receipt:
    access_key: str
    issuer_name: str
    issuer_cnpj: str
    number: int
    series: int
    issued_at: str  # ISO 8601 with offset, e.g. 2026-10-13T16:37:40-03:00
    date: str  # YYYY-MM-DD, the date to use on the expense
    protocol: str
    emission: str  # "normal" or "contingency"
    items: list[Item]
    subtotal: Decimal | None  # only printed when there is a discount
    discount: Decimal
    total_paid: Decimal
    payments: list[Payment]
    change: Decimal | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "access_key": self.access_key,
            "issuer_name": self.issuer_name,
            "issuer_cnpj": self.issuer_cnpj,
            "number": self.number,
            "series": self.series,
            "issued_at": self.issued_at,
            "date": self.date,
            "protocol": self.protocol,
            "emission": self.emission,
            "items": [
                {
                    "line": i.line,
                    "kind": i.kind,
                    "code": i.code,
                    "name": i.name,
                    "quantity": str(i.quantity),
                    "unit": i.unit,
                    "unit_price": str(_money(i.unit_price)),
                    "total": str(_money(i.total)),
                }
                for i in self.items
            ],
            "subtotal": None if self.subtotal is None else str(_money(self.subtotal)),
            "discount": str(_money(self.discount)),
            "total_paid": str(_money(self.total_paid)),
            "payments": [{"method": p.method, "amount": str(_money(p.amount))} for p in self.payments],
            "change": None if self.change is None else str(_money(self.change)),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------- public helpers
def is_valid_access_key(key: str) -> bool:
    """44 digits whose last digit is the modulo-11 check digit of the first 43."""
    if not re.fullmatch(r"\d{44}", key):
        return False
    total = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(key[:43])))
    remainder = total % 11
    check = 0 if remainder < 2 else 11 - remainder
    return int(key[43]) == check


def redact_personal_data(data: bytes) -> bytes:
    """Mask CPF numbers (###.###.###-##) in a raw file before it is stored.

    Names (consumer, cashier) are not touched, so keep the storage private and encrypted.
    """
    return _CPF.sub(b"XXX.XXX.XXX-XX", data)


_CPF = re.compile(rb"\d{3}\.\d{3}\.\d{3}-\d{2}")


def parse_receipt(data: bytes) -> Receipt:
    """Parse the bytes of a saved receipt page (.mht or plain .html)."""
    page = _Page()
    page.feed(_html_from_file(data))
    page.close()
    body = re.sub(r"\s+", " ", " ".join(page.text)).strip()

    # --- access key and issuer, cross-checked against each other
    access_key = re.sub(r"\D", "", "".join(page.captured["chave"]))
    if not is_valid_access_key(access_key):
        raise ReceiptParseError("The access key on the page is missing or invalid.")
    if access_key[20:22] != NFCE_MODEL:
        raise ReceiptParseError("This is not a consumer receipt (NFC-e).")
    if re.search(r"Ambiente de Homologa", body):
        raise ReceiptParseError("This receipt is from the test (homologação) environment.")

    issuer_name = _clean(page.captured["txtTopo"])
    if not issuer_name:
        raise ReceiptParseError("Could not find the issuer name.")
    issuer_cnpj = _find(r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", body, "the issuer CNPJ")
    if re.sub(r"\D", "", issuer_cnpj) != access_key[6:20]:
        raise ReceiptParseError("The CNPJ on the page does not match the access key.")

    match = re.search(
        r"Número:\s*(\d+)\s+Série:\s*(\d+)\s+Emissão:\s*(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2}:\d{2})([+-]\d{2}:\d{2})?",
        body,
    )
    if not match:
        raise ReceiptParseError("Could not find the receipt number and issue date.")
    number, series = int(match.group(1)), int(match.group(2))
    day, month, year, clock, offset = match.group(3, 4, 5, 6, 7)
    if number != int(access_key[25:34]) or series != int(access_key[22:25]):
        raise ReceiptParseError("The receipt number does not match the access key.")
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        raise ReceiptParseError("The issue date on the page is not a valid date.") from None

    # --- items
    items = [_parse_row(n, row) for n, row in enumerate(page.rows, start=1)]
    if not items:
        raise ReceiptParseError("No items were found on the page.")
    products = len(items)

    # --- totals (subtotal and discount are only printed when there is a discount)
    total_paid = _decimal(_find(r"Valor a pagar R\$:\s*([\d.,]+)", body, "the amount to pay"), "the amount to pay")
    subtotal = _optional_decimal(r"Valor total R\$:\s*([\d.,]+)", body)
    discount = _optional_decimal(r"Descontos R\$:\s*([\d.,]+)", body) or Decimal(0)
    declared = re.search(r"Qtd\. total de itens:\s*(\d+)", body)

    if discount > 0:
        items.append(
            Item(
                line=products + 1,
                kind="discount",
                code="",
                name="Desconto",
                quantity=Decimal(1),
                unit="UN",
                unit_price=-discount,
                total=-discount,
            )
        )

    payments, change = _parse_payments(body)

    protocol = re.search(r"Protocolo de Autoriza\S*\s*(\d+)", body)
    receipt = Receipt(
        access_key=access_key,
        issuer_name=issuer_name,
        issuer_cnpj=issuer_cnpj,
        number=number,
        series=series,
        issued_at=f"{year}-{month}-{day}T{clock}{offset or ''}",
        date=f"{year}-{month}-{day}",
        protocol=protocol.group(1) if protocol else "",
        emission="contingency" if "EMITIDA EM CONTING" in body else "normal",
        items=items,
        subtotal=subtotal,
        discount=discount,
        total_paid=total_paid,
        payments=payments,
        change=change,
    )
    receipt.warnings = _check(receipt, access_key, declared and int(declared.group(1)), products)
    return receipt


# ---------------------------------------------------------------- internals
def _html_from_file(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ReceiptParseError("The file is too large to be a receipt.")
    if data.lstrip(b"\xef\xbb\xbf \r\n\t")[:9].lower().startswith((b"<!doctype", b"<html", b"<!--")):
        return _decode(data, None)  # plain "HTML only" page

    message = email.message_from_bytes(data, policy=policy.default)  # .mht is a MIME container
    for part in message.walk():
        if part.get_content_type() != "text/html":
            continue
        payload = part.get_payload(decode=True)  # undoes base64 / quoted-printable
        if payload:
            html = _decode(payload, part.get_content_charset())
            if "tabResult" in html and "chave" in html:
                return html
    raise ReceiptParseError("This file does not look like a saved NFC-e page.")


def _decode(payload: bytes, charset: str | None) -> str:
    for encoding in (charset, "utf-8"):
        if encoding:
            try:
                return payload.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
    return payload.decode("latin-1")


_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_ITEM_CLASSES = frozenset({"txtTit", "RCod", "Rqtd", "RUN", "RvlUnit", "valor"})


class _Page(HTMLParser):
    """Collects the page text, the issuer/key spans and the rows of the items table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []  # (tag, capture, is items table)
        self.text: list[str] = []
        self.captured: dict[str, list[str]] = {"txtTopo": [], "chave": []}
        self.rows: list[dict[str, list[str]]] = []
        self._row: dict[str, list[str]] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in _VOID_TAGS:
            self.text.append(" ")
            return
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "tr" and any(entry[2] for entry in self.stack):
            self._finish_row()
            self._row = {}
        capture = None
        if "txtTopo" in classes:
            capture = "txtTopo"
        elif "chave" in classes:
            capture = "chave"
        elif self._row is not None and tag != "td":  # the td next to the value has the txtTit class too
            hit = classes & _ITEM_CLASSES
            if hit:
                capture = "row:" + next(iter(hit))
        self.stack.append((tag, capture, tag == "table" and attributes.get("id") == "tabResult"))
        self.text.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag in _VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                closed = self.stack[index:]
                del self.stack[index:]
                if tag == "tr" or any(entry[2] for entry in closed):
                    self._finish_row()
                break
        self.text.append(" ")

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        for _, capture, _ in self.stack:
            if capture is None:
                continue
            if capture.startswith("row:"):
                if self._row is not None:
                    self._row.setdefault(capture[4:], []).append(data)
            else:
                self.captured[capture].append(data)

    def _finish_row(self):
        if self._row:
            self.rows.append(self._row)
        self._row = None


def _clean(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _find(pattern: str, body: str, what: str) -> str:
    match = re.search(pattern, body)
    if not match:
        raise ReceiptParseError(f"Could not find {what}.")
    return match.group(1)


def _decimal(text: str, what: str) -> Decimal:
    """Brazilian number format: 1.234,56"""
    cleaned = text.strip()
    if not re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:,\d+)?", cleaned):
        raise ReceiptParseError(f"Could not read {what}: {cleaned[:30]!r}.")
    try:
        return Decimal(cleaned.replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise ReceiptParseError(f"Could not read {what}: {cleaned[:30]!r}.") from None


def _optional_decimal(pattern: str, body: str) -> Decimal | None:
    match = re.search(pattern, body)
    return _decimal(match.group(1), "a total") if match else None


def _money(value: Decimal) -> Decimal:
    """At least two decimal places (135 -> 135.00); more are kept (a 5.999 unit price)."""
    return value if value.as_tuple().exponent <= -2 else value.quantize(CENT)


def _parse_row(line: int, row: dict[str, list[str]]) -> Item:
    def text(key: str) -> str:
        if key not in row:
            raise ReceiptParseError(f"Item {line}: the {key} field is missing.")
        return _clean(row[key])

    def after_colon(key: str) -> str:
        value = text(key)
        if ":" not in value:
            raise ReceiptParseError(f"Item {line}: could not read the {key} field.")
        return value.split(":", 1)[1].strip()

    code = re.search(r"C.digo:\s*(.*?)\s*\)", text("RCod"))
    return Item(
        line=line,
        kind="product",
        code=code.group(1) if code else "",
        name=text("txtTit"),
        quantity=_decimal(after_colon("Rqtd"), f"the quantity of item {line}"),
        unit=after_colon("RUN"),
        unit_price=_decimal(after_colon("RvlUnit"), f"the unit price of item {line}"),
        total=_decimal(text("valor"), f"the total of item {line}"),
    )


_AMOUNT = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"


def _parse_payments(body: str) -> tuple[list[Payment], Decimal | None]:
    section = re.search(r"Valor pago R\$:\s*(.*?)\s*(?:Informa|$)", body)
    payments: list[Payment] = []
    change = None
    if section:
        for label, amount in re.findall(rf"(\D+?)\s+{_AMOUNT}(?=\s|$)", section.group(1)):
            label = label.strip()
            if label.lower().startswith("troco"):
                change = _decimal(amount, "the change")
            elif label:
                payments.append(Payment(label, _decimal(amount, "a payment")))
    return payments, change


def _check(receipt: Receipt, access_key: str, declared: int | None, products: int) -> list[str]:
    warnings = []
    lines = [i for i in receipt.items if i.kind == "product"]

    if declared is not None and declared != products:
        warnings.append(f"The receipt says {declared} items but {products} were found.")

    gross = sum((i.total for i in lines), Decimal(0))
    expected = receipt.subtotal if receipt.subtotal is not None else receipt.total_paid + receipt.discount
    if gross != expected:
        warnings.append(f"The items add up to {_money(gross)} but the receipt says {_money(expected)}.")

    for item in lines:
        if abs(item.quantity * item.unit_price - item.total) > CENT:
            warnings.append(f"Item {item.line}: quantity × unit price differs from the line total.")

    if receipt.payments:
        paid = sum((p.amount for p in receipt.payments), Decimal(0)) - (receipt.change or Decimal(0))
        if paid != receipt.total_paid:
            warnings.append(f"The payments add up to {_money(paid)} but the amount to pay is {_money(receipt.total_paid)}.")

    if receipt.date[2:4] + receipt.date[5:7] != access_key[2:6]:
        warnings.append("The issue month does not match the access key.")
    return warnings
