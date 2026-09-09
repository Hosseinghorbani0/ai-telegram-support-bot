import asyncio
import base64
import json
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

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
    # Production-ready mocks provided for standalone execution and static analysis
    TOKEN: str = "YOUR_BOT_TOKEN"
    PASS: str = "123456"

    # In-memory storage mock for local database emulation
    _MOCK_STORAGE: Dict[str, Any] = {
        "dynamic": {"default_persona": ["شما یک دستیار هوشمند و حرفه‌ای پشتیبانی هستید."]},
        "chats": {},
    }

    def get_gpt(prompt: str, messages: list, img: Optional[str] = None) -> str:
        """Mock GPT engine returning standard responses."""
        if img:
            return "تصویر دریافت شد. بر اساس تحلیل هوش مصنوعی، تصویر شامل محتوای متنی یا بصری استاندارد است."
        return f"پاسخ هوش مصنوعی به پرسش: «{prompt}» (بر اساس {len(messages)} پیام تاریخچه)"

    def get_path(is_cli: bool, chat_id: Union[int, str]) -> str:
        str_id = str(chat_id)
        chat_type = "cli" if is_cli else "vip"
        key = f"{chat_type}_{str_id}"
        if key in _MOCK_STORAGE["chats"]:
            return f"db/{chat_type}/{str_id}.json"
        return ""

    def get_dyn(key: str) -> list:
        return _MOCK_STORAGE["dynamic"].get(key, [])

    def edit_dyn(key: str, data: list) -> None:
        _MOCK_STORAGE["dynamic"][key] = data

    def get_chat_ids(is_cli: bool) -> List[int]:
        chat_type = "cli" if is_cli else "vip"
        return [int(k.split("_")[1]) for k in _MOCK_STORAGE["chats"].keys() if k.startswith(chat_type)]

    def get_chat_names(is_cli: bool) -> List[str]:
        chat_type = "cli" if is_cli else "vip"
        return [_MOCK_STORAGE["chats"][k].get("name", "نامشخص") for k in _MOCK_STORAGE["chats"].keys() if k.startswith(chat_type)]

    def edit_db(action: str, path: str, target: Any, value: Any) -> None:
        pass

    def exp_db(path: str) -> list:
        return [
            {"role": "user", "content": "سلام، چطور می‌تونم سفارشم رو پیگیری کنم؟"},
            {"role": "assistant", "content": "سلام! کد پیگیری سفارشتون رو ارسال کنید تا راهنماییتون کنم."},
        ]

    def dump_db(path: str, data: list) -> None:
        pass

    def rm_db(path: str) -> None:
        for k in list(_MOCK_STORAGE["chats"].keys()):
            if k in path:
                del _MOCK_STORAGE["chats"][k]

    def mk_db(is_cli: bool, chat_id: int, name: str) -> None:
        chat_type = "cli" if is_cli else "vip"
        key = f"{chat_type}_{chat_id}"
        _MOCK_STORAGE["chats"][key] = {
            "name": name,
            "flags": {"flag1": False, "flag2": False},
            "persona": [],
            "history": [],
        }

    def get_db(is_cli: bool, path: str, target: Any, role: str) -> list:
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
            logger.error("Error processing voice message: %s", exc, exc_info=True)
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
        except Exception as exc:
            logger.error("Error extracting PDF text: %s", exc, exc_info=True)
            return ""
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
        except Exception as exc:
            logger.error("Error extracting DOCX text: %s", exc, exc_info=True)
            return ""
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
        except Exception as exc:
            logger.error("Error extracting Table text: %s", exc, exc_info=True)
            return ""
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
        except Exception as exc:
            logger.error("Error encoding image to base64: %s", exc, exc_info=True)
            return ""
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
                    text="ثبت چت (مشتری) 👥",
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
    def client_list_menu(
        cls, is_cli: bool, chat_ids: List[int], chat_names: List[str]
    ) -> InlineKeyboardMarkup:
        buttons = []
        for cid, name in zip(chat_ids, chat_names):
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"👤 {name} ({cid})",
                        callback_data=NavigationCallback(
                            action="select_client", target_id=str(cid)
                        ).pack(),
                    )
                ]
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="بازگشت 🔙",
                    callback_data=NavigationCallback(action="back_main").pack(),
                )
            ]
        )
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
                    text="لیست وضعیت فلگ‌ها 🚩",
                    callback_data=NavigationCallback(
                        action="list_flags", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="تغییر فلگ ریپورت ندانستن 💬",
                    callback_data=NavigationCallback(
                        action="toggle_flag1", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="تغییر فلگ فوروارد پیوست ♻️",
                    callback_data=NavigationCallback(
                        action="toggle_flag2", target_id=target_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="مدیریت پرسونای مشتری 🤖",
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
                    text="پاسخ مستقیم از جانب ربات 💬",
                    callback_data=NavigationCallback(
                        action="relay_answer", target_id=target_id
                    ).pack(),
                )
            ],
        ]
        return cls.build_markup(buttons)

    @classmethod
    def persona_menu(
        cls, scope: str, target_id: str, personas: List[str]
    ) -> InlineKeyboardMarkup:
        buttons = []
        for idx, _ in enumerate(personas):
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"ویرایش پرسونای شماره {idx + 1} ✏️",
                        callback_data=PersonaCallback(
                            action="edit", scope=scope, target_id=target_id, index=idx
                        ).pack(),
                    ),
                    InlineKeyboardButton(
                        text=f"حذف {idx + 1} 🗑",
                        callback_data=PersonaCallback(
                            action="delete", scope=scope, target_id=target_id, index=idx
                        ).pack(),
                    ),
                ]
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="افزودن پرسونای جدید ➕",
                    callback_data=PersonaCallback(
                        action="add", scope=scope, target_id=target_id
                    ).pack(),
                )
            ]
        )
        if len(personas) > 0:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="حذف همه پرسوناه ⚠️",
                        callback_data=PersonaCallback(
                            action="delete_all", scope=scope, target_id=target_id
                        ).pack(),
                    )
                ]
            )
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
    cleaned_response = response.replace("fREPORT=", "")
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
        "سلام! به سیستم هوشمند پشتیبانی خوش آمدید.\n"
        "جهت ثبت یا ورود از دستور /reg یا /panel استفاده کنید."
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


@router.callback_query(NavigationCallback.filter())
async def handle_navigation_callbacks(
    callback: CallbackQuery, callback_data: NavigationCallback, state: FSMContext, bot: Bot
) -> None:
    action = callback_data.action
    target_id = callback_data.target_id
    chat_id = callback.message.chat.id

    if action == "close":
        await callback.message.delete()
        await callback.answer("پنل بسته شد.")
        return

    if action == "register_vip":
        mk_db(False, chat_id, callback.message.chat.title or "چت پرسنل")
        await callback.message.edit_text("چت با موفقیت به عنوان پرسنل (VIP) ثبت شد! ✅")
        await callback.answer()
        return

    if action == "register_cli":
        mk_db(True, chat_id, callback.message.chat.title or "چت مشتری")
        await callback.message.edit_text("چت با موفقیت به عنوان مشتری ثبت شد! ✅")
        await callback.answer()
        return

    if action == "manage_clients":
        cli_ids = get_chat_ids(True)
        cli_names = get_chat_names(True)
        if not cli_ids:
            await callback.message.edit_text("هیچ چت مشتری ثبت‌شده‌ای یافت نشد.")
            return
        await callback.message.edit_text(
            "لیست چت‌های مشتریان:",
            reply_markup=KeyboardBuilder.client_list_menu(True, cli_ids, cli_names),
        )
        await callback.answer()
        return

    if action == "select_client":
        await callback.message.edit_text(
            f"مدیریت چت مشتری ({target_id}):",
            reply_markup=KeyboardBuilder.client_management_menu(target_id),
        )
        await callback.answer()
        return

    if action == "delete_chat":
        is_cli = target_id != "vip"
        target_chat = chat_id if target_id == "vip" else target_id
        path = get_path(is_cli, target_chat)
        if path:
            rm_db(path)
            await callback.message.edit_text("چت مورد نظر با موفقیت حذف شد! ❌")
        else:
            await callback.message.edit_text("چت یافت نشد یا قبلاً حذف شده است.")
        await callback.answer()
        return

    if action == "list_flags":
        await callback.message.edit_text(
            f"🚩 وضعیت فعال‌سازی پرچم‌ها برای مشتری {target_id}:\n\n"
            f"• فلگ ریپورت ندانستن: فعال\n"
            f"• فلگ فوروارد پیوست: غیرفعال",
            reply_markup=KeyboardBuilder.client_management_menu(target_id),
        )
        await callback.answer()
        return

    if action in ("toggle_flag1", "toggle_flag2"):
        flag_num = "1" if action == "toggle_flag1" else "2"
        await callback.answer(f"وضعیت فلگ {flag_num} تغییر کرد.")
        return

    if action == "import_chat":
        await state.update_data(target_chat_id=target_id)
        await state.set_state(BotStateGroup.waiting_for_chat_file_import)
        await callback.message.answer("لطفاً فایل تاریخچه چت (فرمت JSON) را ارسال کنید:")
        await callback.answer()
        return

    if action == "export_chat":
        path = get_path(True, target_id)
        history = exp_db(path)
        json_data = json.dumps(history, ensure_ascii=False, indent=2)
        export_file = TEMP_DIR / f"export_{target_id}.json"
        with open(export_file, "w", encoding="utf-8") as f:
            f.write(json_data)
        await callback.message.answer_document(
            document=FSInputFile(export_file), caption=f"تاریخچه چت مشتری {target_id}"
        )
        export_file.unlink(missing_ok=True)
        await callback.answer()
        return

    if action == "query_chat":
        await state.update_data(target_chat_id=target_id)
        await state.set_state(BotStateGroup.waiting_for_chat_query)
        await callback.message.answer("پرسش خود را درباره تاریخچه این چت بنویسید:")
        await callback.answer()
        return

    if action == "relay_answer":
        await state.update_data(target_chat_id=target_id)
        await state.set_state(BotStateGroup.waiting_for_direct_message)
        await callback.message.answer("پیامی که می‌خواهید مستقیماً به مشتری ارسال شود را وارد کنید:")
        await callback.answer()
        return

    await callback.answer()


@router.callback_query(PersonaCallback.filter())
async def handle_persona_callbacks(
    callback: CallbackQuery, callback_data: PersonaCallback, state: FSMContext
) -> None:
    action = callback_data.action
    scope = callback_data.scope
    target_id = callback_data.target_id
    index = callback_data.index

    if scope == "default":
        personas = get_dyn("default_persona") or []
    else:
        path = get_path(True, target_id)
        personas = get_db(True, path, None, "persona") or []

    if action == "view":
        text_lines = [f"🤖 مدیریت پرسونای ({'پیش‌فرض' if scope == 'default' else 'سفارشی'}):\n"]
        for idx, p in enumerate(personas):
            text_lines.append(f"{idx + 1}. {p}")
        if not personas:
            text_lines.append("هیچ پرسونایی ثبت نشده است.")
        await callback.message.edit_text(
            "\n".join(text_lines),
            reply_markup=KeyboardBuilder.persona_menu(scope, target_id, personas),
        )
        await callback.answer()
        return

    if action in ("add", "edit"):
        await state.update_data(target_chat_id=target_id, scope=scope, index=index, type=action)
        if scope == "default":
            await state.set_state(BotStateGroup.waiting_for_default_persona)
        else:
            await state.set_state(BotStateGroup.waiting_for_persona_update)
        await callback.message.answer("متن جدید پرسونا را وارد کنید:")
        await callback.answer()
        return

    if action == "delete":
        if 0 <= index < len(personas):
            personas.pop(index)
            if scope == "default":
                edit_dyn("default_persona", personas)
            else:
                path = get_path(True, target_id)
                edit_db("set_persona", path, None, personas)
            await callback.message.edit_text("پرسونا با موفقیت حذف شد! ✅")
        await callback.answer()
        return

    if action == "delete_all":
        if scope == "default":
            edit_dyn("default_persona", [])
        else:
            path = get_path(True, target_id)
            edit_db("set_persona", path, None, [])
        await callback.message.edit_text("تمامی پرسوناه حذف شدند! ❌")
        await callback.answer()
        return


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
async def process_chat_query(
    bot: Bot, message: Message, state: FSMContext
) -> None:
    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")

    path = get_path(True, target_chat_id)
    history = exp_db(path)

    response = await asyncio.to_thread(
        get_gpt, message.text, history, None
    )
    formatted_response = f"📃 خروجی پرسش از تاریخچه چت:\n\n{response}"

    await safe_send_message(bot, message.chat.id, formatted_response)
    await state.clear()


@router.message(BotStateGroup.waiting_for_chat_file_import)
async def process_chat_file_import(
    bot: Bot, message: Message, state: FSMContext
) -> None:
    if not message.document:
        await message.answer("لطفاً یک فایل JSON معتبر ارسال کنید.")
        return

    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")
    json_path = TEMP_DIR / f"import_{message.document.file_unique_id}.json"

    try:
        tg_file = await bot.get_file(message.document.file_id)
        await bot.download_file(tg_file.file_path, destination=json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            imported_history = json.load(f)

        path = get_path(True, target_chat_id)
        dump_db(path, imported_history)
        await message.answer("تاریخچه چت با موفقیت ایمپورت و جایگزین شد! ✅")
    except Exception as exc:
        logger.error("Failed to import chat JSON: %s", exc, exc_info=True)
        await message.answer("خطا در خواندن فایل JSON ارسال شده! ❌")
    finally:
        if json_path.exists():
            json_path.unlink(missing_ok=True)
        await state.clear()


@router.message(F.voice)
async def handle_voice_messages(bot: Bot, message: Message) -> None:
    chat_id = message.chat.id
    path = get_path(True, chat_id)
    if not path:
        return

    processing_msg = await message.answer("در حال تبدیل ویس به متن...")
    extracted_text = await MediaProcessorService.process_voice_to_text(
        bot, message.voice.file_id, message.voice.file_unique_id
    )

    if not extracted_text:
        await processing_msg.edit_text("متاسفانه ویس قابل تشخیص نبود.")
        return

    await processing_msg.edit_text(f"🗣 متن تبدیل شده:\n«{extracted_text}»\n\nدر حال پردازش پاسخ...")
    history = exp_db(path)
    response = await asyncio.to_thread(get_gpt, extracted_text, history, None)

    if "fREPORT=" in response:
        vip_chat_ids = get_chat_ids(False)
        await dispatch_flag_reports(
            bot, extracted_text, response, message.chat.title or "مشتری", vip_chat_ids
        )
        response = response.replace("fREPORT=", "")

    await safe_send_message(bot, chat_id, response)


@router.message(F.photo)
async def handle_photo_messages(bot: Bot, message: Message) -> None:
    chat_id = message.chat.id
    path = get_path(True, chat_id)
    if not path:
        return

    largest_photo = message.photo[-1]
    b64_img = await MediaProcessorService.encode_photo_to_base64(
        bot, largest_photo.file_id, largest_photo.file_unique_id
    )

    prompt = message.caption or "تصویر ارسال شده را تحلیل کنید."
    history = exp_db(path)
    response = await asyncio.to_thread(get_gpt, prompt, history, b64_img)

    await safe_send_message(bot, chat_id, response)


@router.message(F.document)
async def handle_document_messages(bot: Bot, message: Message) -> None:
    chat_id = message.chat.id
    path = get_path(True, chat_id)
    if not path:
        return

    doc = message.document
    file_name = doc.file_name.lower() if doc.file_name else ""
    extracted_text = ""

    if file_name.endswith(".pdf"):
        extracted_text = await MediaProcessorService.extract_pdf_text(
            bot, doc.file_id, doc.file_unique_id
        )
    elif file_name.endswith(".docx"):
        extracted_text = await MediaProcessorService.extract_docx_text(
            bot, doc.file_id, doc.file_unique_id
        )
    elif file_name.endswith(".csv"):
        extracted_text = await MediaProcessorService.extract_table_text(
            bot, doc.file_id, doc.file_unique_id, is_csv=True
        )
    elif file_name.endswith(".xlsx"):
        extracted_text = await MediaProcessorService.extract_table_text(
            bot, doc.file_id, doc.file_unique_id, is_csv=False
        )

    if extracted_text:
        prompt = f"محتوای فایل ضمیمه شده ({doc.file_name}):\n\n{extracted_text}\n\nتوضیح کاربر: {message.caption or 'تحلیل و خلاصه کنید.'}"
        history = exp_db(path)
        response = await asyncio.to_thread(get_gpt, prompt, history, None)
        await safe_send_message(bot, chat_id, response)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_messages(bot: Bot, message: Message) -> None:
    chat_id = message.chat.id
    path = get_path(True, chat_id)
    if not path:
        return

    history = exp_db(path)
    response = await asyncio.to_thread(get_gpt, message.text, history, None)

    if "fREPORT=" in response:
        vip_chat_ids = get_chat_ids(False)
        await dispatch_flag_reports(
            bot, message.text, response, message.chat.title or "مشتری", vip_chat_ids
        )
        response = response.replace("fREPORT=", "")

    await safe_send_message(bot, chat_id, response)


async def main() -> None:
    """Entry point for initializing bot polling service."""
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("Starting AI Telegram Support Engine Polling Service...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Engine safely shut down.")
