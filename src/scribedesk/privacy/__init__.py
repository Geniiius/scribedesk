# SPDX-License-Identifier: MIT
"""Anonymisation réversible des données personnelles."""

from __future__ import annotations

from .patterns import ACRONYM_STOPWORDS, DEFAULT_RULES, RULE_DESCRIPTIONS, Rule, build_rules
from .redactor import PRESERVE_INSTRUCTION, Entity, Redaction, Redactor, StreamRestorer

__all__ = [
    "ACRONYM_STOPWORDS",
    "DEFAULT_RULES",
    "PRESERVE_INSTRUCTION",
    "RULE_DESCRIPTIONS",
    "Entity",
    "Redaction",
    "Redactor",
    "Rule",
    "StreamRestorer",
    "build_rules",
]
