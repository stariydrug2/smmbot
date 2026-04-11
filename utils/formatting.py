from __future__ import annotations

from utils.helpers import escape_html, truncate


def format_profile(profile: dict | None, user: dict | None, summary: str, generation_count: int, subscription_status: dict | None) -> str:
    if not profile or not user:
        return '<b>Личный кабинет</b>\n\nПрофиль пока не найден.'
    lines = [
        '<b>Личный кабинет</b>',
        '',
        f"<b>Имя:</b> {escape_html(profile.get('person_name') or '—')}",
        f"<b>Бренд:</b> {escape_html(profile.get('brand_name') or '—')}",
        f"<b>Описание:</b> {escape_html(profile.get('brand_description') or '—')}",
        f"<b>Цель:</b> {escape_html(profile.get('usage_goal') or '—')}",
        f"<b>Аудитория:</b> {escape_html(profile.get('target_audience') or '—')}",
        f"<b>Tone of voice:</b> {escape_html(profile.get('tone_of_voice') or '—')}",
        f"<b>Длина постов:</b> {escape_html(profile.get('post_length') or '—')}",
        f"<b>Форматы:</b> {escape_html(profile.get('preferred_formats') or '—')}",
        f"<b>Запрещённые слова:</b> {escape_html(profile.get('forbidden_words') or '—')}",
        f"<b>Изображения:</b> {'Да' if profile.get('wants_images') else 'Нет'}",
        f"<b>Регистрация:</b> {escape_html(user.get('created_at') or '—')}",
        f"<b>Статус:</b> {escape_html(str(subscription_status or {}))}",
        f"<b>Генераций:</b> {generation_count}",
        '',
        f"<b>Краткая память бренда:</b>\n{escape_html(truncate(summary or 'Память пока не сформирована.', 600))}",
    ]
    return '\n'.join(lines)


def format_history(records: list[dict]) -> str:
    if not records:
        return '<b>История</b>\n\nПока нет ни одной генерации.'
    lines = ['<b>История генераций</b>', '']
    for item in records:
        lines.append(f"<b>#{item['id']}</b> · {escape_html(item['generation_type'])} · {escape_html(item['created_at'])}")
    return '\n'.join(lines)
