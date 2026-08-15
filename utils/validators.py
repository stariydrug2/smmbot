from __future__ import annotations


def is_meaningful_text(text: str | None, min_length: int = 2) -> bool:
    return bool(text and len(text.strip()) >= min_length)


def normalize_bool_text(text: str) -> bool | None:
    lowered = text.strip().lower()
    if lowered in {'да', 'yes', '+'}:
        return True
    if lowered in {'нет', 'no', '-'}:
        return False
    return None
