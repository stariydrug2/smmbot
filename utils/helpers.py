from __future__ import annotations

import html
import re
from pathlib import Path

from aiogram.types import CallbackQuery, Message, TelegramObject


def escape_html(text: str | None) -> str:
    return html.escape(text or '')


def truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_subscription_related_event(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        return (event.text or '').strip().lower().startswith('/start')
    if isinstance(event, CallbackQuery):
        return event.data in {'check_subscription', 'go:menu'}
    return False


def render_model_text(text: str | None) -> str:
    """
    Преобразует ответ модели в безопасный HTML для Telegram.

    Что делает:
    - экранирует сырой HTML
    - сохраняет уже сгенерированные <b>/<strong>
    - переводит markdown-заголовки (#, ##, ###) в <b>
    - переводит **жирный** в <b>
    - аккуратно выделяет короткие лидирующие метки вида "Тема:" или "День 1:"
    """
    raw = (text or '').replace('\r\n', '\n').strip()
    if not raw:
        return ''

    placeholders = {
        '<b>': '[[B_OPEN]]',
        '</b>': '[[B_CLOSE]]',
        '<strong>': '[[B_OPEN]]',
        '</strong>': '[[B_CLOSE]]',
    }
    for src, dst in placeholders.items():
        raw = raw.replace(src, dst)

    lines: list[str] = []
    for source_line in raw.split('\n'):
        line = source_line.rstrip()
        if not line.strip():
            lines.append('')
            continue

        heading_match = re.match(r'^\s{0,3}#{1,6}\s+(.+?)\s*$', line)
        if heading_match:
            heading = _convert_inline_bold(heading_match.group(1).strip())
            lines.append(f'<b>{heading}</b>')
            continue

        converted = _convert_inline_bold(line)
        converted = _bold_leading_label(converted)
        lines.append(converted)

    result = '\n'.join(lines)
    result = result.replace('[[B_OPEN]]', '<b>').replace('[[B_CLOSE]]', '</b>')
    return result


def _convert_inline_bold(line: str) -> str:
    parts = re.split(r'(\*\*.+?\*\*)', line)
    converted_parts: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) >= 4:
            inner = html.escape(part[2:-2].strip())
            converted_parts.append(f'<b>{inner}</b>')
        else:
            converted_parts.append(html.escape(part))
    return ''.join(converted_parts)


def _bold_leading_label(line: str) -> str:
    match = re.match(r'^(\s*)([A-Za-zА-Яа-яЁё0-9][^\n:]{0,40}:)(\s*)(.*)$', line)
    if not match:
        return line
    prefix, label, spacer, rest = match.groups()
    if any(token in label for token in ('http', 'https', 't.me/', '/', '\\')):
        return line
    return f'{prefix}<b>{label}</b>{spacer}{rest}'
