"""Bulk discount rule: 5% off line items with quantity >= 10."""

from __future__ import annotations

from decimal import Decimal

from pricing.cart import LineItem


def qualifies_for_bulk_discount(item: LineItem) -> bool:
    """Return True if the line item qualifies for bulk discount."""
    raise NotImplementedError
