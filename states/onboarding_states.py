from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_brand_name = State()
    waiting_for_brand_description = State()
    waiting_for_usage_goal = State()
    waiting_for_target_audience = State()
    waiting_for_tone = State()
    waiting_for_post_length = State()
