"""Declarative rule-set configuration loader (ADR-014).

Rules are authored as an ordered TOML ``[[rule]]`` array and compiled into the
:class:`~fetcher_service.rules.RuleSet` the service evaluates. Three rule types
are supported:

``iiif``
    IIIF Image API origin (:class:`~fetcher_service.rules.IIIFImageRule`).
    Fields: ``host``, ``mirror_id``, optional ``path_prefix`` (list of segments,
    default ``["iiif"]``). Semantic normalization (rotation/quality canonical
    spelling, ``native``\u2192``default`` dedup) is done in code, not config.
``passthrough``
    Cache every path on a host verbatim
    (:class:`~fetcher_service.rules.HostPassthroughRule`).
    Fields: ``host``, ``mirror_id``.
``regex``
    Generic host with an anchored, named-group regex that **matches and extracts
    only** (:class:`~fetcher_service.rules.RegexRule`).
    Fields: ``host``, ``mirror_id``, ``path_match``, ``alias_template``.

The ``regex`` type is deliberately a **safe subset**: patterns must use named
groups, and backreferences and lookaround are rejected at load time so a rule
set cannot smuggle in catastrophic-backtracking constructs. Every template
placeholder must correspond to a capture group in its pattern. Loading is fully
offline and deterministic, so a rule set can be exhaustively unit-tested.

Example::

    [[rule]]
    type = "iiif"
    host = "gallica.bnf.fr"
    mirror_id = "gallica"

    [[rule]]
    type = "regex"
    host = "images.example.org"
    mirror_id = "example"
    path_match = '^img/(?P<id>[^/]+)\\.(?P<fmt>jpg|png)$'
    alias_template = "img/{id}.{fmt}"
"""

from __future__ import annotations

import os
import re
import string
import tomllib
from pathlib import Path
from typing import Any

from fetcher_service.rules import (
    CacheRule,
    HostPassthroughRule,
    IIIFImageRule,
    RegexRule,
    RuleSet,
)

#: Environment variable naming the TOML rule-set file.
RULES_FILE_ENV = "FETCHER_RULES_FILE"

# Regex constructs banned from `regex` rules: backreferences (\1, \g<name>) and
# lookaround (?=, ?!, ?<=, ?<!). Named groups (?P<name>) remain allowed.
_UNSAFE_REGEX = re.compile(r"\\[1-9]|\\g<|\(\?<?[=!]")


class RuleConfigError(ValueError):
    """Raised when a rule-set configuration is invalid."""


def _require_str(rule: dict[str, Any], key: str, *, index: int) -> str:
    value = rule.get(key)
    if not isinstance(value, str) or not value:
        raise RuleConfigError(f"rule[{index}]: '{key}' must be a non-empty string")
    return value


def _template_fields(template: str) -> set[str]:
    try:
        parsed = string.Formatter().parse(template)
        return {field for _, field, _, _ in parsed if field}
    except ValueError as exc:  # pragma: no cover - malformed brace syntax
        raise RuleConfigError(f"invalid alias_template {template!r}: {exc}") from exc


def _build_regex_rule(rule: dict[str, Any], *, index: int) -> RegexRule:
    host = _require_str(rule, "host", index=index)
    mirror_id = _require_str(rule, "mirror_id", index=index)
    path_match = _require_str(rule, "path_match", index=index)
    alias_template = _require_str(rule, "alias_template", index=index)

    if _UNSAFE_REGEX.search(path_match):
        raise RuleConfigError(
            f"rule[{index}]: 'path_match' uses a disallowed construct "
            "(backreference or lookaround); the regex subset is match/extract only"
        )
    try:
        pattern = re.compile(path_match)
    except re.error as exc:
        raise RuleConfigError(f"rule[{index}]: invalid 'path_match' regex: {exc}") from exc

    groups = set(pattern.groupindex)
    missing = _template_fields(alias_template) - groups
    if missing:
        raise RuleConfigError(
            f"rule[{index}]: alias_template references unknown group(s) "
            f"{sorted(missing)}; defined groups are {sorted(groups)}"
        )
    return RegexRule(
        host=host,
        mirror_id=mirror_id,
        pattern=pattern,
        alias_template=alias_template,
    )


def _build_rule(rule: dict[str, Any], *, index: int) -> CacheRule:
    rule_type = rule.get("type")
    if not isinstance(rule_type, str):
        raise RuleConfigError(f"rule[{index}]: missing 'type'")

    if rule_type == "iiif":
        host = _require_str(rule, "host", index=index)
        mirror_id = _require_str(rule, "mirror_id", index=index)
        path_prefix = rule.get("path_prefix", ["iiif"])
        if not isinstance(path_prefix, list) or not all(
            isinstance(segment, str) for segment in path_prefix
        ):
            raise RuleConfigError(f"rule[{index}]: 'path_prefix' must be a list of strings")
        return IIIFImageRule(
            host=host,
            mirror_id=mirror_id,
            path_prefix=tuple(path_prefix),
        )
    if rule_type == "passthrough":
        return HostPassthroughRule(
            host=_require_str(rule, "host", index=index),
            mirror_id=_require_str(rule, "mirror_id", index=index),
        )
    if rule_type == "regex":
        return _build_regex_rule(rule, index=index)
    raise RuleConfigError(
        f"rule[{index}]: unknown type {rule_type!r} (expected 'iiif', 'passthrough', or 'regex')"
    )


def load_rule_set(text: str) -> RuleSet:
    """Compile a TOML rule-set document into a :class:`RuleSet`."""

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuleConfigError(f"invalid TOML: {exc}") from exc

    raw_rules = document.get("rule", [])
    if not isinstance(raw_rules, list):
        raise RuleConfigError("'rule' must be an array of tables ([[rule]])")

    rules: list[CacheRule] = []
    for index, rule in enumerate(raw_rules):
        if not isinstance(rule, dict):
            raise RuleConfigError(f"rule[{index}]: must be a table")
        rules.append(_build_rule(rule, index=index))
    return RuleSet(rules=tuple(rules))


def load_rule_set_file(path: str | os.PathLike[str]) -> RuleSet:
    """Load and compile a rule-set from a TOML file."""

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleConfigError(f"cannot read rule-set file {path!s}: {exc}") from exc
    return load_rule_set(text)


def rule_set_from_env() -> RuleSet | None:
    """Load the rule-set named by ``FETCHER_RULES_FILE``, or ``None`` if unset."""

    path = os.environ.get(RULES_FILE_ENV)
    if not path:
        return None
    return load_rule_set_file(path)
