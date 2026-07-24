from __future__ import annotations

from dataclasses import dataclass


QUESTIONNAIRE_VERSION = 2


@dataclass(frozen=True)
class Question:
    key: str
    section: str
    prompt: str


QUESTIONS: tuple[Question, ...] = (
    Question(
        "couple_names",
        "Пара",
        "Как зовут жениха и невесту? Напишите полные имена и как лучше называть вас на церемонии.",
    ),
    Question(
        "meeting_story",
        "История",
        "Как вы познакомились? Где это было, что запомнилось, с чего все началось?",
    ),
    Question(
        "relationship_turning_points",
        "История",
        "Какие важные моменты были в отношениях: первое свидание, переезд, поездки, сложные или смешные истории?",
    ),
    Question(
        "proposal_story",
        "Предложение",
        "Как было сделано предложение? Где, когда, что было самым трогательным или неожиданным?",
    ),
    Question(
        "groom_details",
        "Герои церемонии",
        "Расскажите 2-3 личные детали про жениха: характер, привычки, сильные стороны, за что его любят.",
    ),
    Question(
        "bride_details",
        "Герои церемонии",
        "Расскажите 2-3 личные детали про невесту: характер, привычки, сильные стороны, за что ее любят.",
    ),
    Question(
        "mutual_values",
        "Герои церемонии",
        "Что вы цените друг в друге? Почему именно с этим человеком хочется строить семью?",
    ),
    Question(
        "vows",
        "Церемония",
        "Будут ли личные клятвы? Если да, кто будет читать: жених, невеста или оба?",
    ),
    Question(
        "rings",
        "Церемония",
        "Кто выносит кольца? Есть ли важные участники церемонии, которых нужно упомянуть?",
    ),
    Question(
        "tone_and_limits",
        "Церемония",
        "Каким должен быть тон церемонии и каких тем нельзя касаться?",
    ),
)


QUESTION_BY_KEY = {question.key: question for question in QUESTIONS}


def question_count() -> int:
    return len(QUESTIONS)


def get_question(index: int) -> Question | None:
    if 0 <= index < len(QUESTIONS):
        return QUESTIONS[index]
    return None


def format_question(index: int) -> str:
    question = QUESTIONS[index]
    return (
        f"Вопрос {index + 1} из {len(QUESTIONS)}\n"
        f"Раздел: {question.section}\n\n"
        f"{question.prompt}\n\n"
        "Ответьте текстом или голосовым сообщением. Бот сохранит ответ и перейдет к следующему вопросу."
    )


def remaining_count(current_index: int) -> int:
    return max(0, len(QUESTIONS) - current_index)
