"""
Shared parsing utilities for store scrapers.

Provides reusable functions for extracting and normalizing price values
from HTML text. All store scrapers use these helpers to avoid duplicating
price-parsing logic.

Contract:
    Input:  Raw price string (e.g. "₹3,499", "Rs. 2999.00", "3,499")
    Output: Float price value, or None if parsing fails
    Errors: Returns None on invalid input (never raises)
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# PUBLIC_INTERFACE
def extract_price(text: Optional[str]) -> Optional[float]:
    """
    Extract a numeric price from a string containing Indian Rupee formatting.

    Handles formats like:
      - "₹3,499"
      - "Rs. 2,999.00"
      - "INR 3499"
      - "3,499.00"
      - "₹ 3,499 .00"

    Args:
        text: Raw price string, possibly with currency symbols and commas

    Returns:
        Float price value, or None if no valid price found
    """
    if not text:
        return None

    # Remove currency symbols, "Rs", "INR", commas, and extra whitespace
    cleaned = text.strip()
    cleaned = re.sub(r'[₹$]', '', cleaned)
    cleaned = re.sub(r'(?i)(rs\.?|inr)', '', cleaned)
    cleaned = cleaned.replace(',', '').strip()

    # Extract the first number (integer or decimal)
    match = re.search(r'(\d+(?:\.\d{1,2})?)', cleaned)
    if match:
        try:
            price = float(match.group(1))
            # Sanity check: game prices should be between 50 and 100,000 INR
            if 50 <= price <= 100000:
                return price
        except ValueError:
            pass

    return None


# PUBLIC_INTERFACE
def extract_discount_percent(text: Optional[str]) -> Optional[float]:
    """
    Extract a discount percentage from text.

    Handles formats like:
      - "30% off"
      - "(25%)"
      - "Save 40%"
      - "-35%"

    Args:
        text: Raw text that may contain a discount percentage

    Returns:
        Float discount percentage, or None if no valid discount found
    """
    if not text:
        return None

    match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
    if match:
        try:
            pct = float(match.group(1))
            if 0 < pct < 100:
                return pct
        except ValueError:
            pass

    return None


# PUBLIC_INTERFACE
def compute_price_from_mrp_and_discount(
    mrp: Optional[float], discount_pct: Optional[float]
) -> Optional[float]:
    """
    Compute selling price from MRP and discount percentage.

    Used specifically for Amazon.in where the selling price sometimes
    needs to be derived from MRP and displayed discount.

    Args:
        mrp: Maximum Retail Price
        discount_pct: Discount percentage (e.g. 30 for 30%)

    Returns:
        Computed selling price, or None if inputs are invalid
    """
    if mrp is None or discount_pct is None:
        return None
    if mrp <= 0 or discount_pct <= 0 or discount_pct >= 100:
        return None

    return round(mrp * (1 - discount_pct / 100), 2)
