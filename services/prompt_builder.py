from __future__ import annotations

from typing import Any

from services.prompt_templates import SYSTEM_PROMPT_RU


def _format_profile(profile: dict[str, Any] | None) -> str:
    if not profile:
        return 'Профиль бренда пока не заполнен.'
    parts = [
        f"Имя: {profile.get('person_name') or '-'}",
        f"Бренд: {profile.get('brand_name') or '-'}",
        f"Описание: {profile.get('brand_description') or '-'}",
        f"Цель использования: {profile.get('usage_goal') or '-'}",
        f"ЦА: {profile.get('target_audience') or '-'}",
        f"Tone of voice: {profile.get('tone_of_voice') or '-'}",
        f"Длина постов: {profile.get('post_length') or '-'}",
        f"Предпочтительные форматы: {profile.get('preferred_formats') or '-'}",
        f"Запрещённые слова/приёмы: {profile.get('forbidden_words') or '-'}",
        f"Нужны изображения: {'да' if profile.get('wants_images') else 'нет'}",
    ]
    return '\n'.join(parts)


def _format_examples(examples: list[str]) -> str:
    if not examples:
        return 'Примеры постов не сохранены.'
    return '\n\n'.join([f'Пример {idx}:\n{text}' for idx, text in enumerate(examples[:5], start=1)])


def _compose_context(profile: dict[str, Any] | None, memory_summary: str, examples: list[str]) -> str:
    return (
        f"{SYSTEM_PROMPT_RU}\n\n"
        f"ПРОФИЛЬ БРЕНДА:\n{_format_profile(profile)}\n\n"
        f"КРАТКАЯ ПАМЯТЬ БРЕНДА:\n{memory_summary or 'Память пока не сформирована.'}\n\n"
        f"ПРИМЕРЫ ПОСТОВ:\n{_format_examples(examples)}"
    )


def _options_block(**kwargs: Any) -> str:
    clean = {k: v for k, v in kwargs.items() if v not in (None, '', [], False)}
    return '\n'.join([f'- {k}: {v}' for k, v in clean.items()]) if clean else ''


def build_content_plan_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return (
        f"{_compose_context(profile, memory_summary, examples)}\n\n"
        f"ЗАДАЧА: собери контент-план на 7 дней для Telegram.\n"
        f"Запрос пользователя: {user_request}\n"
        f"Дополнительные параметры:\n{_options_block(**kwargs)}\n\n"
        "Формат ответа:\nДень 1\nТема:\nФормат:\nЦель:\nКраткая идея:\nCTA (если уместно):"
    )


def build_post_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return (
        f"{_compose_context(profile, memory_summary, examples)}\n\n"
        f"ЗАДАЧА: напиши готовый Telegram-пост.\nМатериал пользователя: {user_request}\n"
        f"Параметры:\n{_options_block(**kwargs)}\n\n"
        "Сделай текст пригодным к публикации сразу, с хорошей структурой и естественным русским языком."
    )


def build_series_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return (
        f"{_compose_context(profile, memory_summary, examples)}\n\n"
        f"ЗАДАЧА: создай серию Telegram-постов по одной теме.\nОснова: {user_request}\n"
        f"Параметры:\n{_options_block(**kwargs)}\n\n"
        "Оформи как 3-5 последовательных публикаций с логикой и разным углом подачи."
    )


def build_rewrite_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return f"{_compose_context(profile, memory_summary, examples)}\n\nЗАДАЧА: перепиши текст в нужный стиль для Telegram.\nИсходный текст: {user_request}\nПараметры:\n{_options_block(**kwargs)}"


def build_cta_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return f"{_compose_context(profile, memory_summary, examples)}\n\nЗАДАЧА: подготовь сильные CTA для Telegram-поста.\nКонтекст: {user_request}\nПараметры:\n{_options_block(**kwargs)}\n\nДай 5 вариантов, отличающихся по тону и силе призыва."


def build_story_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return f"{_compose_context(profile, memory_summary, examples)}\n\nЗАДАЧА: создай короткий story-анонс или подводку к посту.\nКонтекст: {user_request}\nПараметры:\n{_options_block(**kwargs)}"


def build_visual_idea_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return f"{_compose_context(profile, memory_summary, examples)}\n\nЗАДАЧА: предложи идею визуала для Telegram-поста.\nКонтекст: {user_request}\nПараметры:\n{_options_block(**kwargs)}\n\nДай 3 идеи визуала и короткий промпт для каждой."


def build_image_prompt(profile: dict[str, Any] | None, memory_summary: str, examples: list[str], user_request: str, **kwargs: Any) -> str:
    return f"{_compose_context(profile, memory_summary, examples)}\n\nЗАДАЧА: подготовь точный промпт для генерации изображения.\nКонтекст: {user_request}\nПараметры:\n{_options_block(**kwargs)}\n\nСначала коротко опиши концепцию, затем выдай финальный промпт одной цельной строкой."
