
import asyncio
import base64
import logging
import subprocess
import tempfile
from pathlib import Path

from anthropic import AsyncAnthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==================================================
# ТВОИ ТРИ НАСТРОЙКИ
# ==================================================

TELEGRAM_TOKEN = "ВСТАВЬ_ТОКЕН_ТЕЛЕГРАМ"
CLAUDE_API_KEY = "ВСТАВЬ_API_КЛЮЧ_CLAUDE"
ADMIN_ID = 0

# Сначала оставь ADMIN_ID = 0.
# Запусти бота, отправь /myid.
# Вставь полученное число сюда и перезапусти бота.

# ==================================================
# НАСТРОЙКИ БОТА
# ==================================================

MODELS = {
    "opus": ("Claude Opus 5.5", "claude-opus-5-5"),
    "sonnet": ("Claude Sonnet 5.5", "claude-sonnet-5-5"),
    "haiku": ("Claude Haiku 5.5", "claude-haiku-5-5"),
    "fable": ("Claude Fable 5.2", "claude-fable-5-2"),
}

DEFAULT_MODEL = "sonnet"
MAX_TOKENS = 2000
MAX_HISTORY = 20
MAX_VIDEO_SIZE = 19 * 1024 * 1024
MAX_VIDEO_FRAMES = 6

SYSTEM_PROMPT = """
Ты умный, внимательный и дружелюбный ИИ-помощник.
Отвечай на языке пользователя.
Помогай с программированием, учебой,
анализом изображений и повседневными задачами.
Если получаешь фотографию или кадры видео,
внимательно анализируй их.
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not TELEGRAM_TOKEN.startswith("ВСТАВЬ") and TELEGRAM_TOKEN:
    pass
else:
    raise ValueError("Вставь Telegram Token!")

if not CLAUDE_API_KEY.startswith("ВСТАВЬ") and CLAUDE_API_KEY:
    pass
else:
    raise ValueError("Вставь Claude API Key!")

claude = AsyncAnthropic(api_key=CLAUDE_API_KEY)

histories = {}
user_models = {}


# ==================================================
# ПРОВЕРКА АДМИНИСТРАТОРА
# ==================================================

def is_admin(update):
    return (
        update.effective_user is not None
        and ADMIN_ID != 0
        and update.effective_user.id == ADMIN_ID
    )


async def access(update):
    if is_admin(update):
        return True

    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Доступ запрещён. Этот бот личный."
        )

    return False


# ==================================================
# ПОЛУЧЕНИЕ TELEGRAM ID
# ==================================================

async def myid(update, context):
    await update.message.reply_text(
        f"Твой Telegram ID: {update.effective_user.id}\n\n"
        "Вставь это число в ADMIN_ID в файле bot.py "
        "и перезапусти программу."
    )


# ==================================================
# СТАРТ
# ==================================================

async def start(update, context):
    if not await access(update):
        return

    model = user_models.get(
        update.effective_user.id, DEFAULT_MODEL
    )

    keyboard = [
        [InlineKeyboardButton(
            "🤖 Выбрать модель",
            callback_data="models"
        )],
        [InlineKeyboardButton(
            "🧹 Очистить историю",
            callback_data="reset"
        )]
    ]

    await update.message.reply_text(
        f"Привет! Я твой личный Claude AI.\n\n"
        f"Текущая модель: {MODELS[model][0]}\n\n"
        "Я умею:\n"
        "💬 Общаться\n"
        "📸 Анализировать фотографии\n"
        "🎬 Анализировать видео по кадрам\n"
        "🧠 Помнить историю диалога\n\n"
        "Выбирай модель кнопкой ниже или используй /model.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================================================
# ВЫБОР МОДЕЛИ
# ==================================================

async def choose_model(update, context):
    if not await access(update):
        return

    keyboard = [
        [InlineKeyboardButton(
            name,
            callback_data=f"select:{key}"
        )]
        for key, (name, model_id) in MODELS.items()
    ]

    await update.message.reply_text(
        "Выбери модель Claude:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buttons(update, context):
    query = update.callback_query

    if not is_admin(update):
        await query.answer("Нет доступа", show_alert=True)
        return

    await query.answer()

    if query.data == "models":
        keyboard = [
            [InlineKeyboardButton(
                name,
                callback_data=f"select:{key}"
            )]
            for key, (name, model_id) in MODELS.items()
        ]

        await query.edit_message_text(
            "Выбери модель:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("select:"):
        key = query.data.split(":", 1)[1]

        if key not in MODELS:
            return

        user_models[update.effective_user.id] = key

        await query.edit_message_text(
            f"✅ Выбрана модель: {MODELS[key][0]}"
        )

    elif query.data == "reset":
        histories[update.effective_user.id] = []

        await query.edit_message_text(
            "🧹 История переписки очищена!"
        )


# ==================================================
# ОЧИСТКА ИСТОРИИ
# ==================================================

async def reset(update, context):
    if not await access(update):
        return

    histories[update.effective_user.id] = []

    await update.message.reply_text(
        "История очищена!"
    )


# ==================================================
# ОБЩЕНИЕ С CLAUDE
# ==================================================

async def ask_claude(update, content):
    user_id = update.effective_user.id

    history = histories.setdefault(user_id, [])

    history.append({
        "role": "user",
        "content": content
    })

    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]

    while history and history[0]["role"] != "user":
        history.pop(0)

    model_key = user_models.get(user_id, DEFAULT_MODEL)
    model_id = MODELS[model_key][1]

    try:
        await update.get_bot().send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        response = await claude.messages.create(
            model=model_id,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=history
        )

        answer = "\n".join(
            block.text
            for block in response.content
            if block.type == "text"
        ).strip()

        if not answer:
            answer = "Claude не вернул текстовый ответ."

        history.append({
            "role": "assistant",
            "content": answer
        })

        for i in range(0, len(answer), 4000):
            await update.effective_message.reply_text(
                answer[i:i + 4000]
            )

    except Exception:
        logger.exception("Ошибка Claude API")

        if history and history[-1]["role"] == "user":
            history.pop()

        await update.effective_message.reply_text(
            "Ошибка Claude API. Проверь ключ, баланс "
            "и доступность выбранной модели."
        )


# ==================================================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# ==================================================

async def text_message(update, context):
    if not await access(update):
        return

    await ask_claude(
        update,
        update.message.text
    )


# ==================================================
# ФОТОГРАФИИ
# ==================================================

async def photo_message(update, context):
    if not await access(update):
        return

    message = update.message

    try:
        file = await context.bot.get_file(
            message.photo[-1].file_id
        )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "photo.jpg"

            await file.download_to_drive(path)

            image_data = base64.b64encode(
                path.read_bytes()
            ).decode("utf-8")

        prompt = message.caption or "Проанализируй фотографию."

        content = [
            {
                "type": "text",
                "text": prompt
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_data
                }
            }
        ]

        await ask_claude(update, content)

    except Exception:
        logger.exception("Ошибка фото")
        await message.reply_text(
            "Не удалось обработать фотографию."
        )


# ==================================================
# АНАЛИЗ ВИДЕО
# ==================================================

def extract_frames(video_path, output_dir):
    pattern = str(output_dir / "frame-%02d.jpg")

    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", str(video_path),
            "-vf", "fps=1/5,scale=768:-1",
            "-frames:v", str(MAX_VIDEO_FRAMES),
            "-q:v", "5",
            pattern
        ],
        check=True,
        timeout=90
    )

    return sorted(output_dir.glob("frame-*.jpg"))


async def process_video(
    update,
    context,
    file_id,
    file_size,
    caption
):
    message = update.effective_message

    if file_size and file_size > MAX_VIDEO_SIZE:
        await message.reply_text(
            "Видео слишком большое. Максимум 19 МБ."
        )
        return

    try:
        await message.reply_text(
            "🎬 Получаю видео и подготавливаю кадры..."
        )

        telegram_file = await context.bot.get_file(file_id)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video_path = root / "video.mp4"
            frames_dir = root / "frames"
            frames_dir.mkdir()

            await telegram_file.download_to_drive(video_path)

            frames = await asyncio.to_thread(
                extract_frames,
                video_path,
                frames_dir
            )

            if not frames:
                await message.reply_text(
                    "Не удалось получить кадры видео."
                )
                return

            content = [{
                "type": "text",
                "text": (
                    (caption + "\n\n" if caption else "")
                    + "Проанализируй следующие кадры видео "
                    "по порядку. Это выборочные кадры."
                )
            }]

            for frame in frames:
                data = base64.b64encode(
                    frame.read_bytes()
                ).decode("utf-8")

                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": data
                    }
                })

        await ask_claude(update, content)

    except FileNotFoundError:
        await message.reply_text(
            "Установи FFmpeg для анализа видео. "
            "Фото и текст работают без него."
        )

    except Exception:
        logger.exception("Ошибка видео")
        await message.reply_text(
            "Не удалось обработать видео."
        )


async def video_message(update, context):
    if not await access(update):
        return

    video = update.message.video

    await process_video(
        update,
        context,
        video.file_id,
        video.file_size,
        update.message.caption
    )


async def video_document(update, context):
    if not await access(update):
        return

    document = update.message.document

    if (
        document.mime_type
        and document.mime_type.startswith("video/")
    ):
        await process_video(
            update,
            context,
            document.file_id,
            document.file_size,
            update.message.caption
        )
    else:
        await update.message.reply_text(
            "Поддерживаются текст, фото и видео."
        )


# ==================================================
# ЗАПУСК
# ==================================================

def main():
    if ADMIN_ID == 0:
        print(
            "Сначала отправь /myid боту, "
            "впиши свой ID в ADMIN_ID и перезапусти."
        )

    app = Application.builder().token(
        TELEGRAM_TOKEN
    ).build()

    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("model", choose_model))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(
        CallbackQueryHandler(buttons)
    )

    app.add_handler(
        MessageHandler(filters.PHOTO, photo_message)
    )

    app.add_handler(
        MessageHandler(filters.VIDEO, video_message)
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            video_document
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message
        )
    )

    print("Claude Telegram Bot запущен!")

    app.run_polling()


if __name__ == "__main__":
    main()
