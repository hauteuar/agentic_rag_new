
import re
from typing import Tuple

# Very simple PII redaction (extend for production)
PII_PATTERNS = [
    (re.compile(r"\b\d{13,19}\b"), "[REDACTED_CARD]"),  # card-like
    (re.compile(r"\b\d{3}-\d{3}-\d{4}\b"), "[REDACTED_PHONE]"),
    (re.compile(r"\b\d{9}\b"), "[REDACTED_SSN_OR_NAS]"),
]

def redact_for_logs(text: str) -> str:
    red = text
    for pat, rep in PII_PATTERNS:
        red = pat.sub(rep, red)
    return red
