"""Column transforms for reportgen.

A rules file maps a column name to a transform name; the registry below is
the single source of truth for what those names mean. Each transform takes
the raw string cell and returns the transformed value — numeric transforms
return floats, everything else returns strings.

The registry is versioned: every cache entry is stamped with the registry
version it was produced under (cache.REGISTRY_VERSION, stamped by
make_entry) and the version is compared at lookup, so a summary written
under an older registry is never reused.
"""


import datetime
import math


class TransformError(Exception):
    """Raised when a cell cannot be transformed under its column's rule."""


def trim(value):
    return value.strip()


def upper(value):
    return value.upper()


def lower(value):
    return value.lower()


def currency_amount(value):
    """'$1,234.5' -> 1234.5 (float, rounded to 2 decimals)."""
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        num = float(cleaned)
    except ValueError:
        raise TransformError("not a currency amount: %r" % value)
    if not math.isfinite(num):
        raise TransformError("not a currency amount: %r" % value)
    return round(num, 2)


def round2(value):
    """Parse a float and round it to 2 decimals."""
    try:
        num = float(value.strip())
    except ValueError:
        raise TransformError("not a number: %r" % value)
    if not math.isfinite(num):
        raise TransformError("not a number: %r" % value)
    return round(num, 2)


def boolean(value):
    """Case-insensitive yes/true -> 1.0, no/false -> 0.0."""
    if not isinstance(value, str):
        raise TransformError("not a boolean: %r" % value)
    cleaned = value.strip().lower()
    if cleaned in ("yes", "true"):
        return 1.0
    if cleaned in ("no", "false"):
        return 0.0
    raise TransformError("not a boolean: %r" % value)


def date_iso(value):
    """'MM/DD/YYYY' -> 'YYYY-MM-DD'."""
    parts = value.strip().split("/")
    if len(parts) != 3:
        raise TransformError("not a MM/DD/YYYY date: %r" % value)
    month, day, year = (p.strip() for p in parts)
    if len(year) != 4 or not (1 <= len(month) <= 2 and 1 <= len(day) <= 2):
        raise TransformError("not a MM/DD/YYYY date: %r" % value)
    if not (month.isascii() and day.isascii() and year.isascii()
            and month.isdigit() and day.isdigit() and year.isdigit()):
        raise TransformError("not a MM/DD/YYYY date: %r" % value)
    try:
        dt = datetime.date(int(year), int(month), int(day))
    except ValueError:
        raise TransformError("not a MM/DD/YYYY date: %r" % value)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


REGISTRY = {
    "trim": trim,
    "upper": upper,
    "lower": lower,
    "currency_amount": currency_amount,
    "round2": round2,
    "boolean": boolean,
    "date_iso": date_iso,
}


def apply(name, value):
    """Apply the named transform to a raw cell. An empty name is a
    passthrough; an unknown name raises TransformError."""
    if not name:
        return value
    fn = REGISTRY.get(name)
    if fn is None:
        raise TransformError("unknown transform: %r" % name)
    res = fn(value)
    if isinstance(res, bool) or not isinstance(res, (str, float)):
        raise TransformError("invalid transform result for %r: %r" % (name, res))
    if isinstance(res, float) and not math.isfinite(res):
        raise TransformError("invalid transform result for %r: %r" % (name, res))
    return res
