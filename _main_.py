import asyncio
import base64
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Union

import docx
import pandas as pd
import pypdf
import speech_recognition as sr
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

try:
    from config import PASS, TOKEN
    from db_client import (
        dump_db,
        edit_db,
        edit_dyn,
        exp_db,
        get_chat_ids,
        get_chat_names,
        get_db,
        get_dyn,
        get_path,
        mk_db,
        rm_db,
    )
    from gpt_client import get_gpt
except ImportError:
    # Mocks provided for independent static typing verification
    TOKEN = "YOUR_BOT_TOKEN"
    PASS = "YOUR_ADMIN_PASSWORD"

    def get_gpt(prompt: str, messages: list, img: Optional[str] = None) -> str:
        return "پاسخ نمونه سیستم هوش مصنوعی"

    def get_path(is_cli: bool, chat_id: Union[int, str]) -> str:
        return f"db/{'cli' if is_cli else 'vip'}/{chat_id}.json"

    def get_dyn(key: str) -> list:
        return []

    def edit_dyn(key: str, data: list) -> None:
        pass

    def get_chat_ids(is_cli: bool) -> List[int]:
        return []

    def get_chat_names(is_cli: bool) -> List[str]:
        return []

    def edit_db(*args, **kwargs) -> None:
        pass

    def exp_db(path: str) -> list:
        return []

    def dump_db(*args, **kwargs) -> None:
        pass

    def rm_db(path: str) -> None:
        pass

    def mk_db(is_cli: bool, chat_id: int, name: str) -> None:
        pass

    def get_db(is_cli: bool, path: str, target: None, role: str) -> list:
        return []


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("BotEngine")

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


class NavigationCallback(CallbackData, prefix="nav"):
    action: str
    target_id: str = ""
    index: int = -1


class PersonaCallback(CallbackData, prefix="persona"):
    action: str  # view, add, edit, delete, delete_all
    scope: str  # custom, default
    target_id: str = ""
    index: int = -1


class BotStateGroup(StatesGroup):
    waiting_for_password = State()
    waiting_for_persona_update = State()
    waiting_for_default_persona = State()
    waiting_for_direct_message = State()
    waiting_for_chat_query = State()
    waiting_for_chat_file_import = State()


class MediaProcessorService:
    """Asynchronous offloading wrapper for blocking file and audio processing operations."""

    @staticmethod
    async def process_voice_to_text(
        bot: Bot, voice_file_id: str, file_unique_id: str
    ) -> str:
        ogg_path = TEMP_DIR / f"{file_unique_id}.ogg"
        wav_path = TEMP_DIR / f"{file_unique_id}.wav"

        try:
            tg_file = await bot.get_file(voice_file_id)
            await bot.download_file(tg_file.file_path, destination=ogg_path)

            # Non-blocking execution of FFmpeg conversion via asyncio subprocess
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(ogg_path),
                str(wav_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.communicate()

            def _transcribe() -> str:
                recognizer = sr.Recognizer()
                with sr.AudioFile(str(wav_path)) as source:
                    audio_data = recognizer.record(source)
                return recognizer.recognize_google(audio_data, language="fa-IR")

            return await asyncio.to_thread(_transcribe)

        except Exception as exc:
            logger.error(
                "Error processing voice message: %s", exc, exc_info=True
            )
            return ""
        finally:
            for file in (ogg_path, wav_path):
                if file.exists():
                    file.unlink(missing_ok=True)

    @staticmethod
    async def extract_pdf_text(
        bot: Bot, file_id: str, file_unique_id: str
    ) -> str:
        pdf_path = TEMP_DIR / f"{file_unique_id}.pdf"
        try:
            tg_file = await bot.get_file(file_id)
            await bot.download_file(tg_file.file_path, destination=pdf_path)

            def _read_pdf() -> str:
                reader = pypdf.PdfReader(str(pdf_path))
                return "\n".join(
                    [
                        page.extract_text()
                        for page in reader.pages
                        if page.extract_text()
                    ]
                )

            return await asyncio.to_thread(_read_pdf)
        finally:
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)

    @staticmethod
    async def extract_docx_text(
        bot: Bot, file_id: str, file_unique_id: str
    ) -> str:
        docx_path = TEMP_DIR / f"{file_unique_id}.docx"
        try:
            tg_file = await bot.get_file(file_id)
            await bot.download_file(tg_file.file_path, destination=docx_path)

            def _read_docx() -> str:
                document = docx.Document(str(docx_path))
                return "\n".join(
                    [para.text for para in document.paragraphs if para.text]
                )

            return await asyncio.to_thread(_read_docx)
        finally:
            if docx_path.exists():
                docx_path.unlink(missing_ok=True)

    @staticmethod
    async def extract_table_text(
        bot: Bot, file_id: str, file_unique_id: str, is_csv: bool
    ) -> str:
        ext = "csv" if is_csv else "xlsx"
        file_path = TEMP_DIR / f"{file_unique_id}.{ext}"
        try:
            tg_file = await bot.get_file(file_id)
            await bot.download_file(tg_file.file_path, destination=file_path)

            def _read_table() -> str:
                if is_csv:
                    df = pd.read_csv(str(file_path))
                else:
                    df = pd.read_excel(str(file_path))
                return df.to_string(index=False)

            return await asyncio.to_thread(_read_table)
        finally:
            if file_path.exists():
                file_path.unlink(missing_ok=True)

    @staticmethod
    async def encode_photo_to_base64(
        bot: Bot, file_id: str, file_unique_id: str
    ) -> str:
        photo_path = TEMP_DIR / f"{file_unique_id}.jpg"
        try:
            tg_file = await bot.get_file(file_id)
            await bot.download_file(tg_file.file_path, destination=photo_path)

            def _read_and_encode() -> str:
                with open(photo_path, "rb") as img_f:
                    return base64.b64encode(img_f.read()).decode("utf-8")

            return await asyncio.to_thread(_read_and_encode)
        finally:
            if photo_path.exists():
                photo_path.unlink(missing_ok=True)


class KeyboardBuilder:
    """Centralized keyboard generator adhering to UI/UX standards."""

    @staticmethod
    def build_markup(
        buttons: List[List[InlineKeyboardButton]],
    ) -> InlineKeyboardMarkup:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="بستن پنل ❌",
                    callback_data=NavigationCallback(action="close").pack(),
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @classmethod
    def registration_menu(cls) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(
                    text="ثبت چت (پرسنل) ✅",
                    callback_data=NavigationCallback(
                        action="register_vip"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="ثبت چت (مشتری)",
                    callback_data=NavigationCallback(
                        action="register_cli"
                    ).pack(),
                ),
            ]
        ]
        return cls.build_markup(buttons)

    @classmethod
    def vip_panel_menu(cls) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(
                    text="حذف این چت ❌",
                    callback_data=NavigationCallback(
                        action="delete_chat", target_id="vip"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="لیست چت‌ها 📃",
                    callback_data=NavigationCallback(
                        action="list_chats"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="پرسونای پیش‌فرض 🤖",
                    callback_data=PersonaCallback(
                        action="view", scope="default"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="مدیریت چت‌های مشتری 🔗",
                    callback_data=NavigationCallback(
                        action="manage_clients"
                    ).pack(),
                )
            ],
        ]
        return cls.build_markup(buttons)

    @classmethod
    def client_management_menu(cls, target_id: str) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(
                    text="حذف چت مشتری ❌",
                    callback_data=NavigationCallback(
                        action="delete_chat", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="لیست فلگ‌ها 🚩",
                    callback_data=NavigationCallback(
                        action="list_flags"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="فلگ ریپورت ندانستن (آماده) 💬",
                    callback_data=NavigationCallback(
                        action="toggle_flag1", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="فلگ فوروارد پیوست (آماده) ♻️",
                    callback_data=NavigationCallback(
                        action="toggle_flag2", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="مدیریت پرسونا 🤖",
                    callback_data=PersonaCallback(
                        action="view", scope="custom", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="ایمپورت چت 📩",
                    callback_data=NavigationCallback(
                        action="import_chat", target_id=target_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="اکسپورت چت 📤",
                    callback_data=NavigationCallback(
                        action="export_chat", target_id=target_id
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="پرسش از چت 🎈",
                    callback_data=NavigationCallback(
                        action="query_chat", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="پاسخ از جانب ربات 💬",
                    callback_data=NavigationCallback(
                        action="relay_answer", target_id=target_id
                    ).pack(),
                )
            ],
        ]
        return cls.build_markup(buttons)


async def safe_send_message(
    bot: Bot,
    chat_id: Union[int, str],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None,
    max_length: int = 3800,
) -> None:
    """Splits long text messages into chunks avoiding Telegram character boundary exceptions."""
    if not text:
        return

    chunks = [text[i : i + max_length] for i in range(0, len(text), max_length)]
    for idx, chunk in enumerate(chunks):
        markup = reply_markup if idx == len(chunks) - 1 else None
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_markup=markup,
            parse_mode=parse_mode,
        )


async def dispatch_flag_reports(
    bot: Bot,
    prompt: str,
    response: str,
    title: str,
    target_chat_ids: List[Union[int, str]],
) -> None:
    cleaned_response = response.replace(f"fREPORT=", "")
    report_text = (
        f"💬 چت: {title}\n\n"
        f"🧑 پیام مشتری:\n{prompt}\n\n"
        f"🤖 پاسخ ربات:\n{cleaned_response}\n\n"
        f"🚩 گزارش فلگ سیستم"
    )
    for cid in target_chat_ids:
        try:
            await bot.send_message(chat_id=cid, text=report_text)
        except Exception as exc:
            logger.warning(
                "Failed to dispatch flag report to chat %s: %s", cid, exc
            )


router = Router()


@router.message(Command("start"))
async def handle_start_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "سلام! به سیستم هوشمند پشتیبانی خوش آمدید.\nجهت ثبت یا ورود از دستور /reg یا /panel استفاده کنید."
    )


@router.message(Command("reg"))
async def handle_registration_command(
    message: Message, state: FSMContext
) -> None:
    chat_id = message.chat.id
    if get_path(False, chat_id) or get_path(True, chat_id):
        await message.answer("این چت قبلاً در سیستم ثبت شده است!")
        return

    await message.answer("لطفاً رمز عبور مدیریت را وارد کنید:")
    await state.set_state(BotStateGroup.waiting_for_password)


@router.message(Command("panel"))
async def handle_panel_command(message: Message) -> None:
    chat_id = message.chat.id
    if get_path(False, chat_id):
        await message.answer(
            "پنل مدیریت پرسنل:", reply_markup=KeyboardBuilder.vip_panel_menu()
        )
    elif not get_path(True, chat_id):
        await message.answer("این چت در سیستم ثبت نشده است!")


@router.message(BotStateGroup.waiting_for_password)
async def process_password_input(message: Message, state: FSMContext) -> None:
    if message.text == PASS:
        await message.answer(
            "احراز هویت موفقیت‌آمیز بود. نوع چت را انتخاب کنید:",
            reply_markup=KeyboardBuilder.registration_menu(),
        )
    else:
        await message.answer(
            "رمز عبور اشتباه است. فرآیند ثبت‌نام لغو شد. ❌"
        )
    await state.clear()


@router.message(BotStateGroup.waiting_for_persona_update)
async def process_persona_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")
    edit_type = data.get("type")
    target_persona = data.get("target")

    path = get_path(True, target_chat_id)
    edit_db(edit_type, path, target_persona, message.text)

    await message.answer("پرسونا با موفقیت ویرایش و ذخیره شد! ✅")
    await state.clear()


@router.message(BotStateGroup.waiting_for_default_persona)
async def process_default_persona_input(
    message: Message, state: FSMContext
) -> None:
    data = await state.get_data()
    index = data.get("index")

    default_personas = get_dyn("default_persona") or []
    if index is not None and index >= 0:
        if index < len(default_personas):
            default_personas[index] = message.text
    else:
        default_personas.append(message.text)

    edit_dyn("default_persona", default_personas)
    await message.answer("پرسونای پیش‌فرض با موفقیت به‌روزرسانی شد! ✅")
    await state.clear()


@router.message(BotStateGroup.waiting_for_direct_message)
async def process_relay_message(
    bot: Bot, message: Message, state: FSMContext
) -> None:
    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")

    try:
        await bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await message.answer("پیام با موفقیت برای مشتری ارسال شد! ✅")
    except Exception as exc:
        logger.error("Failed to relay message to %s: %s", target_chat_id, exc)
        await message.answer("خطا در ارسال پیام به مشتری! ❌")
    finally:
        await state.clear()


@router.message(BotStateGroup.waiting_for_chat_query)
async def process_chat_query(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")

    path = get_path(True, target_chat_id)
    history = exp_db(path)

    response = await asyncio.to_thread(
        get_gpt, message.text, history, None
    )
    formatted_response = f"📃 خروجی پرسش از تاریخچه چت:\n\n{response}"

    await safe_send_message(
        bot=message.bot, chat_id=message.chat.id, text=formatted_response
    )
    await state.clear()


@router.message(F.text | F.photo | F.document | F.voice | F.audio)
async def process_chatgpt_interaction(
    bot: Bot, message: Message, state: FSMContext
) -> None:
    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.full_name or "Unknown Chat"

    # Verify registration context
    if get_path(False, chat_id):
        await message.answer(
            "چت پرسنل تنها جهت کنترل ربات از طریق /panel استفاده می‌شود."
        )
        return

    if not get_path(True, chat_id):
        await message.answer("این چت در سیستم ربات ثبت نشده است!")
        return

    prompt = ""
    image_base64: Optional[str] = None
    file_unique_id = str(message.message_id)

    # 1. Attachment Forwarding Flag Handling (pr_flg2)
    if (
        message.photo
        or message.document
        or message.voice
        or message.video
        or message.audio
    ):
        pr_flg2_data = get_dyn("pr_flg2") or []
        for item in pr_flg2_data:
            if str(chat_id) == str(item.get("src")):
                for dest_id in item.get("dest", []):
                    try:
                        await message.forward(chat_id=dest_id)
                        await bot.send_message(
                            chat_id=dest_id,
                            text=f"📎 پیوست جدید دریافتی از چت: {chat_title}",
                        )
                    except Exception as exc:
                        logger.warning(
                            "Error forwarding attachment to %s: %s",
                            dest_id,
                            exc,
                        )

    # 2. Extract media/document content into prompt
    if message.voice:
        prompt = await MediaProcessorService.process_voice_to_text(
            bot, message.voice.file_id, file_unique_id
        )

    elif message.document:
        mime = message.document.mime_type or ""
        if mime == "application/pdf":
            prompt = await MediaProcessorService.extract_pdf_text(
                bot, message.document.file_id, file_unique_id
            )
        elif (
            mime
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            prompt = await MediaProcessorService.extract_docx_text(
                bot, message.document.file_id, file_unique_id
            )
        elif mime in (
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ):
            is_csv = mime == "text/csv"
            prompt = await MediaProcessorService.extract_table_text(
                bot, message.document.file_id, file_unique_id, is_csv
            )

    elif message.photo:
        image_base64 = await MediaProcessorService.encode_photo_to_base64(
            bot, message.photo[-1].file_id, file_unique_id
        )
        prompt = "توضیح بده!"

    # Append caption or text content
    if message.caption:
        prompt = f"{message.caption}\n{prompt}".strip()
    elif message.text:
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and not message.reply_to_message.from_user.is_bot
        ):
            prompt = (
                f"{message.reply_to_message.text}\n{message.text}".strip()
            )
        else:
            prompt = message.text

        # Handle Google Spreadsheets Link
        if "docs.google.com/spreadsheets" in prompt:
            try:
                base_part = prompt.split("docs.google.com/")[1].split(
                    "/edit"
                )[0]
                csv_url = f"https://docs.google.com/{base_part}/export?format=csv"

                def _fetch_sheet() -> str:
                    df = pd.read_csv(csv_url)
                    return df.to_string(index=False)

                sheet_data = await asyncio.to_thread(_fetch_sheet)
                prompt += f"\n{sheet_data}"
            except Exception as exc:
                logger.error("Error reading Google Sheet URL: %s", exc)

    if not prompt.strip():
        await message.reply("بررسی می‌کنم، اطلاع میدم!")
        return

    # Fetch History and Generate Response from GPT
    path = get_path(True, chat_id)
    history = exp_db(path)

    ai_response = await asyncio.to_thread(
        get_gpt, prompt, history, image_base64
    )

    # 3. Report Trigger Flags Handling
    if "fREPORT=ALL" in ai_response:
        all_vips = get_chat_ids(False)
        await dispatch_flag_reports(
            bot, prompt, ai_response, chat_title, all_vips
        )
    elif "fREPORT=" in ai_response:
        try:
            target_report_id = (
                ai_response.split("fREPORT=")[1].split()[0].strip()
            )
            await dispatch_flag_reports(
                bot, prompt, ai_response, chat_title, [target_report_id]
            )
        except IndexingError:
            pass

    # 4. Keyword Report Trigger Flag Handling (pr_flg1)
    unknown_keywords = [
        "اطلاع",
        "نمیدانم",
        "نمی‌دانم",
        "نمی دانم",
        "نمیدونم",
        "نمی‌دونم",
        "نمی دونم",
    ]
    if any(kw in ai_response for kw in unknown_keywords):
        pr_flg1_data = get_dyn("pr_flg1") or []
        for item in pr_flg1_data:
            if str(chat_id) == str(item.get("src")):
                await dispatch_flag_reports(
                    bot,
                    prompt,
                    ai_response,
                    chat_title,
                    item.get("dest", []),
                )

    # Clean flags from presentation text
    clean_display_response = ai_response
    for flag in get_dyn("flgs") or []:
        clean_display_response = clean_display_response.replace(flag, "")

    await message.reply(clean_display_response)

    # Update Database State History
    edit_db(False, path, "user", prompt)
    edit_db(False, path, "assistant", clean_display_response)


@router.callback_query(NavigationCallback.filter())
async def handle_navigation_callbacks(
    callback: CallbackQuery,
    callback_data: NavigationCallback,
    state: FSMContext,
) -> None:
    chat_id = callback.message.chat.id
    action = callback_data.action
    target_id = callback_data.target_id

    if action == "close":
        await callback.message.delete()
        await callback.answer()
        return

    elif action == "register_cli":
        chat_name = (
            callback.message.chat.title
            or callback.message.chat.full_name
            or ""
        )
        mk_db(True, chat_id, chat_name)
        await callback.message.answer("چت مشتری با موفقیت ثبت شد! ✅")

    elif action == "register_vip":
        chat_name = (
            callback.message.chat.title
            or callback.message.chat.full_name
            or ""
        )
        mk_db(False, chat_id, chat_name)
        await callback.message.answer("چت پرسنل با موفقیت ثبت شد! ✅")

    elif action == "delete_chat":
        if target_id == "vip":
            vip_path = get_path(False, chat_id)
            if vip_path:
                rm_db(vip_path)
        else:
            rm_db(get_path(True, target_id))
            for ftype in ["pr_flg1", "pr_flg2"]:
                f_data = [
                    item
                    for item in (get_dyn(ftype) or [])
                    if str(target_id) != str(item.get("src"))
                ]
                edit_dyn(ftype, f_data)
        await callback.message.answer("چت با موفقیت حذف شد! ✅")

    elif action == "list_chats":
        cli_names = get_chat_names(True) or []
        vip_names = get_chat_names(False) or []

        cli_str = (
            "\n".join([f"• {name} (cli)" for name in cli_names])
            if cli_names
            else "هیچ چت مشتری ثبت نشده!"
        )
        vip_str = (
            "\n".join([f"• {name} (vip)" for name in vip_names])
            if vip_names
            else "هیچ چتی ثبت نشده!"
        )

        response_msg = (
            f"💚 **چت‌های پرسنل (VIP):**\n{vip_str}\n\n"
            f"🔷 **چت‌های مشتری (CLI):**\n{cli_str}"
        )
        await safe_send_message(
            bot=callback.bot, chat_id=chat_id, text=response_msg
        )

    elif action == "list_flags":
        text = (
            "🚩 **راهنمای فلگ‌های گزارش‌دهی:**\n\n"
            f"`fREPORT={chat_id}`\nارسال گزارش چت مشتری به این پنل چت جاری.\n\n"
            "`fREPORT=ALL`\nارسال گزارش عمومی به تمامی چت‌های پرسنل ثبت شده."
        )
        await callback.message.answer(text, parse_mode="Markdown")

    elif action == "manage_clients":
        cli_names = get_chat_names(True) or []
        cli_ids = get_chat_ids(True) or []

        if not cli_names:
            await callback.message.answer(
                "هیچ چت مشتری برای مدیریت یافت نشد!"
            )
        else:
            buttons = [
                [
                    InlineKeyboardButton(
                        text=name,
                        callback_data=NavigationCallback(
                            action="select_client", target_id=str(cid)
                        ).pack(),
                    )
                ]
                for name, cid in zip(cli_names, cli_ids)
            ]
            await callback.message.answer(
                "چت مشتری مدنظر را انتخاب کنید:",
                reply_markup=KeyboardBuilder.build_markup(buttons),
            )

    elif action == "select_client":
        await callback.message.answer(
            f"مدیریت چت مشتری ({target_id}):",
            reply_markup=KeyboardBuilder.client_management_menu(target_id),
        )

    elif action == "relay_answer":
        await state.update_data(target_chat_id=target_id)
        await state.set_state(BotStateGroup.waiting_for_direct_message)
        await callback.message.answer("لطفاً پیام ارسالی به مشتری را بنویسید:")

    elif action == "query_chat":
        await state.update_data(target_chat_id=target_id)
        await state.set_state(BotStateGroup.waiting_for_chat_query)
        await callback.message.answer("پرسش خود درباره این چت را وارد کنید:")

    elif action in ("toggle_flag1", "toggle_flag2"):
        flag_key = "pr_flg1" if action == "toggle_flag1" else "pr_flg2"
        flag_data = get_dyn(flag_key) or []

        for item in flag_data:
            if str(item.get("src")) == str(target_id):
                if chat_id in item["dest"]:
                    item["dest"].remove(chat_id)
                    await callback.message.answer("فلگ غیرفعال شد! 🚫")
                else:
                    item["dest"].append(chat_id)
                    await callback.message.answer("فلگ فعال شد! ✅")
                break
        else:
            flag_data.append({"src": str(target_id), "dest": [chat_id]})
            await callback.message.answer("فلگ فعال شد! ✅")

        edit_dyn(flag_key, flag_data)

    elif action == "export_chat":
        file_path = get_path(True, target_id)
        if file_path and Path(file_path).exists():
            await callback.bot.send_document(
                chat_id=chat_id, document=FSInputFile(file_path)
            )
        else:
            await callback.message.answer("فایل چت یافت نشد! ❌")

    await callback.answer()


@router.callback_query(PersonaCallback.filter())
async def handle_persona_callbacks(
    callback: CallbackQuery, callback_data: PersonaCallback, state: FSMContext
) -> None:
    action = callback_data.action
    scope = callback_data.scope
    target_id = callback_data.target_id
    index = callback_data.index
    chat_id = callback.message.chat.id

    if action == "view":
        is_default = scope == "default"
        if is_default:
            personas = get_dyn("default_persona") or []
        else:
            personas = (
                get_db(
                    False, get_path(True, target_id), None, "system"
                )
                or []
            )

        text = (
            "🤖 **پرسونای فعلی:**\n\n"
            + "\n\n".join(
                [f"{i + 1}. {p}" for i, p in enumerate(personas)]
            )
            if personas
            else "هیچ پرسونایی ثبت نشده است!"
        )

        buttons = [
            [
                InlineKeyboardButton(
                    text="اضافه کردن ➕",
                    callback_data=PersonaCallback(
                        action="add", scope=scope, target_id=target_id
                    ).pack(),
                )
            ]
        ]
        if personas:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="ویرایش ابعاد ✏️",
                        callback_data=PersonaCallback(
                            action="edit_list",
                            scope=scope,
                            target_id=target_id,
                        ).pack(),
                    ),
                    InlineKeyboardButton(
                        text="حذف ❌",
                        callback_data=PersonaCallback(
                            action="delete_list",
                            scope=scope,
                            target_id=target_id,
                        ).pack(),
                    ),
                ]
            )

        await safe_send_message(
            bot=callback.bot,
            chat_id=chat_id,
            text=text,
            reply_markup=KeyboardBuilder.build_markup(buttons),
        )

    elif action == "add":
        if scope == "default":
            await state.update_data(index=None)
            await state.set_state(BotStateGroup.waiting_for_default_persona)
        else:
            await state.update_data(
                target_chat_id=target_id, type=False, target="system"
            )
            await state.set_state(BotStateGroup.waiting_for_persona_update)
        await callback.message.answer("لطفاً متن پرسونای جدید را وارد کنید:")

    elif action == "edit_list":
        personas = (
            get_dyn("default_persona")
            if scope == "default"
            else get_db(
                False, get_path(True, target_id), None, "system"
            )
        ) or []
        buttons = [
            [
                InlineKeyboardButton(
                    text=f"{idx + 1}. {p[:25]}...",
                    callback_data=PersonaCallback(
                        action="edit_item",
                        scope=scope,
                        target_id=target_id,
                        index=idx,
                    ).pack(),
                )
            ]
            for idx, p in enumerate(personas)
        ]
        await callback.message.answer(
            "بعد مدنظر جهت ویرایش را انتخاب کنید:",
            reply_markup=KeyboardBuilder.build_markup(buttons),
        )

    elif action == "edit_item":
        if scope == "default":
            await state.update_data(index=index)
            await state.set_state(BotStateGroup.waiting_for_default_persona)
        else:
            personas = (
                get_db(
                    False, get_path(True, target_id), None, "system"
                )
                or []
            )
            target_val = personas[index] if index < len(personas) else ""
            await state.update_data(
                target_chat_id=target_id, type=True, target=target_val
            )
            await state.set_state(BotStateGroup.waiting_for_persona_update)
        await callback.message.answer(
            "لطفاً متن جدید پرسونا را ارسال کنید:"
        )

    elif action == "delete_list":
        personas = (
            get_dyn("default_persona")
            if scope == "default"
            else get_db(
                False, get_path(True, target_id), None, "system"
            )
        ) or []
        buttons = [
            [
                InlineKeyboardButton(
                    text=f"{idx + 1}. {p[:25]}...",
                    callback_data=PersonaCallback(
                        action="delete_item",
                        scope=scope,
                        target_id=target_id,
                        index=idx,
                    ).pack(),
                )
            ]
            for idx, p in enumerate(personas)
        ]
        buttons.append(
            [
                InlineKeyboardButton(
                    text="حذف کل ابعاد ❌",
                    callback_data=PersonaCallback(
                        action="delete_all", scope=scope, target_id=target_id
                    ).pack(),
                )
            ]
        )
        await callback.message.answer(
            "مورد جهت حذف را انتخاب کنید:",
            reply_markup=KeyboardBuilder.build_markup(buttons),
        )

    elif action == "delete_item":
        if scope == "default":
            personas = get_dyn("default_persona") or []
            if 0 <= index < len(personas):
                personas.pop(index)
                edit_dyn("default_persona", personas)
        else:
            personas = (
                get_db(
                    False, get_path(True, target_id), None, "system"
                )
                or []
            )
            if 0 <= index < len(personas):
                dump_db(
                    True,
                    get_path(True, target_id),
                    None,
                    personas[index],
                )
        await callback.message.answer("پرسونا با موفقیت حذف شد! ✅")

    elif action == "delete_all":
        if scope == "default":
            edit_dyn("default_persona", [])
        else:
            dump_db(False, get_path(True, target_id), "system", None)
        await callback.message.answer("تمام ابعاد پرسونا ریست گردید! ✅")

    await callback.answer()


async def main() -> None:
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Initializing Bot Polling Engine...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution terminated cleanly.")
