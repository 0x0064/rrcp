from __future__ import annotations


def normalize_recipients(
    recipients: list[str] | None,
    *,
    author_id: str,
) -> list[str] | None:
    if not recipients:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for rid in recipients:
        if rid == author_id:
            continue
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out or None
