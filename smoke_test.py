from __future__ import annotations

import tempfile
from pathlib import Path

from documents import create_ceremony_script_docx, create_ceremony_script_html, create_questionnaire_docx
from openai_service import build_generation_prompt
from questionnaire import QUESTIONNAIRE_VERSION, QUESTIONS, question_count
from storage import Storage


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = Storage(root / "test.sqlite3")
        session = storage.get_or_create(123, version=QUESTIONNAIRE_VERSION)
        for index, question in enumerate(QUESTIONS):
            session.answers[question.key] = f"Тестовый ответ {index + 1}"
        session.current_index = question_count()
        session.completed = True
        session.status = "review"
        storage.save(session)

        loaded = storage.get_or_create(123, version=QUESTIONNAIRE_VERSION)
        assert loaded.completed
        assert loaded.status == "review"
        assert loaded.version == QUESTIONNAIRE_VERSION
        assert len(loaded.answers) == question_count()

        output_dir = root / "outputs"
        docx_path = create_questionnaire_docx(loaded.answers, output_dir, loaded.chat_id)
        script_html_path = create_ceremony_script_html(
            "Полный текст свадебной церемонии для ведущего.",
            loaded.answers,
            output_dir,
            loaded.chat_id,
        )
        script_docx_path = create_ceremony_script_docx(
            "Полный текст свадебной церемонии для ведущего.",
            loaded.answers,
            output_dir,
            loaded.chat_id,
        )
        assert docx_path.exists()
        assert script_html_path.exists()
        assert script_docx_path.exists()
        assert "Полный текст свадебной церемонии" in script_html_path.read_text(encoding="utf-8")
        assert "Ответы анкеты" in build_generation_prompt(loaded.answers)
    print("Smoke test passed")


if __name__ == "__main__":
    main()
