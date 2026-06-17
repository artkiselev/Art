from __future__ import annotations

from datetime import datetime
from pathlib import Path
from textwrap import shorten

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from questionnaire import QUESTIONS, QUESTION_BY_KEY


def _safe_filename(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    normalized = "".join(ch if ch in allowed else "_" for ch in value)
    return normalized.strip("_") or "wedding_questionnaire"


def _set_default_font(document: Document) -> None:
    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)


def create_questionnaire_docx(answers: dict[str, str], output_dir: Path, chat_id: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = Document()
    _set_default_font(document)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run("Свадебная анкета")
    title_run.bold = True
    title_run.font.size = Pt(20)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(f"Сформировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    current_section = None
    for question in QUESTIONS:
        if question.section != current_section:
            document.add_heading(question.section, level=1)
            current_section = question.section
        document.add_paragraph(question.prompt, style=None).runs[0].bold = True
        answer = answers.get(question.key, "").strip() or "Не заполнено"
        document.add_paragraph(answer)

    ceremony_prompt = build_ceremony_prompt(answers)
    document.add_page_break()
    document.add_heading("Промпт для подготовки церемонии через Codex", level=1)
    document.add_paragraph(ceremony_prompt)

    names = answers.get("couple_names", "")
    filename_hint = _safe_filename(shorten(names, width=40, placeholder="")) if names else f"chat_{chat_id}"
    output_path = output_dir / f"{filename_hint}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    document.save(output_path)
    return output_path


def create_ceremony_prompt_txt(answers: dict[str, str], output_dir: Path, chat_id: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    names = answers.get("couple_names", "")
    filename_hint = _safe_filename(shorten(names, width=40, placeholder="")) if names else f"chat_{chat_id}"
    output_path = output_dir / f"{filename_hint}_ceremony_prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    output_path.write_text(build_ceremony_prompt(answers), encoding="utf-8")
    return output_path


def build_ceremony_prompt(answers: dict[str, str]) -> str:
    lines = [
        "Составь теплый, современный и живой текст свадебной церемонии на русском языке.",
        "Тон: искренний, не слишком официальный, без пошлых шуток и без тем, которые пара запретила.",
        "",
        "Структура церемонии:",
        "1. Начало церемонии.",
        "2. Вступительная речь и плавный переход к приглашению жениха.",
        "3. Выход жениха и короткая история про него.",
        "4. Подводка к выходу невесты.",
        "5. Выход невесты.",
        "6. Информация про нее, про него и про их отношения.",
        "7. Подводка к клятвам.",
        "8. Подводка к объявлению мужем и женой.",
        "9. Подводка к выносу колец.",
        "10. Финал.",
        "",
        "Данные анкеты:",
    ]
    for key, value in answers.items():
        question = QUESTION_BY_KEY.get(key)
        label = question.prompt if question else key
        lines.append(f"\n{label}\n{value.strip() or 'Не заполнено'}")
    return "\n".join(lines)
