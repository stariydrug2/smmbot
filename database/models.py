from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class User:
    id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    full_name: Optional[str]
    is_subscribed: int
    is_onboarding_completed: int
    is_admin: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class BrandProfile:
    id: int
    user_id: int
    person_name: Optional[str]
    brand_name: Optional[str]
    brand_description: Optional[str]
    usage_goal: Optional[str]
    target_audience: Optional[str]
    tone_of_voice: Optional[str]
    post_length: Optional[str]
    preferred_formats: Optional[str]
    forbidden_words: Optional[str]
    wants_images: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class GenerationRecord:
    id: int
    user_id: int
    generation_type: str
    source_type: str
    input_text: str
    output_text: str
    metadata_json: str
    created_at: str
