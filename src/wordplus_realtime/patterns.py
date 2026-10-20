"""The names an app's rules own, by pattern: ``order:{id}``,
``chat:{a}:{b}``, ``meeting:{id}``, a plain name for itself. A ``{part}`` takes one or more characters other than ``:``
and ``.``, as few as the rest of the pattern allows, exactly as the realtime server matches a public grant's patterns.
The rule with the most characters of its own wins; on a tie, the one declared first. @wordplus/realtime's patterns.ts,
line for line."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_ROOM = re.compile(r"^[A-Za-z0-9_\-=@,.;:]{1,200}$")
_PATTERN = re.compile(r"^(?:[A-Za-z0-9_\-=@,.;:]|\{[A-Za-z_][A-Za-z0-9_]{0,31}\}){1,200}$")
_PART = re.compile(r"(\{[^}]+\})")


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

        parts: List[str] = []
        source = ""
        for piece in _PART.split(pattern):
            if not piece:
                continue
            if piece.startswith("{"):
                parts.append(piece[1:-1])
                source += "([^:.]+?)"
            else:
                source += re.escape(piece)

        existing = next((i for i, compiled in enumerate(self._list) if compiled["pattern"] == pattern), None)
        compiled = {
            "pattern": pattern,
            "re": re.compile("^" + source + "$"),
            "parts": parts,
            "literal": len(_PART.sub("", pattern)),
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
