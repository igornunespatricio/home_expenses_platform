"""Builds synthetic NFC-e pages (same markup as the RJ portal) so the repo holds no real receipts."""

import quopri

ISSUER = "MERCADO EXEMPLO LTDA"
CNPJ = "12345678000195"


def make_key(cnpj=CNPJ, number=1234, series=1, yymm="2610", model="65", corrupt=False):
    # UF(2) AAMM(4) CNPJ(14) model(2) series(3) number(9) emission type(1) code(8) check digit(1)
    base = f"33{yymm}{cnpj}{model}{series:03d}{number:09d}" + "1" + "12345678"
    total = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(base)))
    remainder = total % 11
    check = 0 if remainder < 2 else 11 - remainder
    if corrupt:
        check = (check + 1) % 10
    return base + str(check)


def _cnpj(digits):
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _item(n, name, code, qty, unit, price, total):
    return f"""<tr id="Item + {n}">
<td valign="top"><span class="txtTit">{name}</span><span class="RCod">
\t\t\t\t\t\t\t\t\t\t(Código:
\t\t\t\t\t\t\t\t\t\t{code}
\t\t\t\t\t\t\t\t\t\t)
\t\t\t\t\t\t\t\t\t</span>
<br>
<span class="Rqtd"><strong>Qtde.:</strong>{qty}</span><span class="RUN"><strong>UN: </strong>{unit}</span><span class="RvlUnit"><strong>Vl. Unit.:</strong>
\t\t\t\t\t\t\t\t\t\t&nbsp;
\t\t\t\t\t\t\t\t\t\t{price}</span></td><td class="txtTit noWrap" valign="top" align="right">
\t\t\t\t\t\t\t\t\tVl. Total
\t\t\t\t\t\t\t\t\t<br>
<span class="valor">{total}</span></td>
</tr>
"""


def receipt_html(
    items,
    due,
    payments,
    *,
    subtotal=None,
    discount=None,
    change=None,
    declared=None,
    issuer=ISSUER,
    cnpj=CNPJ,
    number=1234,
    series=1,
    day="13/10/2026",
    time="16:37:40",
    contingency=False,
    cpf=None,
    environment="Produção",
    key=None,
    cnpj_printed=None,
):
    """items: (name, code, quantity, unit, unit price, line total), all as printed on the page."""
    key = key or make_key(cnpj, number, series, yymm=day[8:10] + day[3:5])
    spaced_key = " ".join(key[i : i + 4] for i in range(0, 44, 4))
    rows = "".join(_item(n, *item) for n, item in enumerate(items, start=1))
    declared = len(items) if declared is None else declared

    totals = f'<label>Qtd. total de itens:</label><span class="totalNumb">{declared}</span>'
    if discount is not None:
        totals += f'<label>Valor total R$:</label><span class="totalNumb">{subtotal}</span>'
        totals += f'<label>Descontos R$:</label><span class="totalNumb">{discount}</span>'
    totals += f'<label>Valor a pagar R$:</label><span class="totalNumb txtMax">{due}</span>'
    totals += '<label>Forma de pagamento:</label><span class="totalNumb txtTitR">Valor pago R$:</span>'
    for method, amount in payments:
        totals += f'<label class="tx">\n\t\t{method}\n\t</label><span class="totalNumb">{amount}</span>'
    if change is not None:
        totals += f'<label class="tx">Troco </label><span class="totalNumb">{change}</span>'
    totals += '<label class="txtObs">Informação dos Tributos Totais Incidentes (Lei Federal 12.741/2012)&nbsp;R$</label><span class="totalNumb txtObs">5,23</span>'

    consumer = f"CPF: {cpf} Nome: MARIA EXEMPLO" if cpf else "Consumidor não identificado"
    emission = "EMITIDA EM CONTINGÊNCIA" if contingency else "EMISSÃO NORMAL"
    return f"""<!DOCTYPE html><html><head><title>NFC-e</title><style>.x {{ color: red }}</style></head><body>
<script>var Número = "Valor a pagar R$: 999,99";</script>
<div class="text"><div class="txtTopo" id="u20">{issuer}</div>
<div class="text">
\t\t\t\t\t\t\t\tCNPJ:
\t\t\t\t\t\t\t\t{cnpj_printed or _cnpj(cnpj)}</div>
<div class="text">Rua Exemplo
\t\t\t\t\t\t\t,
\t\t\t\t\t\t\t100
\t\t\t\t\t\t\t,
\t\t\t\t\t\t\tCentro
\t\t\t\t\t\t\t,
\t\t\t\t\t\t\tRIO DE JANEIRO
\t\t\t\t\t\t\t,
\t\t\t\t\t\t\tRJ</div></div>
<table data-filter="true" id="tabResult" cellspacing="0" cellpadding="0" align="center" border="0">
<tbody>{rows}</tbody></table>
<div class="txtRight" id="totalNota">{totals}</div>
<ul><li><strong>{emission}</strong><br><br><strong>Número: </strong>{number}<strong> Série: </strong>{series}<strong> Emissão: </strong>{day} {time}-03:00
\t\t\t\t\t\t\t\t- Via Consumidor 2<br><br><strong>Protocolo de Autorização: </strong>233262447712396       {day}
        às
      {time}-03:00<br><br><strong>
\t\t\t\t\t\t\t\t\t\tAmbiente de {environment} -
\t\t\t\t\t\t\t\t\tVersão XML:
\t\t\t\t\t\t\t\t\t4.00
\t\t\t\t\t\t\t\t\t- Versão XSLT: 2.07
\t\t\t\t\t\t\t\t</strong></li></ul>
<ul><li>Consulte pela Chave de Acesso em www.fazenda.rj.gov.br/nfce/consulta<br><br><strong>Chave de acesso:</strong><br><span class="chave">{spaced_key}</span></li></ul>
<ul><li>{consumer}</li></ul>
<ul><li>Trib aprox R$: 2,98 Fed e 4,89 Est;2112 - OPERADOR EXEMPLO;Obrigado - Volte sempre!</li></ul>
</body></html>"""


def make_mht(html, *, quoted_printable=False):
    """Wrap the page in a MIME container like Chrome's "Save as MHTML"."""
    boundary = "----MultipartBoundary--test"
    if quoted_printable:
        body = quopri.encodestring(html.encode("utf-8"))
        encoding = b"quoted-printable"
    else:
        body = html.encode("utf-8")
        encoding = b"binary"
    nl = b"\r\n"
    return b"".join(
        [
            b"From: <Saved by Blink>", nl,
            b"Snapshot-Content-Location: https://example.invalid/consultaNFCe", nl,
            b"Subject: DOCUMENTO AUXILIAR", nl,
            b"MIME-Version: 1.0", nl,
            b'Content-Type: multipart/related;\r\n\ttype="text/html";\r\n\tboundary="', boundary.encode(), b'"', nl, nl,
            b"--", boundary.encode(), nl,
            b"Content-Type: text/html", nl,
            b"Content-ID: <frame-1@mhtml.blink>", nl,
            b"Content-Transfer-Encoding: ", encoding, nl,
            b"Content-Location: https://example.invalid/consultaNFCe/result.faces", nl, nl,
            body, nl,
            b"--", boundary.encode(), nl,
            b"Content-Type: text/css", nl,
            b"Content-Transfer-Encoding: binary", nl,
            b"Content-Location: https://example.invalid/style.css", nl, nl,
            b".x { color: red }", nl,
            b"--", boundary.encode(), nl,
            b"Content-Type: text/html", nl,
            b"Content-Transfer-Encoding: binary", nl, nl,
            b"<html><body>loading</body></html>", nl,
            b"--", boundary.encode(), b"--", nl,
        ]
    )
