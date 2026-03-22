"""
Thermal printer service via ESC/POS over TCP (port 9100).
Works with most network-enabled receipt/kitchen printers.
"""
import socket
import logging
from typing import Optional

logger = logging.getLogger("printer")


def _esc(cmd: bytes) -> bytes:
    return cmd


ESC_INIT     = b'\x1b\x40'
ESC_ALIGN_C  = b'\x1b\x61\x01'   # center
ESC_ALIGN_L  = b'\x1b\x61\x00'   # left
ESC_BOLD_ON  = b'\x1b\x45\x01'
ESC_BOLD_OFF = b'\x1b\x45\x00'
ESC_BIG      = b'\x1d\x21\x11'   # double width + height
ESC_NORMAL   = b'\x1d\x21\x00'
CUT          = b'\x1d\x56\x41\x03'
FEED         = b'\n'


def _send(ip: str, port: int, data: bytes):
    try:
        with socket.create_connection((ip, port), timeout=5) as s:
            s.sendall(data)
    except Exception as e:
        logger.error(f"Printer error {ip}:{port} – {e}")


def print_kitchen_ticket(order, printer_ip: str, printer_port: int = 9100):
    """Print kitchen order ticket."""
    buf = bytearray()
    buf += ESC_INIT
    buf += ESC_ALIGN_C
    buf += ESC_BIG + b"ORDER #%04d\n" % order.queue_number + ESC_NORMAL
    buf += ESC_BOLD_ON + b"------------------------\n" + ESC_BOLD_OFF
    buf += ESC_ALIGN_L

    for line in order.lines:
        qty_name = f"{line.quantity}x {line.name}".encode()
        price    = f"  {float(line.line_total):.2f}\n".encode()
        buf += ESC_BOLD_ON + qty_name + ESC_BOLD_OFF + price
        for cust in line.customizations:
            buf += f"   + {cust.option_name}\n".encode()

    buf += b"------------------------\n"
    if order.note:
        buf += ESC_BOLD_ON + b"NOTE: " + order.note.encode() + b"\n" + ESC_BOLD_OFF

    buf += b"\n\n"
    buf += CUT
    _send(printer_ip, printer_port, bytes(buf))


def print_receipt(order, restaurant_name: str, footer: str,
                  currency: str, printer_ip: str, printer_port: int = 9100):
    """Print customer receipt."""
    buf = bytearray()
    buf += ESC_INIT
    buf += ESC_ALIGN_C
    buf += ESC_BOLD_ON + restaurant_name.encode() + b"\n" + ESC_BOLD_OFF
    buf += b"========================\n"
    buf += ESC_BIG + b"#%04d\n" % order.queue_number + ESC_NORMAL
    buf += b"========================\n"
    buf += ESC_ALIGN_L

    for line in order.lines:
        buf += ESC_BOLD_ON + f"{line.quantity}x {line.name}".encode() + ESC_BOLD_OFF
        buf += f"  {currency}{float(line.line_total):.2f}\n".encode()
        for cust in line.customizations:
            buf += f"   + {cust.option_name}".encode()
            if float(cust.extra_price) > 0:
                buf += f"  +{currency}{float(cust.extra_price):.2f}".encode()
            buf += b"\n"

    buf += b"------------------------\n"
    buf += f"Subtotal:  {currency}{float(order.subtotal):.2f}\n".encode()
    if float(order.tax_amount) > 0:
        buf += f"Tax:       {currency}{float(order.tax_amount):.2f}\n".encode()
    buf += ESC_BOLD_ON + f"TOTAL:     {currency}{float(order.total_amount):.2f}\n".encode() + ESC_BOLD_OFF
    buf += b"------------------------\n"
    buf += f"Payment:   {order.payment_method or 'N/A'}\n".encode()
    buf += b"========================\n"
    buf += ESC_ALIGN_C + footer.encode() + b"\n"
    buf += b"\n\n"
    buf += CUT
    _send(printer_ip, printer_port, bytes(buf))
