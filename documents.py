from __future__ import annotations

from datetime import datetime
from pathlib import Path
from textwrap import shorten

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from openai_service import build_generation_prompt
from questionnaire import QUESTIONS


def _safe_filename(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    normalized = "".join(ch if ch in allowed else "_" for ch in value)
    return normalized.strip("_") or "wedding_ceremony"


def _filename_hint(answers: dict[str, str], chat_id: int) -> str:
    names = answers.get("couple_names", "")
    return _safe_filename(shorten(names, width=40, placeholder="")) if names else f"chat_{chat_id}"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _set_default_font(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)


def create_questionnaire_docx(answers: dict[str, str], output_dir: Path, chat_id: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = Document()
    _set_default_font(document)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run("Анкета для свадебной церемонии")
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
        paragraph = document.add_paragraph()
        paragraph.add_run(question.prompt).bold = True
        document.add_paragraph(answers.get(question.key, "").strip() or "Не заполнено")

    output_path = output_dir / f"{_filename_hint(answers, chat_id)}_questionnaire_{_timestamp()}.docx"
    document.save(output_path)
    return output_path


def create_ceremony_prompt_txt(answers: dict[str, str], output_dir: Path, chat_id: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_filename_hint(answers, chat_id)}_ceremony_prompt_{_timestamp()}.txt"
    output_path.write_text(build_generation_prompt(answers), encoding="utf-8")
    return output_path


def create_ceremony_script_txt(script_text: str, answers: dict[str, str], output_dir: Path, chat_id: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_filename_hint(answers, chat_id)}_ceremony_script_{_timestamp()}.txt"
    output_path.write_text(script_text.strip() + "\n", encoding="utf-8")
    return output_path
