from aiogram.fsm.state import State, StatesGroup


class ChannelProfileStates(StatesGroup):
    project = State()
    audience = State()
    voice = State()
    topics = State()
    goals = State()
    examples = State()


class CreateStates(StatesGroup):
    request = State()
    voice = State()
    improve_instruction = State()
    manual_edit = State()
    schedule_time = State()
    image_prompt = State()


class PlanStates(StatesGroup):
    brief = State()


class AnalysisStates(StatesGroup):
    collecting_posts = State()
    intercept_post = State()
    expert_post = State()
    competitor_source = State()
