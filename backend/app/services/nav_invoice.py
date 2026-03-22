"""
nav_invoice.py
==============
Hungarian NAV Online Számla (Online Invoice System) API v3.0 client.

Official documentation : https://onlineszamla.nav.gov.hu/dokumentaciok
GitHub schemas          : https://github.com/nav-gov-hu/Online-Invoice
API v3.0 XSD schemas    : https://github.com/nav-gov-hu/Online-Invoice/tree/master/src/schemas/nav/gov/hu/OSA/3.0

Flow for each order
───────────────────
  1.  tokenExchange  → 5-minute single-use session token
  2.  manageInvoice  → submit InvoiceData XML (base64-encoded); receive transactionId
  3.  queryInvoiceStatus → poll until status is DONE or ABORTED

Crypto conventions (NAV v3.0)
──────────────────────────────
  passwordHash      = SHA-512( plain_password ).upper()
  requestSignature  = SHA3-512( requestId + timestamp + sigKey [+ invoiceHash...] ).upper()
  invoiceHash       = SHA3-512( base64_invoice_xml ).upper()   # per invoice in manageInvoice
  All hashes are plain hex strings (no prefix), UPPERCASE.

Invoice XML (InvoiceData)
──────────────────────────
  • Namespace : http://schemas.nav.gov.hu/OSA/3.0/data
  • Encoded   : UTF-8 bytes → base64 string
  • For B2C receipts: completenessIndicator=false, invoiceAppearance=PAPER
"""
from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger("app.nav")

# ── API endpoints ─────────────────────────────────────────────────────────────
_BASE_PROD = "https://api.onlineszamla.nav.gov.hu/invoiceService/v3"
_BASE_TEST = "https://api-test.onlineszamla.nav.gov.hu/invoiceService/v3"

# ── XML namespaces ────────────────────────────────────────────────────────────
_NS_API    = "http://schemas.nav.gov.hu/OSA/3.0/api"
_NS_COMMON = "http://schemas.nav.gov.hu/NTCA/1.0/common"
_NS_DATA   = "http://schemas.nav.gov.hu/OSA/3.0/data"

# ── Crypto helpers ────────────────────────────────────────────────────────────

def sha512_upper(text: str) -> str:
    """SHA-512 of UTF-8 encoded text → uppercase hex string."""
    return hashlib.sha512(text.encode("utf-8")).hexdigest().upper()


def sha3_512_upper(text: str) -> str:
    """SHA3-512 of UTF-8 encoded text → uppercase hex string."""
    return hashlib.sha3_512(text.encode("utf-8")).hexdigest().upper()


def make_request_id() -> str:
    """Generate a unique, NAV-compliant request ID (max 30 alphanumeric chars)."""
    return "RID" + uuid.uuid4().hex[:27].upper()


def make_timestamp() -> str:
    """Current UTC time in NAV ISO-8601 format."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def token_exchange_signature(request_id: str, timestamp: str, sig_key: str) -> str:
    return sha3_512_upper(request_id + timestamp + sig_key)


def manage_invoice_signature(
    request_id: str, timestamp: str, sig_key: str, invoice_base64_list: List[str]
) -> str:
    parts = request_id + timestamp + sig_key
    for b64 in invoice_base64_list:
        parts += sha3_512_upper(b64)
    return sha3_512_upper(parts)


# ── Supplier tax number parser ────────────────────────────────────────────────

@dataclass
class TaxNumber:
    taxpayer: str   # 8 digits
    vat_code: str   # 1 digit
    county:   str   # 2 digits


def parse_tax_number(full: str) -> TaxNumber:
    """
    Parse '12345678-1-23' or '12345678123' into TaxNumber parts.
    Falls back gracefully if format is unexpected.
    """
    clean = full.replace("-", "").strip()
    if len(clean) >= 11:
        return TaxNumber(taxpayer=clean[:8], vat_code=clean[8], county=clean[9:11])
    if len(clean) == 8:
        return TaxNumber(taxpayer=clean, vat_code="2", county="41")
    # best-effort
    return TaxNumber(taxpayer=clean[:8].ljust(8, "0"), vat_code="2", county="41")


# ── Money helpers ─────────────────────────────────────────────────────────────

def _d2(value) -> Decimal:
    """Round to 2 decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(value) -> str:
    """Format Decimal for NAV XML (2 decimal places)."""
    return str(_d2(value))


# ── Invoice XML builder ───────────────────────────────────────────────────────

@dataclass
class InvoiceLine:
    description: str
    quantity:    Decimal
    unit_price:  Decimal   # net (ex-VAT) per unit
    vat_rate:    Decimal   # e.g. Decimal("0.27") for 27%


@dataclass
class InvoiceRequest:
    invoice_number:     str
    issue_date:         date
    delivery_date:      date
    currency:           str          = "HUF"
    payment_method:     str          = "CASH"    # CASH / TRANSFER / CARD / OTHER
    payment_date:       date         = field(default_factory=date.today)
    supplier_name:      str          = ""
    supplier_tax_number:str          = ""        # full 11-char string
    supplier_country:   str          = "HU"
    supplier_postal:    str          = ""
    supplier_city:      str          = ""
    supplier_address:   str          = ""
    customer_name:      str          = "Magánszemély"
    lines:              List[InvoiceLine] = field(default_factory=list)


def build_invoice_xml(req: InvoiceRequest) -> str:
    """
    Build an InvoiceData XML string conforming to NAV Online Számla v3.0 schema.
    Returns a UTF-8 XML string.

    For B2C restaurant receipts:
      completenessIndicator = false  (reporting a paper invoice issued to customer)
      invoiceAppearance      = PAPER
      customerVatStatus      = PRIVATE_PERSON

    Reference: https://github.com/nav-gov-hu/Online-Invoice/blob/master/src/schemas/nav/gov/hu/OSA/3.0/invoiceData.xsd
    """
    tn = parse_tax_number(req.supplier_tax_number) if req.supplier_tax_number else None

    # ── Pre-compute totals ────────────────────────────────────────────────────
    @dataclass
    class VatBucket:
        rate:       Decimal
        net:        Decimal = Decimal("0")
        vat:        Decimal = Decimal("0")
        gross:      Decimal = Decimal("0")

    buckets: dict[str, VatBucket] = {}
    line_xmls = []

    for idx, line in enumerate(req.lines, start=1):
        net_total   = _d2(line.unit_price * line.quantity)
        vat_amount  = _d2(net_total * line.vat_rate)
        gross_total = _d2(net_total + vat_amount)
        vat_pct     = _d2(line.vat_rate * 100)          # e.g. 27.00

        bucket_key = str(line.vat_rate)
        if bucket_key not in buckets:
            buckets[bucket_key] = VatBucket(rate=line.vat_rate)
        b = buckets[bucket_key]
        b.net   += net_total
        b.vat   += vat_amount
        b.gross += gross_total

        line_xmls.append(f"""      <line>
        <lineNumber>{idx}</lineNumber>
        <lineDescription>{_esc(line.description)}</lineDescription>
        <quantity>{_fmt(line.quantity)}</quantity>
        <unitOfMeasure>PIECE</unitOfMeasure>
        <unitPrice>{_fmt(line.unit_price)}</unitPrice>
        <unitPriceHUF>{_fmt(line.unit_price)}</unitPriceHUF>
        <lineAmountsNormal>
          <lineNetAmountData>
            <lineNetAmount>{_fmt(net_total)}</lineNetAmount>
            <lineNetAmountHUF>{_fmt(net_total)}</lineNetAmountHUF>
          </lineNetAmountData>
          <lineVatRate>
            <vatPercentage>{_fmt(line.vat_rate)}</vatPercentage>
          </lineVatRate>
          <lineVatData>
            <lineVatAmount>{_fmt(vat_amount)}</lineVatAmount>
            <lineVatAmountHUF>{_fmt(vat_amount)}</lineVatAmountHUF>
          </lineVatData>
          <lineGrossAmountData>
            <lineGrossAmountNormal>{_fmt(gross_total)}</lineGrossAmountNormal>
            <lineGrossAmountNormalHUF>{_fmt(gross_total)}</lineGrossAmountNormalHUF>
          </lineGrossAmountData>
        </lineAmountsNormal>
      </line>""")

    # ── VAT summary ───────────────────────────────────────────────────────────
    summary_by_vat_xml = []
    total_net   = Decimal("0")
    total_vat   = Decimal("0")
    total_gross = Decimal("0")
    for b in buckets.values():
        total_net   += b.net
        total_vat   += b.vat
        total_gross += b.gross
        summary_by_vat_xml.append(f"""        <summaryByVatRate>
          <vatRate>
            <vatPercentage>{_fmt(b.rate)}</vatPercentage>
          </vatRate>
          <vatRateNetData>
            <vatRateNetAmount>{_fmt(b.net)}</vatRateNetAmount>
            <vatRateNetAmountHUF>{_fmt(b.net)}</vatRateNetAmountHUF>
          </vatRateNetData>
          <vatRateVatData>
            <vatRateVatAmount>{_fmt(b.vat)}</vatRateVatAmount>
            <vatRateVatAmountHUF>{_fmt(b.vat)}</vatRateVatAmountHUF>
          </vatRateVatData>
          <vatRateGrossData>
            <vatRateGrossAmount>{_fmt(b.gross)}</vatRateGrossAmount>
            <vatRateGrossAmountHUF>{_fmt(b.gross)}</vatRateGrossAmountHUF>
          </vatRateGrossData>
        </summaryByVatRate>""")

    supplier_tax_xml = ""
    if tn:
        supplier_tax_xml = f"""          <supplierTaxNumber>
            <taxpayerNumber>{tn.taxpayer}</taxpayerNumber>
            <vatCode>{tn.vat_code}</vatCode>
            <countyCode>{tn.county}</countyCode>
          </supplierTaxNumber>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<InvoiceData xmlns="{_NS_DATA}"
             xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <invoiceNumber>{_esc(req.invoice_number)}</invoiceNumber>
  <invoiceIssueDate>{req.issue_date.isoformat()}</invoiceIssueDate>
  <completenessIndicator>false</completenessIndicator>
  <invoiceMain>
    <invoice>
      <invoiceHead>
        <supplierInfo>
{supplier_tax_xml}
          <supplierName>{_esc(req.supplier_name)}</supplierName>
          <supplierAddress>
            <simpleAddress>
              <countryCode>{req.supplier_country}</countryCode>
              <postalCode>{_esc(req.supplier_postal)}</postalCode>
              <city>{_esc(req.supplier_city)}</city>
              <additionalAddressDetail>{_esc(req.supplier_address)}</additionalAddressDetail>
            </simpleAddress>
          </supplierAddress>
          <individualExemption>false</individualExemption>
        </supplierInfo>
        <customerInfo>
          <customerVatStatus>PRIVATE_PERSON</customerVatStatus>
          <customerName>{_esc(req.customer_name)}</customerName>
        </customerInfo>
        <invoiceDetail>
          <invoiceCategory>NORMAL</invoiceCategory>
          <invoiceDeliveryDate>{req.delivery_date.isoformat()}</invoiceDeliveryDate>
          <currencyCode>{req.currency}</currencyCode>
          <exchangeRate>1</exchangeRate>
          <paymentMethod>{req.payment_method}</paymentMethod>
          <paymentDate>{req.payment_date.isoformat()}</paymentDate>
          <invoiceAppearance>PAPER</invoiceAppearance>
        </invoiceDetail>
      </invoiceHead>
      <invoiceLines>
{chr(10).join(line_xmls)}
      </invoiceLines>
      <invoiceSummary>
        <summaryNormal>
{chr(10).join(summary_by_vat_xml)}
          <invoiceNetAmount>{_fmt(total_net)}</invoiceNetAmount>
          <invoiceNetAmountHUF>{_fmt(total_net)}</invoiceNetAmountHUF>
          <invoiceVatAmount>{_fmt(total_vat)}</invoiceVatAmount>
          <invoiceVatAmountHUF>{_fmt(total_vat)}</invoiceVatAmountHUF>
        </summaryNormal>
        <summaryGrossData>
          <invoiceGrossAmount>{_fmt(total_gross)}</invoiceGrossAmount>
          <invoiceGrossAmountHUF>{_fmt(total_gross)}</invoiceGrossAmountHUF>
        </summaryGrossData>
      </invoiceSummary>
    </invoice>
  </invoiceMain>
</InvoiceData>"""
    return xml


def _esc(text: str) -> str:
    """XML-escape a string value."""
    return (text or "").\
        replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").\
        replace('"', "&quot;").replace("'", "&apos;")


def encode_invoice(xml_str: str) -> str:
    """UTF-8 encode the invoice XML and return base64 string."""
    return base64.b64encode(xml_str.encode("utf-8")).decode("ascii")


# ── Request XML builders ──────────────────────────────────────────────────────

def _common_header(request_id: str, timestamp: str) -> str:
    return f"""  <common:header>
    <common:requestId>{request_id}</common:requestId>
    <common:timestamp>{timestamp}</common:timestamp>
    <common:requestVersion>3.0</common:requestVersion>
    <common:headerVersion>1.0</common:headerVersion>
  </common:header>"""


def _common_user(login: str, password_hash: str, tax_number: str, signature: str) -> str:
    return f"""  <common:user>
    <common:login>{login}</common:login>
    <common:passwordHash cryptoType="SHA-512">{password_hash}</common:passwordHash>
    <common:taxNumber>{tax_number}</common:taxNumber>
    <common:requestSignature cryptoType="SHA3-512">{signature}</common:requestSignature>
  </common:user>"""


def _common_software(tax_number: str) -> str:
    soft_id = f"KIOSK-{tax_number[:8]}"
    return f"""  <common:software>
    <common:softwareId>{soft_id}</common:softwareId>
    <common:softwareName>Restaurant Kiosk</common:softwareName>
    <common:softwareOperation>LOCAL_SOFTWARE</common:softwareOperation>
    <common:softwareMainVersion>1.0</common:softwareMainVersion>
    <common:softwareDevName>Restaurant Kiosk System</common:softwareDevName>
    <common:softwareDevContact>admin@restaurant.hu</common:softwareDevContact>
    <common:softwareDevCountryCode>HU</common:softwareDevCountryCode>
    <common:softwareSupportUrl>http://localhost</common:softwareSupportUrl>
  </common:software>"""


def build_token_exchange_request(
    login: str, password_hash: str, tax_number: str, sig_key: str
) -> Tuple[str, str, str]:
    """
    Build a TokenExchange request XML.
    Returns (xml_string, request_id, timestamp).
    """
    rid = make_request_id()
    ts  = make_timestamp()
    sig = token_exchange_signature(rid, ts, sig_key)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<TokenExchangeRequest xmlns="{_NS_API}"
                      xmlns:common="{_NS_COMMON}">
{_common_header(rid, ts)}
{_common_user(login, password_hash, tax_number, sig)}
{_common_software(tax_number)}
</TokenExchangeRequest>"""
    return xml, rid, ts


def build_manage_invoice_request(
    login: str, password_hash: str, tax_number: str, sig_key: str,
    exchange_token: str, invoice_base64: str,
) -> Tuple[str, str, str]:
    """
    Build a ManageInvoice (CREATE) request XML.
    Returns (xml_string, request_id, timestamp).
    """
    rid = make_request_id()
    ts  = make_timestamp()
    sig = manage_invoice_signature(rid, ts, sig_key, [invoice_base64])
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<ManageInvoiceRequest xmlns="{_NS_API}"
                      xmlns:common="{_NS_COMMON}">
{_common_header(rid, ts)}
{_common_user(login, password_hash, tax_number, sig)}
{_common_software(tax_number)}
  <exchangeToken>{exchange_token}</exchangeToken>
  <invoiceOperations>
    <compressedContent>false</compressedContent>
    <invoiceOperation>
      <index>1</index>
      <invoiceOperation>CREATE</invoiceOperation>
      <invoiceData>{invoice_base64}</invoiceData>
    </invoiceOperation>
  </invoiceOperations>
</ManageInvoiceRequest>"""
    return xml, rid, ts


def build_query_status_request(
    login: str, password_hash: str, tax_number: str, sig_key: str,
    transaction_id: str,
) -> Tuple[str, str, str]:
    """
    Build a QueryInvoiceStatus request XML.
    Returns (xml_string, request_id, timestamp).
    """
    rid = make_request_id()
    ts  = make_timestamp()
    sig = token_exchange_signature(rid, ts, sig_key)   # same signature scheme
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<QueryInvoiceStatusRequest xmlns="{_NS_API}"
                           xmlns:common="{_NS_COMMON}">
{_common_header(rid, ts)}
{_common_user(login, password_hash, tax_number, sig)}
{_common_software(tax_number)}
  <transactionId>{transaction_id}</transactionId>
  <returnOriginalRequest>false</returnOriginalRequest>
</QueryInvoiceStatusRequest>"""
    return xml, rid, ts


def build_query_taxpayer_request(
    login: str, password_hash: str, tax_number: str, sig_key: str,
    query_tax_number: str,
) -> Tuple[str, str, str]:
    """
    Build a QueryTaxpayer request (used for connection test).
    Returns (xml_string, request_id, timestamp).
    """
    rid = make_request_id()
    ts  = make_timestamp()
    sig = token_exchange_signature(rid, ts, sig_key)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<QueryTaxpayerRequest xmlns="{_NS_API}"
                      xmlns:common="{_NS_COMMON}">
{_common_header(rid, ts)}
{_common_user(login, password_hash, tax_number, sig)}
{_common_software(tax_number)}
  <taxNumber>{query_tax_number}</taxNumber>
</QueryTaxpayerRequest>"""
    return xml, rid, ts


# ── HTTP helpers ──────────────────────────────────────────────────────────────

_HEADERS = {"Content-Type": "application/xml", "Accept": "application/xml"}
_TIMEOUT = 30.0


async def _post_xml(base_url: str, endpoint: str, xml_body: str) -> str:
    """POST an XML request and return the raw response body as a string."""
    url = f"{base_url}/{endpoint}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, content=xml_body.encode("utf-8"), headers=_HEADERS)
        resp.raise_for_status()
        return resp.text


def _extract_text(xml_str: str, *tag_names: str) -> Optional[str]:
    """
    Search for a tag (with or without namespace prefix) in the XML and return its text.
    Tries each name in tag_names in order.
    """
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None
    for name in tag_names:
        # Try full namespace search
        for ns in (_NS_API, _NS_COMMON, _NS_DATA):
            el = root.find(f".//{{{ns}}}{name}")
            if el is not None and el.text:
                return el.text.strip()
        # Try without namespace
        el = root.find(f".//{name}")
        if el is not None and el.text:
            return el.text.strip()
    return None


def _extract_func_code(xml_str: str) -> str:
    return _extract_text(xml_str, "funcCode") or "UNKNOWN"


def _extract_error_message(xml_str: str) -> str:
    msg = _extract_text(xml_str, "message", "errorCode", "resultMessage")
    return msg or ""


# ── High-level API client ─────────────────────────────────────────────────────

@dataclass
class NAVCredentials:
    login:         str
    password_hash: str   # SHA-512 uppercase hex
    tax_number:    str   # 8 digits
    sig_key:       str
    test_mode:     bool = True

    @property
    def base_url(self) -> str:
        return _BASE_TEST if self.test_mode else _BASE_PROD


async def token_exchange(creds: NAVCredentials) -> str:
    """
    Perform a tokenExchange call.
    Returns the exchange token string on success.
    Raises ValueError with NAV error details on failure.
    """
    xml, rid, ts = build_token_exchange_request(
        creds.login, creds.password_hash, creds.tax_number, creds.sig_key
    )
    log.debug("tokenExchange  rid=%s  test=%s", rid, creds.test_mode)
    try:
        resp_xml = await _post_xml(creds.base_url, "tokenExchange", xml)
    except httpx.HTTPStatusError as e:
        raise ValueError(f"HTTP {e.response.status_code}: {e.response.text[:500]}")
    except httpx.RequestError as e:
        raise ValueError(f"Connection error: {e}")

    func_code = _extract_func_code(resp_xml)
    if func_code != "OK":
        err = _extract_error_message(resp_xml)
        raise ValueError(f"NAV tokenExchange failed: {func_code} — {err}")

    token = _extract_text(resp_xml, "encodedExchangeToken")
    if not token:
        raise ValueError("NAV tokenExchange: missing encodedExchangeToken in response")

    log.info("tokenExchange OK  rid=%s", rid)
    return token


async def submit_invoice(
    creds: NAVCredentials,
    invoice_req: InvoiceRequest,
) -> Tuple[str, str, str]:
    """
    Full invoice submission:
      1. tokenExchange
      2. build InvoiceData XML
      3. manageInvoice

    Returns (transaction_id, invoice_xml, invoice_base64).
    Raises ValueError on any failure.
    """
    # 1. Get token
    exchange_token = await token_exchange(creds)

    # 2. Build invoice XML
    invoice_xml    = build_invoice_xml(invoice_req)
    invoice_base64 = encode_invoice(invoice_xml)

    # 3. Submit
    req_xml, rid, ts = build_manage_invoice_request(
        creds.login, creds.password_hash, creds.tax_number, creds.sig_key,
        exchange_token, invoice_base64,
    )
    log.debug("manageInvoice  rid=%s  invoice=%s", rid, invoice_req.invoice_number)
    try:
        resp_xml = await _post_xml(creds.base_url, "manageInvoice", req_xml)
    except httpx.HTTPStatusError as e:
        raise ValueError(f"HTTP {e.response.status_code}: {e.response.text[:500]}")
    except httpx.RequestError as e:
        raise ValueError(f"Connection error: {e}")

    func_code = _extract_func_code(resp_xml)
    if func_code != "OK":
        err = _extract_error_message(resp_xml)
        raise ValueError(f"NAV manageInvoice failed: {func_code} — {err}")

    transaction_id = _extract_text(resp_xml, "transactionId")
    if not transaction_id:
        raise ValueError("NAV manageInvoice: missing transactionId in response")

    log.info(
        "manageInvoice OK  invoice=%s  transactionId=%s",
        invoice_req.invoice_number, transaction_id,
    )
    return transaction_id, invoice_xml, resp_xml


async def query_invoice_status(creds: NAVCredentials, transaction_id: str) -> str:
    """
    Query the processing status of a submitted invoice.
    Returns the invoice status string: RECEIVED / PROCESSING / SAVED / DONE / ABORTED
    """
    xml, rid, _ = build_query_status_request(
        creds.login, creds.password_hash, creds.tax_number, creds.sig_key, transaction_id
    )
    try:
        resp_xml = await _post_xml(creds.base_url, "queryInvoiceStatus", xml)
    except httpx.HTTPStatusError as e:
        raise ValueError(f"HTTP {e.response.status_code}: {e.response.text[:500]}")
    except httpx.RequestError as e:
        raise ValueError(f"Connection error: {e}")

    func_code = _extract_func_code(resp_xml)
    if func_code != "OK":
        err = _extract_error_message(resp_xml)
        raise ValueError(f"NAV queryInvoiceStatus failed: {func_code} — {err}")

    status = _extract_text(resp_xml, "invoiceStatus")
    return status or "UNKNOWN"


async def test_connection(creds: NAVCredentials) -> str:
    """
    Test credentials by calling queryTaxpayer with the configured tax number.
    Returns 'OK' or an error description string.
    """
    xml, rid, _ = build_query_taxpayer_request(
        creds.login, creds.password_hash, creds.tax_number, creds.sig_key,
        creds.tax_number,
    )
    try:
        resp_xml = await _post_xml(creds.base_url, "queryTaxpayer", xml)
    except httpx.HTTPStatusError as e:
        return f"HTTP {e.response.status_code}: {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Connection error: {e}"

    func_code = _extract_func_code(resp_xml)
    if func_code == "OK":
        return "OK"
    return f"{func_code}: {_extract_error_message(resp_xml)}"


# ── Invoice number generator ──────────────────────────────────────────────────

def next_invoice_number(prefix: str, current_seq: int, current_year: Optional[int]) -> Tuple[str, int, int]:
    """
    Compute the next invoice number.
    Resets the sequence counter each calendar year.
    Returns (invoice_number, new_seq, year).
    """
    today = date.today()
    year  = today.year
    if current_year != year:
        seq = 1        # year changed → reset
    else:
        seq = (current_seq or 0) + 1
    number = f"{prefix}/{year}/{seq:06d}"
    return number, seq, year


# ── Order → InvoiceRequest converter ─────────────────────────────────────────

def order_to_invoice_request(
    order,             # SQLAlchemy Order instance (with .lines loaded)
    invoice_number: str,
    nav_cfg,           # NavSettings instance
    tax_rate: Decimal,
) -> InvoiceRequest:
    """
    Convert a database Order object into an InvoiceRequest ready for XML generation.
    The order.lines must be eagerly loaded before calling this function.
    """
    today     = date.today()
    order_dt  = order.created_at.date() if order.created_at else today
    vat_rate  = (tax_rate / 100).quantize(Decimal("0.0001"))  # e.g. 0.27

    lines = []
    for line in order.lines:
        # unit_price in DB is gross (incl. VAT); compute net for NAV XML
        gross_per_unit = Decimal(str(line.unit_price))
        net_per_unit   = (gross_per_unit / (1 + vat_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        lines.append(InvoiceLine(
            description = line.name,
            quantity    = Decimal(str(line.quantity)),
            unit_price  = net_per_unit,
            vat_rate    = vat_rate,
        ))

    payment_map = {
        "cash":   "CASH",
        "card":   "CARD",
        "online": "TRANSFER",
    }
    nav_payment = payment_map.get((order.payment_method or "").lower(), "CASH")

    return InvoiceRequest(
        invoice_number      = invoice_number,
        issue_date          = today,
        delivery_date       = order_dt,
        currency            = "HUF",
        payment_method      = nav_payment,
        payment_date        = order_dt,
        supplier_name       = nav_cfg.supplier_name or "",
        supplier_tax_number = nav_cfg.supplier_tax_number or "",
        supplier_country    = nav_cfg.supplier_country or "HU",
        supplier_postal     = nav_cfg.supplier_postal_code or "",
        supplier_city       = nav_cfg.supplier_city or "",
        supplier_address    = nav_cfg.supplier_address_detail or "",
        customer_name       = order.customer_name or "Magánszemély",
        lines               = lines,
    )
