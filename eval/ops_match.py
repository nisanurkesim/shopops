# Execution match for ops answers (brief section 9.1): are the agent's result rows the
# same as the rows of the golden SQL? Column names are ignored, only values count.
# A number matches when it is the golden value correctly rounded to the digits the
# agent shows (0.0672 matches 0.067218, 0.0677 does not). Text is compared without case.
# Row order counts only when the question asks for an order (top N).
from decimal import Decimal


def shown_decimals(value: float) -> int:
    """Digits after the decimal point as the value is written: 0.0672 -> 4, 12.5 -> 1."""
    exponent = Decimal(repr(value)).as_tuple().exponent
    return max(0, -exponent)


def values_match(shown, golden) -> bool:
    if isinstance(golden, str) or isinstance(shown, str):
        return str(shown).strip().lower() == str(golden).strip().lower()
    if shown is None or golden is None:
        return shown is golden
    if isinstance(shown, int) and not isinstance(shown, bool):
        return float(golden) == shown
    tolerance = 0.5 * 10 ** -shown_decimals(float(shown)) + 1e-9
    return abs(float(shown) - float(golden)) <= tolerance


def row_matches(shown_row: list, golden_row: list) -> bool:
    """Every golden value is found in the shown row (each shown value used once)."""
    free = list(shown_row)
    for g in golden_row:
        for i, s in enumerate(free):
            if values_match(s, g):
                del free[i]
                break
        else:
            return False
    return True


def rows_match(shown_rows: list, golden_rows: list, order_matters: bool) -> bool:
    """The shown rows contain the golden rows (extra rows are allowed, for example all
    months when the question asks for six). With order_matters the first rows must be
    the golden rows in the same order."""
    if order_matters:
        return (len(shown_rows) >= len(golden_rows)
                and all(row_matches(s, g) for s, g in zip(shown_rows, golden_rows)))
    free = list(shown_rows)
    for g in golden_rows:
        for i, s in enumerate(free):
            if row_matches(s, g):
                del free[i]
                break
        else:
            return False
    return True
