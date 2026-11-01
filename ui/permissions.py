"""Navigation uses effective API permissions with their own scope grants."""

from typing import Any

PAGE_PERMISSIONS = {
    "Review queue": ("queue:read",),
    "Case evidence": ("case:read",),
    "History": ("case:read", "audit:read"),
    "Operations": ("batch:intake", "score:submit", "train:submit", "job:read"),
    "Exports": ("export:create",),
}


def can(identity: dict[str, Any], permission: str) -> bool:
    grants = identity.get("permission_scopes", {})
    scopes = set(identity.get("scopes", []))
    return permission in identity.get("permissions", []) and bool(
        scopes.intersection(grants.get(permission, []))
    )


def build_navigation(
    identity: dict[str, Any], extension_pages: tuple[str, ...] = (), *, mock_mode: bool = False
) -> list[str]:
    base = [
        page
        for page, permissions in PAGE_PERMISSIONS.items()
        if any(can(identity, p) for p in permissions)
    ]
    return base + [
        name
        for name in extension_pages
        if name
        in {"Models", "Retraining proposals", "Evidence reports", "Source health", "Pilot metrics"}
        and mock_mode
        and can(identity, "audit:read")
    ]


def navigation_groups(pages: list[str]) -> dict[str, list[str]]:
    groups = {
        "Investigation": [
            p for p in pages if p in {"Review queue", "Case evidence", "History", "Exports"}
        ],
        "Operations": [p for p in pages if p == "Operations"],
        "Preview · Synthetic only": [p for p in pages if p not in PAGE_PERMISSIONS],
    }
    return {name: items for name, items in groups.items() if items}
