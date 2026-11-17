"""Hide staff mobile numbers from everything the assistant shows or speaks.

The school's website prints department heads' 8-digit mobiles («Утас 9…»). The
reception gives visitors a teacher's school e-mail, not a phone, and this project never
shows, reads out or publishes staff mobiles (CLAUDE.md, 11/09). The mobiles printed on the
school's pages start with 8 or 9 (11/17 count: 12 numbers); the school's own line (+976 7577
7799) starts with 7, an office line in the older field tests with 6, and a year range
(«2025-2026») with 1 or 2, so those stay. A spaced or hyphenated number («9911-2233») is
hidden only after +976 or a phone label («Утасны дугаар:», «Холбоо барих:»), so a price
range («8000-9000₮») stays. A value that is only a web address is left as it is.
"""
import re

HIDDEN = '[гар утсыг нуусан]'
_LABEL = r'(?:утас|утсаар|утсанд|утасны|залга\w*|холбоо\s+барих|phone|tel)'
_JOINED = r'(?:\+?976[\s-]?)?[89]\d{7}'
_SPLIT = r'(?:\+?976[\s-]?|' + _LABEL + r'[^\d\n]{0,20})[89]\d{3}[\s-]\d{4}'
# «99112233/88112233»: a slash may join two numbers; letters, dots, + and hyphens may not.
MOBILE = re.compile(r'(?<![\w.+-])(?:' + _SPLIT + '|' + _JOINED + r')(?![\w-])', re.I)
_URL = re.compile(r'https?://\S*')


def _hide(match):
    # Keep a leading label («Утасны дугаар: [гар утсыг нуусан]»), hide only the number.
    return re.match(r'[^\d+]*', match.group()).group() + HIDDEN


def hide_mobiles(value):
    """The same value with every staff mobile number replaced; other values are unchanged."""
    if isinstance(value, str):
        if not re.search(r'[89]\d{3}', value) or _URL.fullmatch(value):
            return value
        return MOBILE.sub(_hide, value)
    if isinstance(value, dict):
        return {key: hide_mobiles(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(hide_mobiles(item) for item in value)
    return value
