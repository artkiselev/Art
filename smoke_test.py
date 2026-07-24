from __future__ import annotations

import tempfile
from pathlib import Path

from documents import create_ceremony_prompt_txt, create_ceremony_script_txt, create_questionnaire_docx
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
        storage.save(session)

        loaded = storage.get_or_create(123, version=QUESTIONNAIRE_VERSION)
        assert loaded.completed
        assert loaded.version == QUESTIONNAIRE_VERSION
        assert len(loaded.answers) == question_count()

        output_dir = root / "outputs"
        docx_path = create_questionnaire_docx(loaded.answers, output_dir, loaded.chat_id)
        prompt_path = create_ceremony_prompt_txt(loaded.answers, output_dir, loaded.chat_id)
        script_path = create_ceremony_script_txt(
            "Полный текст свадебной церемонии для ведущего.",
            loaded.answers,
            output_dir,
            loaded.chat_id,
        )
        assert docx_path.exists()
        assert prompt_path.exists()
        assert script_path.exists()
        assert "Составь полный текст свадебной церемонии" in prompt_path.read_text(encoding="utf-8")
        assert "Полный текст свадебной церемонии" in script_path.read_text(encoding="utf-8")
        assert "Ответы анкеты" in build_generation_prompt(loaded.answers)
    print("Smoke test passed")


if __name__ == "__main__":
    main()
