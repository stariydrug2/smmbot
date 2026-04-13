from aiogram.fsm.state import State, StatesGroup


class GenerationStates(StatesGroup):
    choosing_mode = State()
    waiting_for_topic = State()
    waiting_for_goal = State()
    waiting_for_style = State()
    waiting_for_length = State()
    waiting_for_options = State()
    waiting_for_rewrite_text = State()
    waiting_for_voice = State()
    waiting_for_photo = State()
    waiting_for_content_plan_brief = State()
    waiting_for_examples = State()
    waiting_for_visual_request = State()
