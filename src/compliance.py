"""Healthcare-advertising and brand guardrails for generated copy.

NeuroAxis is a regulated provider. Generated text must not claim CQC
registration, promise cures or guaranteed outcomes, diagnose the reader, name
prescription medications, make unsubstantiated superiority claims, or reference
Trustpilot widgets/logos. ``check(text)`` returns a list of human-readable
violation strings (empty == clean).

The list is deliberately conservative: false positives cost one regeneration;
false negatives put a non-compliant claim on a clinic's public feed.
"""

from __future__ import annotations

import re

# (compiled pattern, explanation). Patterns are matched case-insensitively.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcqc[\s-]*(registered|accredited|approved|certified)\b", re.I),
     "implies CQC registration (locked wording: 'Operating to CQC standards' only)"),
    (re.compile(r"\bregistered with (the )?cqc\b", re.I),
     "implies CQC registration"),
    (re.compile(r"\b(cure|cures|curing|cured)\b", re.I),
     "promises a cure"),
    (re.compile(r"\bguarantee(d|s)?\b", re.I),
     "makes a guarantee"),
    (re.compile(r"\bfix(es|ed|ing)? your\b", re.I),
     "promises to 'fix' the reader"),
    (re.compile(r"\byou (have|might have|probably have) adhd\b", re.I),
     "diagnoses/asserts the reader has ADHD"),
    (re.compile(r"\b(methylphenidate|lisdexamfetamine|elvanse|vyvanse|concerta|"
                r"ritalin|atomoxetine|strattera|adderall)\b", re.I),
     "names a prescription medication"),
    (re.compile(r"\bwe prescribe\b", re.I),
     "implies a prescription outcome"),
    (re.compile(r"\b(the )?(fastest|quickest|cheapest|best|number one|#1|leading)\b"
                r"[^.!?]*\b(uk|britain|clinic|assessment|service|provider)\b", re.I),
     "unsubstantiated superiority claim"),
    (re.compile(r"\btrustpilot\b(?!\s+5)", re.I),
     "Trustpilot reference other than the plain-text '5★ Patient Reviews' link"),
]


def check(text: str) -> list[str]:
    """Return a list of guideline violations found in ``text`` (empty if clean)."""
    if not text:
        return []
    found: list[str] = []
    for pattern, explanation in _RULES:
        if pattern.search(text):
            found.append(explanation)
    return found
