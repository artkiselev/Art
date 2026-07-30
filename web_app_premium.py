from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from html import escape
from pathlib import Path

from fastapi import Cookie, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from config import ROOT_DIR, get_settings
from documents import create_ceremony_script_docx, create_ceremony_script_html, create_questionnaire_docx
from openai_service import generate_ceremony_script, transcribe_audio
from questionnaire import QUESTIONS, format_answers_review, question_count
from telegram_sender import send_documents_to_telegram
from web_storage import WebSession, WebStorage


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

settings = get_settings()
storage = WebStorage(settings.database_path)
app = FastAPI()

ACCESS_CODES_PATH = ROOT_DIR / "data" / "access_codes.txt"
WEB_VOICE_DIR = ROOT_DIR / "data" / "web_voice"


@app.on_event("startup")
async def startup() -> None:
    if ACCESS_CODES_PATH.exists():
        codes = ACCESS_CODES_PATH.read_text(encoding="utf-8").splitlines()
        inserted = storage.import_codes(codes)
        logger.info("Imported %s new web access codes", inserted)
    else:
        logger.warning("Access codes file is missing: %s", ACCESS_CODES_PATH)


@app.get("/", response_class=HTMLResponse)
async def index(web_session: str | None = Cookie(default=None)) -> HTMLResponse:
    session = storage.get_session(web_session) if web_session else None
    if not session:
        return page("Вход", login_view())
    return questionnaire_page(session)


@app.post("/login")
async def login(response: Response, code: str = Form(...)) -> RedirectResponse:
    session_id = secrets.token_urlsafe(32)
    session = storage.get_or_create_session(code, session_id)
    if not session:
        return page_redirect("/", "Код не найден. Проверьте код доступа и попробуйте еще раз.")
    redirect = RedirectResponse("/", status_code=303)
    redirect.set_cookie("web_session", session.session_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return redirect


@app.post("/answer")
async def answer(
    web_session: str | None = Cookie(default=None),
    answer_text: str = Form(...),
) -> RedirectResponse:
    session = require_session(web_session)
    if session.status == "confirmed":
        return RedirectResponse("/", status_code=303)
    if session.status == "review":
        return RedirectResponse("/review", status_code=303)
    if session.current_index < 0 or session.current_index >= question_count():
        session.status = "review"
        storage.save_session(session)
        return RedirectResponse("/review", status_code=303)

    question = QUESTIONS[session.current_index]
    session.answers[question.key] = answer_text.strip()

    if session.status == "editing":
        session.status = "review"
        storage.save_session(session)
        return RedirectResponse("/review", status_code=303)

    session.current_index += 1
    if session.current_index >= question_count():
        session.status = "review"
        storage.save_session(session)
        return RedirectResponse("/review", status_code=303)

    session.status = "collecting"
    storage.save_session(session)
    return RedirectResponse("/", status_code=303)


@app.get("/review", response_class=HTMLResponse)
async def review(web_session: str | None = Cookie(default=None)) -> HTMLResponse:
    session = require_session(web_session)
    return review_page(session)


@app.post("/edit")
async def edit(web_session: str | None = Cookie(default=None), question_number: int = Form(...)) -> RedirectResponse:
    session = require_session(web_session)
    if session.status == "confirmed":
        return RedirectResponse("/", status_code=303)
    if question_number < 1 or question_number > question_count():
        return RedirectResponse("/review", status_code=303)
    session.current_index = question_number - 1
    session.status = "editing"
    storage.save_session(session)
    return RedirectResponse("/", status_code=303)


@app.post("/confirm", response_class=HTMLResponse)
async def confirm(web_session: str | None = Cookie(default=None)) -> HTMLResponse:
    session = require_session(web_session)
    if session.status == "confirmed":
        return questionnaire_page(session)
    if session.status != "review":
        return questionnaire_page(session)

    try:
        await asyncio.to_thread(export_session, session)
    except Exception:
        logger.exception("Web export failed for session_id=%s", session.session_id)
        return page("Не получилось", failure_view())

    session.status = "confirmed"
    storage.save_session(session)
    return questionnaire_page(session)


@app.post("/reset")
async def reset(web_session: str | None = Cookie(default=None)) -> RedirectResponse:
    session = require_session(web_session)
    new_session_id = secrets.token_urlsafe(32)
    new_session = storage.reset_session(session, new_session_id)
    redirect = RedirectResponse("/", status_code=303)
    redirect.set_cookie("web_session", new_session.session_id, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return redirect


@app.post("/transcribe")
async def transcribe(web_session: str | None = Cookie(default=None), audio: UploadFile = File(...)) -> dict[str, str]:
    require_session(web_session)
    if not settings.openai_api_key:
        return {"text": "", "error": "voice_unavailable"}

    WEB_VOICE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.filename or "voice.webm").suffix or ".webm"
    audio_path = WEB_VOICE_DIR / f"{secrets.token_hex(16)}{suffix}"
    audio_path.write_bytes(await audio.read())
    try:
        text = await asyncio.to_thread(
            transcribe_audio,
            settings.openai_api_key,
            settings.openai_transcribe_model,
            audio_path,
        )
    except Exception:
        logger.exception("Web voice transcription failed")
        return {"text": "", "error": "transcription_failed"}
    return {"text": text}


def require_session(session_id: str | None) -> WebSession:
    session = storage.get_session(session_id) if session_id else None
    if not session:
        raise RuntimeError("Session is missing")
    return session


def export_session(session: WebSession) -> None:
    script_text = generate_ceremony_script(settings.openai_api_key, settings.openai_text_model, session.answers)
    source_id = web_source_id(session.session_id)
    docx_path = create_questionnaire_docx(session.answers, settings.output_dir, source_id)
    script_html_path = create_ceremony_script_html(script_text, session.answers, settings.output_dir, source_id)
    script_docx_path = create_ceremony_script_docx(script_text, session.answers, settings.output_dir, source_id)
    send_documents_to_telegram(
        settings.telegram_bot_token,
        settings.export_chat_id,
        [
            (docx_path, f"Анкета с сайта. Код: {session.access_code}"),
            (script_html_path, "Текст для церемонии - HTML"),
            (script_docx_path, "Текст для церемонии - DOCX для печати"),
        ],
    )


def web_source_id(session_id: str) -> int:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return int(digest[:10], 16)


def questionnaire_page(session: WebSession) -> HTMLResponse:
    if session.status == "confirmed":
        return page("Готово", success_view())
    if session.status == "review":
        return review_page(session)
    if session.current_index >= question_count():
        session.status = "review"
        storage.save_session(session)
        return review_page(session)

    question = QUESTIONS[session.current_index]
    answered_count = len([question for question in QUESTIONS if session.answers.get(question.key, "").strip()])
    progress = int((answered_count / question_count()) * 100)
    current_number = session.current_index + 1
    eyebrow = "Редактура ответа" if session.status == "editing" else f"Вопрос {current_number} из {question_count()}"
    primary_label = "Обновить финальную анкету" if session.status == "editing" else "Сохранить и продолжить"
    body = f"""
    <section class="app-shell">
      <header class="app-header">
        <div>
          <div class="brand-lock">Dream Wedding Studio</div>
          <div class="header-subtitle">Автономный агент свадебной церемонии</div>
        </div>
        <form method="post" action="/reset"><button class="ghost-button" type="submit">Новая анкета</button></form>
      </header>
      <main class="studio-grid">
        <aside class="studio-rail">
          <div class="rail-card progress-card">
            <div class="rail-label">Прогресс анкеты</div>
            <div class="progress-number">{progress}%</div>
            <div class="progress-track"><i style="width:{progress}%"></i></div>
          </div>
          <div class="rail-card">
            <div class="rail-label">Сценарий</div>
            <ol class="flow-list">
              <li class="active">Ответы пары</li>
              <li>Проверка анкеты</li>
              <li>Текст церемонии</li>
              <li>Передача ведущему</li>
            </ol>
          </div>
          <div class="rail-note">Можно писать свободно: живые детали важнее идеальных формулировок.</div>
        </aside>
        <section class="question-panel">
          <div class="kicker">{escape(eyebrow)} · {escape(question.section)}</div>
          <h1>{escape(question.prompt)}</h1>
          <p class="question-copy">Ответ можно записать текстом или голосом. Перед отправкой ведущему вы увидите всю анкету и сможете спокойно исправить любой пункт.</p>
          <form class="answer-form" method="post" action="/answer">
            <textarea id="answerText" name="answer_text" rows="9" required placeholder="Напишите ответ здесь. Можно подробно, живым языком.">{escape(session.answers.get(question.key, ""))}</textarea>
            <div class="actions">
              <button class="primary-button" type="submit">{primary_label}</button>
              <button class="secondary-button" id="recordButton" type="button"><span class="button-icon">●</span>Голосовой ответ</button>
            </div>
            <div class="voice-status" id="voiceStatus"></div>
          </form>
        </section>
      </main>
    </section>
    {voice_script()}
    """
    return page("Анкета", body)


def review_page(session: WebSession) -> HTMLResponse:
    answers = []
    for index, question in enumerate(QUESTIONS, start=1):
        value = session.answers.get(question.key, "").strip() or "Не заполнено"
        answers.append(
            f"""
            <article class="answer-card">
              <div class="answer-number">{index}</div>
              <div>
                <div class="answer-section">{escape(question.section)}</div>
                <h2>{escape(question.prompt)}</h2>
                <p>{escape(value)}</p>
              </div>
              <form method="post" action="/edit">
                <input type="hidden" name="question_number" value="{index}">
                <button class="edit-button" title="Изменить ответ" aria-label="Изменить ответ {index}" type="submit">✎</button>
              </form>
            </article>
            """
        )
    body = f"""
    <section class="app-shell">
      <header class="app-header">
        <div>
          <div class="brand-lock">Dream Wedding Studio</div>
          <div class="header-subtitle">Финальная вычитка перед передачей ведущему</div>
        </div>
        <form method="post" action="/reset"><button class="ghost-button" type="submit">Новая анкета</button></form>
      </header>
      <main class="review-layout">
        <section class="review-head">
          <div class="kicker">Финальная проверка</div>
          <h1>Проверьте историю так, как ее услышит ведущий.</h1>
          <p>Если хочется уточнить деталь, нажмите значок редактирования рядом с вопросом. Когда все звучит верно, подтвердите анкету.</p>
          <form method="post" action="/confirm">
            <button class="primary-button full-width" type="submit">Подтвердить и передать ведущему</button>
          </form>
          <div class="handoff-note">После подтверждения агент подготовит речь, HTML-версию и DOCX для печати.</div>
        </section>
        <section class="answers-list">
          {''.join(answers)}
        </section>
      </main>
    </section>
    """
    return page("Проверка", body)


def login_view(message: str = "") -> str:
    alert = f"<div class=\"alert\">{escape(message)}</div>" if message else ""
    return f"""
    <section class="entry-screen">
      <main class="entry-layout">
        <section class="entry-copy">
          <div class="brand-lock">Dream Wedding Studio</div>
          <h1>Церемония, которая звучит как ваша история.</h1>
          <p>Закрытая анкета для пары. Ответы превращаются в структуру церемонии, речь ведущего и документы для подготовки.</p>
          <div class="signature-line">
            <span>Лично</span>
            <span>Бережно</span>
            <span>Без шаблонности</span>
          </div>
        </section>
        <section class="access-panel">
          <div class="kicker">Закрытый доступ</div>
          <h2>Введите код приглашения</h2>
          <p>Код нужен, чтобы анкета была доступна только вашей паре и ведущему.</p>
        {alert}
        <form method="post" action="/login">
            <input name="code" autocomplete="one-time-code" placeholder="DW-XXXX-XXXX" required>
            <button class="primary-button full-width" type="submit">Открыть анкету</button>
        </form>
        </section>
      </main>
    </section>
    """


def success_view() -> str:
    return """
    <section class="entry-screen">
      <main class="completion-panel">
        <div class="brand-lock">Dream Wedding Studio</div>
        <div class="completion-mark">✓</div>
        <h1>Готово. Анкета принята.</h1>
        <p>Материалы уже переданы ведущему. Спасибо, что так подробно рассказали вашу историю. Теперь можно выдохнуть, расслабиться и спокойно ждать день церемонии.</p>
        <form method="post" action="/reset">
          <button class="secondary-button full-width" type="submit">Заполнить новую анкету</button>
        </form>
      </main>
    </section>
    """


def failure_view() -> str:
    return """
    <section class="entry-screen">
      <main class="completion-panel">
        <div class="brand-lock">Dream Wedding Studio</div>
        <h1>Пока не получилось подготовить материалы.</h1>
        <p>Ответы сохранены. Попробуйте подтвердить анкету чуть позже или напишите ведущему.</p>
        <a class="secondary-button link-button" href="/review">Вернуться к проверке</a>
      </main>
    </section>
    """


def page_redirect(path: str, message: str) -> HTMLResponse:
    return page("Вход", login_view(message))


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Dream Wedding</title>
  <style>{css()}</style>
</head>
<body>
  {body}
</body>
</html>"""
    )


def css() -> str:
    return """
    :root {
      --ink: #17211f;
      --muted: #66736f;
      --line: #d9ded8;
      --paper: #fbfaf7;
      --panel: #ffffff;
      --green: #183c35;
      --gold: #b48a43;
      --rose: #8e4d5a;
      --focus: #2f6f62;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background:
        linear-gradient(120deg, rgba(24,60,53,.08), transparent 36%),
        linear-gradient(240deg, rgba(142,77,90,.10), transparent 34%),
        var(--paper);
    }
    button, input, textarea { font: inherit; }
    .login-screen {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .login-panel {
      width: min(520px, 100%);
      background: rgba(255,255,255,.92);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 34px;
      box-shadow: 0 24px 80px rgba(23,33,31,.12);
    }
    .brand {
      color: var(--green);
      font-weight: 700;
      font-size: 15px;
      letter-spacing: 0;
      margin-bottom: 10px;
    }
    h1 {
      font-size: 34px;
      line-height: 1.12;
      margin: 0 0 14px;
      letter-spacing: 0;
      max-width: 820px;
    }
    p { color: var(--muted); font-size: 16px; line-height: 1.55; }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 15px 16px;
      outline: none;
      color: var(--ink);
    }
    textarea { resize: vertical; min-height: 220px; line-height: 1.5; }
    input:focus, textarea:focus { border-color: var(--focus); box-shadow: 0 0 0 3px rgba(47,111,98,.14); }
    .primary, .secondary, .ghost, .icon-button, .link-button {
      border: 0;
      border-radius: 8px;
      min-height: 46px;
      padding: 0 18px;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      white-space: nowrap;
    }
    .primary { background: var(--green); color: #fff; }
    .secondary { background: #efe8dd; color: var(--ink); }
    .ghost { background: transparent; color: var(--green); border: 1px solid var(--line); }
    .wide { width: 100%; margin-top: 16px; }
    .shell { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 56px; }
    .topbar {
      min-height: 72px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 28px;
    }
    .muted, .section-label, .voice-status { color: var(--muted); font-size: 14px; }
    .workspace { display: grid; grid-template-columns: 220px 1fr; gap: 22px; align-items: start; }
    .rail {
      display: grid;
      gap: 12px;
      position: sticky;
      top: 20px;
    }
    .metric {
      background: rgba(255,255,255,.75);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    .metric span { display: block; font-size: 30px; font-weight: 700; color: var(--rose); }
    .metric small { color: var(--muted); }
    .progress { height: 8px; border-radius: 999px; background: #e5e8e3; overflow: hidden; }
    .progress i { display: block; height: 100%; background: var(--gold); }
    .panel {
      background: rgba(255,255,255,.92);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 30px;
      box-shadow: 0 18px 50px rgba(23,33,31,.08);
    }
    .eyebrow { color: var(--rose); font-weight: 700; font-size: 14px; margin-bottom: 12px; }
    .answer-form { display: grid; gap: 14px; margin-top: 22px; }
    .actions { display: flex; gap: 12px; flex-wrap: wrap; }
    .review-layout { display: grid; grid-template-columns: 360px 1fr; gap: 22px; align-items: start; }
    .review-head {
      position: sticky;
      top: 20px;
      background: rgba(255,255,255,.88);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
    }
    .review-head h1 { font-size: 24px; line-height: 1.24; }
    .answers-list { display: grid; gap: 12px; }
    .answer-card {
      display: grid;
      grid-template-columns: 42px 1fr 48px;
      gap: 14px;
      align-items: start;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .answer-number {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: #efe8dd;
      display: grid;
      place-items: center;
      color: var(--green);
      font-weight: 700;
    }
    .answer-card h2 { font-size: 17px; line-height: 1.35; margin: 0 0 8px; }
    .answer-card p { margin: 0; color: var(--ink); white-space: pre-wrap; }
    .icon-button { width: 42px; min-height: 42px; padding: 0; background: var(--green); color: #fff; font-size: 18px; }
    .alert { margin: 14px 0; padding: 12px 14px; border-radius: 8px; background: #f9e8e9; color: #733640; }
    .success-panel { border-color: rgba(47,111,98,.28); }
    @media (max-width: 820px) {
      .workspace, .review-layout { grid-template-columns: 1fr; }
      .rail, .review-head { position: static; }
      h1 { font-size: 28px; }
      .panel, .login-panel { padding: 22px; }
      .answer-card { grid-template-columns: 34px 1fr; }
      .answer-card form { grid-column: 2; }
      .topbar { align-items: flex-start; flex-direction: column; padding-bottom: 16px; }
    }
    """


def voice_script() -> str:
    return """
    <script>
    const button = document.getElementById('recordButton');
    const statusEl = document.getElementById('voiceStatus');
    const answerEl = document.getElementById('answerText');
    let recorder;
    let chunks = [];
    button?.addEventListener('click', async () => {
      if (recorder && recorder.state === 'recording') {
        recorder.stop();
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        chunks = [];
        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = event => chunks.push(event.data);
        recorder.onstop = async () => {
          stream.getTracks().forEach(track => track.stop());
          button.textContent = 'Голосовой ответ';
          statusEl.textContent = 'Перевожу голос в текст...';
          const blob = new Blob(chunks, { type: 'audio/webm' });
          const data = new FormData();
          data.append('audio', blob, 'voice.webm');
          const response = await fetch('/transcribe', { method: 'POST', body: data });
          const result = await response.json();
          if (result.text) {
            answerEl.value = result.text;
            statusEl.textContent = 'Готово. Текст можно отредактировать перед сохранением.';
          } else {
            statusEl.textContent = 'Не получилось разобрать голос. Напишите ответ текстом.';
          }
        };
        recorder.start();
        button.textContent = 'Остановить запись';
        statusEl.textContent = 'Идет запись...';
      } catch (error) {
        statusEl.textContent = 'Браузер не дал доступ к микрофону. Напишите ответ текстом.';
      }
    });
    </script>
    """
