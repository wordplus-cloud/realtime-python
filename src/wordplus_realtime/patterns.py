"""The names an app's rules own, by pattern: ``order:{id}``,
``chat:{a}:{b}``, ``meeting:{id}``, a plain name for itself. A ``{part}`` takes one or more characters other than ``:``
and ``.``, as few as the rest of the pattern allows, exactly as the realtime server matches a public grant's patterns.
The rule with the most characters of its own wins; on a tie, the one declared first. @wordplus/realtime's patterns.ts,
line for line.

``{pair}``, in a room's or a call's pattern, is the two people the name holds: ``support:{pair}`` matches
``support:34:42``, with ``{"pair": "34:42"}``, and only those two get in, which room() and calls() check before any rule
of the app's."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# \Z, not $: Python's $ also matches before a newline at the end, and `order:42\n` is no room.
_ROOM = re.compile(r"^[A-Za-z0-9_\-=@,.;:]{1,200}\Z")
_PATTERN = re.compile(r"^(?:[A-Za-z0-9_\-=@,.;:]|\{[A-Za-z_][A-Za-z0-9_]{0,31}\}){1,200}\Z")
_PART = re.compile(r"(\{[^}]+\})")


def has_pair(pattern: str) -> bool:
    """Whether a pattern names the two people in it."""
    return "{pair}" in pattern


def other_of(pair: str, user: Any) -> Optional[str]:
    """The other of the two in a ``{pair}`` for a user who is one of them, or None for anyone else, and for one person
    twice."""
    a, b = pair.split(":", 1)
    if user is None or a == b:
        return None
    id_ = str(user)
    return b if id_ == a else a if id_ == b else None


def valid_room(name: Any) -> bool:
    """A room's name, a call's or a group call's: 1 to 200 of A-Z a-z 0-9 _ - = @ , . ; and ``:``."""
    return isinstance(name, str) and _ROOM.match(name) is not None


def valid_pattern(pattern: Any) -> bool:
    """A pattern: a name with ``{part}``s, each named by a letter or ``_`` then up to 31 letters, digits and ``_``."""
    return isinstance(pattern, str) and _PATTERN.match(pattern) is not None


class Patterns:
    def __init__(self) -> None:
        self._list: List[Dict[str, Any]] = []

    def add(self, pattern: str, value: Any) -> None:
        """Adds a pattern and what it owns; one already there is replaced."""
        if not valid_pattern(pattern):
            raise ValueError("wordplus-realtime: not a pattern: %r (letters, digits, _ - = @ , . ; : and {part}s)" % (pattern,))
        if pattern.count("{pair}") > 1:
            raise ValueError("wordplus-realtime: a name holds one pair: %r" % (pattern,))

        parts: List[str] = []
        source = ""
        for piece in _PART.split(pattern):
            if not piece:
                continue
            if piece.startswith("{"):
                parts.append(piece[1:-1])
                source += "([^:.]+?:[^:.]+?)" if piece == "{pair}" else "([^:.]+?)"
            else:
                source += re.escape(piece)

        existing = next((i for i, compiled in enumerate(self._list) if compiled["pattern"] == pattern), None)
        compiled = {
            "pattern": pattern,
            "re": re.compile("^" + source + r"\Z"),
            "parts": parts,
            # `{pair}` counts its `:`, so it weighs as `{a}:{b}` does.
            "literal": len(_PART.sub("", pattern.replace("{pair}", ":"))),
            "order": len(self._list) if existing is None else self._list[existing]["order"],
            "value": value,
        }
        if existing is None:
            self._list.append(compiled)
        else:
            self._list[existing] = compiled

    def match(self, name: str) -> Optional[Dict[str, Any]]:
        """What owns a name, ``{"pattern", "value", "params"}``, or None for none."""
        best: Optional[Dict[str, Any]] = None
        params: Dict[str, str] = {}
        for compiled in self._list:
            found = compiled["re"].match(name)
            if found is None:
                continue
            if best is not None and (compiled["literal"] < best["literal"] or (compiled["literal"] == best["literal"] and compiled["order"] > best["order"])):
                continue
            best = compiled
            params = {part: found.group(i + 1) for i, part in enumerate(compiled["parts"])}
        return None if best is None else {"pattern": best["pattern"], "value": best["value"], "params": params}

    def entries(self) -> List[Tuple[str, Any]]:
        return [(compiled["pattern"], compiled["value"]) for compiled in self._list]
