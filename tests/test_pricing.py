"""
Hommy Cottage - Pricing Calculation & Generator Tests
Validates reservation arithmetic, tax computations, and unique reference codes.
"""
from datetime import date
from routes.bookings import generate_booking_code, generate_txn_ref
from config import Config


def test_booking_code_format():
    """Verify booking codes follow HC-YYYY-XXXXXX alphanumeric format."""
    code = generate_booking_code()
    assert code.startswith(f"HC-{date.today().year}-")
    assert len(code) >= 12


def test_transaction_ref_format():
    """Verify simulated transaction codes follow TXN-HC-XXXXXXXX format."""
    ref = generate_txn_ref()
    assert ref.startswith("TXN-HC-")
    assert len(ref) >= 14


def test_pricing_and_tax_calculation():
    """Verify reservation duration, subtotal, 12% GST, and total amounts."""
    nights = 3
    base_rate = 3800.00
    gst_rate = Config.GST_TAX_RATE  # 0.12

    subtotal = nights * base_rate
    expected_tax = round(subtotal * gst_rate, 2)
    grand_total = subtotal + expected_tax

    assert subtotal == 11400.00
    assert expected_tax == 1368.00
    assert grand_total == 12768.00


def test_pricing_with_decimal_types():
    """Verify Decimal arithmetic works without Decimal/float mismatch."""
    from decimal import Decimal, ROUND_HALF_UP
    nights = 5
    base_rate = Decimal("3800.00")
    subtotal = base_rate * nights
    tax_rate = Decimal(str(Config.GST_TAX_RATE))
    tax_amount = (subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_amount = subtotal + tax_amount

    assert subtotal == Decimal("19000.00")
    assert tax_amount == Decimal("2280.00")
    assert total_amount == Decimal("21280.00")
