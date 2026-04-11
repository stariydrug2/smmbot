from aiogram.fsm.state import State, StatesGroup


class ProfileStates(StatesGroup):
    choosing_field = State()
    editing_person_name = State()
    editing_brand_name = State()
    editing_brand_description = State()
    editing_usage_goal = State()
    editing_target_audience = State()
    editing_tone = State()
    editing_post_length = State()
    editing_preferred_formats = State()
    editing_forbidden_words = State()
    editing_examples = State()
