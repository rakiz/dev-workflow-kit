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
        number = float(cleaned)
    except ValueError:
        raise TransformError("not a currency amount: %r" % value)
    if not math.isfinite(number):
        raise TransformError("not a currency amount: %r" % value)
    return round(number, 2)


def round2(value):
    """Parse a float and round it to 2 decimals."""
    try:
        number = float(value.strip())
    except ValueError:
        raise TransformError("not a number: %r" % value)
    if not math.isfinite(number):
        raise TransformError("not a number: %r" % value)
    return round(number, 2)


def date_iso(value):
    """'MM/DD/YYYY' -> 'YYYY-MM-DD'."""
    parts = value.strip().split("/")
    if len(parts) != 3 or len(parts[2]) != 4:
        raise TransformError("not a MM/DD/YYYY date: %r" % value)
    month, day, year = (p.strip() for p in parts)
    if not all(p.isascii() and p.isdigit() for p in (month, day, year)):
        raise TransformError("not a MM/DD/YYYY date: %r" % value)
    return "%s-%02d-%02d" % (year, int(month), int(day))


_BOOLEAN_FORMS = {"yes": 1.0, "true": 1.0, "no": 0.0, "false": 0.0}


def boolean(value):
    """yes/true -> 1.0, no/false -> 0.0 (case-insensitive, surrounding
    whitespace ignored like the other numeric transforms)."""
    result = _BOOLEAN_FORMS.get(value.strip().lower())
    if result is None:
        raise TransformError("not a boolean: %r" % value)
    return result


REGISTRY = {
    "trim": trim,
    "upper": upper,
    "lower": lower,
    "currency_amount": currency_amount,
    "round2": round2,
    "date_iso": date_iso,
    "boolean": boolean,
}


def apply(name, value):
    """Apply the named transform to a raw cell. An empty name is a
    passthrough; an unknown name raises TransformError."""
    if not name:
        return value
    fn = REGISTRY.get(name)
    if fn is None:
        raise TransformError("unknown transform: %r" % name)
    return fn(value)
