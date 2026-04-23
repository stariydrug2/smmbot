from __future__ import annotations

from utils.helpers import escape_html, format_dt_human, truncate


def format_profile(
    profile: dict | None,
    user: dict | None,
    summary: str,
    generation_count: int,
    subscription_status: dict | None,
    last_payments: list[dict] | None = None,
) -> str:
    if not profile or not user:
        return '<b>Личный кабинет</b>\n\nПрофиль пока не найден.'

    status = subscription_status or {}

    payment_lines = []
    for payment in (last_payments or [])[:3]:
        payment_lines.append(
            f"• {escape_html(payment.get('plan_title') or payment.get('plan_code') or 'Платёж')} — "
            f"{payment.get('amount')} ₽ — {escape_html(_payment_status_label(payment.get('status')))}"
        )
    last_payments_block = '\n'.join(payment_lines) if payment_lines else '—'

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
        f"<b>Регистрация:</b> {escape_html(format_dt_human(user.get('created_at')))}",
        '',
        '<b>Подписка</b>',
        f"<b>Статус:</b> {escape_html(_subscription_status_label(str(status.get('status') or 'trial')))}",
        f"<b>Тариф:</b> {escape_html(str(status.get('plan_title') or '—'))}",
        f"<b>Действует до:</b> {escape_html(str(status.get('ends_at_human') or '—'))}",
        f"<b>Осталось часов:</b> {escape_html(str(status.get('hours_left') if status.get('hours_left') is not None else '—'))}",
        '',
        '<b>Последние оплаты</b>',
        last_payments_block,
        '',
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
        lines.append(
            f"<b>#{item['id']}</b> · {escape_html(item['generation_type'])} · "
            f"{escape_html(format_dt_human(item.get('created_at')))}"
        )
    return '\n'.join(lines)


def format_payment_history(payments: list[dict]) -> str:
    if not payments:
        return '<b>История оплат</b>\n\nПока нет ни одной платежной записи.'

    lines = ['<b>История оплат</b>', '']
    for payment in payments:
        lines.append(
            f"<b>#{payment['id']}</b> · "
            f"{escape_html(payment.get('plan_title') or payment.get('plan_code') or 'Платёж')} · "
            f"{payment.get('amount')} ₽ · "
            f"{escape_html(_payment_status_label(payment.get('status')))} · "
            f"{escape_html(format_dt_human(payment.get('created_at')))}"
        )
    return '\n'.join(lines)


def format_payment_details(payment: dict) -> str:
    lines = [
        f"<b>Платёж #{payment['id']}</b>",
        '',
        f"<b>Тариф:</b> {escape_html(payment.get('plan_title') or payment.get('plan_code') or '—')}",
        f"<b>Сумма:</b> {payment.get('amount')} ₽",
        f"<b>Статус:</b> {escape_html(_payment_status_label(payment.get('status')))}",
        f"<b>Создан:</b> {escape_html(format_dt_human(payment.get('created_at')))}",
        f"<b>Оплачен:</b> {escape_html(format_dt_human(payment.get('paid_at')))}",
    ]
    if payment.get('invoice_url'):
        lines.append(f"<b>Ссылка:</b> {escape_html(payment['invoice_url'])}")
    return '\n'.join(lines)


def _subscription_status_label(value: str) -> str:
    return {
        'trial': 'Триал',
        'active': 'Активна',
        'expired': 'Истекла',
        'cancelled': 'Отменена',
    }.get(value, value)


def _payment_status_label(value: str | None) -> str:
    return {
        'created': 'Создан',
        'pending': 'Ожидает оплаты',
        'paid': 'Оплачен',
        'failed': 'Ошибка',
        'expired': 'Истёк',
        'cancelled': 'Отменён',
    }.get(value or '', value or '—')
