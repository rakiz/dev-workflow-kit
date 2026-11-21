"""Parse duration strings such as '45s', '90m', '1h30m' and '2h' into seconds."""
import re


def parse_duration(text):
    """Return the duration in seconds, or None when the text is not a valid duration."""
    m = re.match(r"(\d+)s", text)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(\d+)h", text)
    if m:
        return int(m.group(1)) * 3600
    return None
