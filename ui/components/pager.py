"""A cursor belongs to exactly one immutable queue version and filter set."""

from dataclasses import dataclass, field
from typing import Any

import streamlit as st


@dataclass
class CursorPager:
    version: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    cursor: dict[str, Any] = field(default_factory=dict)
    previous: list[dict[str, Any]] = field(default_factory=list)

    def bind(self, version: str, filters: dict[str, Any]) -> None:
        if (version, filters) != (self.version, self.filters):
            self.version, self.filters = version, dict(filters)
            self.cursor, self.previous = {}, []

    def advance(self, cursor: dict[str, Any] | None) -> None:
        if cursor and self.version:
            self.previous.append(dict(self.cursor))
            self.cursor = dict(cursor)

    def back(self) -> None:
        if self.previous:
            self.cursor = self.previous.pop()


def render_pager(pager: CursorPager, next_cursor: dict[str, Any] | None, *, key: str) -> None:
    back, forward = st.columns(2)
    if back.button("Previous page", disabled=not pager.previous, key=key + "_previous"):
        pager.back()
        st.rerun()
    if forward.button("Next page", disabled=not next_cursor, key=key + "_next"):
        pager.advance(next_cursor)
        st.rerun()
