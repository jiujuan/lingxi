"""Billing helpers used by the invoice pipeline."""

TAX_RATE = 1.2


def add_tax(amount):
    """Return the amount after applying the standard tax rate."""
    return amount * TAX_RATE
