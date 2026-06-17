from __future__ import annotations

import tempfile
from pathlib import Path

from documents import create_ceremony_prompt_txt, create_questionnaire_docx
from questionnaire import QUESTIONS, question_count
from storage import Storage


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = Storage(root / "test.sqlite3")
        session = storage.get_or_create(123)
        for index, question in enumerate(QUESTIONS):
            session.answers[question.key] = f"Тестовый ответ {index + 1}"
        session.current_index = question_count()
        session.completed = True
        storage.save(session)

        loaded = storage.get_or_create(123)
        assert loaded.completed
        assert len(loaded.answers) == question_count()

        docx_path = create_questionnaire_docx(loaded.answers, root / "outputs", loaded.chat_id)
        prompt_path = create_ceremony_prompt_txt(loaded.answers, root / "outputs", loaded.chat_id)
        assert docx_path.exists()
        assert prompt_path.exists()
        assert "Составь теплый" in prompt_path.read_text(encoding="utf-8")
    print("Smoke test passed")


if __name__ == "__main__":
    main()
