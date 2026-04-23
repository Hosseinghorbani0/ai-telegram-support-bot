import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import TOKEN, PASS
from gpt_client import get_gpt
from db_client import *

import speech_recognition as sr 
import PyPDF2
import docx
import base64
import subprocess
import pandas as pd
import os

#init
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
storage = MemoryStorage()

class RegisterState(StatesGroup):
    get_password = State()
    get_persona = State()
    get_default_persona = State()
    get_answer = State()
    get_prompt = State()
    get_file = State()

#functions
def split_message(message, max_length=3500):
    return [message[i:i + max_length] for i in range(0, len(message), max_length)]

async def send_split_message(chat_id, message, reply_markup=None, parse_mode=None):
    for part in split_message(message):
        await bot.send_message(chat_id, part, reply_markup=reply_markup, parse_mode=parse_mode)

def create_keyboard(buttons):
    buttons.append([("بستن پنل", "exit")])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in buttons])

async def load_reg(message: Message):
    reg_keyboard = create_keyboard([
        [("ثبت چت (پرسنل) ✅", "reg_vip"), ("ثبت چت (مشتری)", "reg_cli")]
    ])
    await message.answer("لطفا انتخاب کنید:", reply_markup=reg_keyboard)

async def load_panel(message: Message):
    panel_keyboard = create_keyboard([
        [("حذف این چت ❌", "del_chat_vip"),("لیست چت‌ها 📃", "chat_list")],
        [("پرسونا‌ی پیشفرض", "directsd")],
        [("مدیریت چت های cli 🔗", "manage_cli")],
    ])
    await message.answer("لطفا انتخاب کنید:", reply_markup=panel_keyboard)

async def load_cli_panel(message: Message, chat_id):
    panel_keyboard = create_keyboard([
        [("حذف چت مشتری ❌", f"del_chat_{chat_id}")],
        [("لیست فلگ‌ها 🚩", "flag_list")],
        [("فلگ ریپورت ندانستن (آماده) 💬", f"pr_flg1_{chat_id}")],
        [("فلگ فوروارد پیوست (آماده) ♻️", f"pr_flg2_{chat_id}")],
        [("مدیریت پرسونا 🤖", f"directs_{chat_id}")],
        [("ایمپورت چت 📩", "import_chat"),("اکسپورت چت 📤", f"export_chat_{chat_id}")],
        [("پرسش از چت 🎈", f"get_report_{chat_id}")],
        [("پاسخ از جانت ربات", f"answer_for_{chat_id}")]
    ])
    await message.answer("لطفا انتخاب کنید:", reply_markup=panel_keyboard)

async def load_persona(callback_query: CallbackQuery, chat_id, defualt: bool):
    if defualt:
        current_persona = get_dyn("default_persona")
        pov = "personad"
    else:
        current_persona = get_db(False, get_path(True, chat_id), None, "system")
        pov = "persona"
    persona_keyboard = [
        [("اضافه کردن ➕", f"add_{pov}_{chat_id}")],
        [("ویرایش ابعاد ✏️", f"edit_{pov}_{chat_id}")],
        [("حذف پرسونا ❌", f"reset_{pov}_{chat_id}")]
    ]
    if current_persona:
        response_message = "\n\n".join([f"{index + 1}. {persona}" for index, persona in enumerate(current_persona)])
        response_message = "🤖 پرسونا فعلی:\n\n" + response_message 
    else:
        response_message = "هیچ پرسونایی ثبت نشده است!"
        persona_keyboard = [persona_keyboard[0]]
    persona_keyboard = create_keyboard(persona_keyboard)
    await send_split_message(callback_query.message.chat.id, response_message, reply_markup=persona_keyboard)

#flags
async def report_flg(prompt, response, title, chat_id):
    response.replace(f"fREPORT={chat_id}", "")
    report_txt = f"💬 چت: {title}\n\n🧑 پیام مشتری:\n{prompt}\n\n🤖 پاسخ ربات:\n{response}\n\nفلگ report 🚩"
    await bot.send_message(chat_id, report_txt)

async def report_to_all_flg(prompt, response, title):
    report_txt = f"💬 چت: {title}\n\n🧑 پیام مشتری:\n{prompt}\n\n🤖 پاسخ ربات:\n{response}\n\nفلگ report 🚩"
    vip_chat_ids = get_chat_ids(False)
    for chat_id in vip_chat_ids:
        await bot.send_message(chat_id, report_txt)

async def pr_flagging(callback_query, chat_id, flag_type):
    target_chat_id = callback_query.data.split("_")[2]
    flag_data = get_dyn(flag_type)
    for item in flag_data:
        if target_chat_id == item["src"]:
            if chat_id in item["dest"]:
                item["dest"].remove(chat_id)
                await callback_query.message.answer("فلگ غیرفعال شد! 🚫")
            else:
                item["dest"].append(chat_id)
                await callback_query.message.answer("فلگ فعال شد! ✅")
            break
    else:
        flag_data.append({"src": target_chat_id, "dest": [chat_id]})
        await callback_query.message.answer("فلگ فعال شد! ✅")
    edit_dyn(flag_type, flag_data)

#router
@router.message(Command(commands=["start"]))
async def start_chat(message: Message, state: FSMContext):
    pass

@router.message(Command(commands=["reg"]))
async def reg_chat(message: Message, state: FSMContext):
    if get_path(False, message.chat.id) or get_path(True, message.chat.id):
        await message.answer("این چت قبلا ثبت شده است!")
    else:
        await message.answer("لطفا رمز عبور را وارد کنید:")
        await state.set_state(RegisterState.get_password)

@router.message(Command(commands=["panel"]))
async def panel_chat(message: Message, state: FSMContext):
    if get_path(False, message.chat.id):
        await load_panel(message)
    elif not get_path(True, message.chat.id):
        await message.answer("این چت برای ربات ثبت نشده است!")

@router.message(RegisterState.get_password)
async def process_pre_password(message: Message, state: FSMContext):
    if message.text == PASS:
         await load_reg(message)
    else:
        await message.answer("رمز عبور اشتباه است. لطفا دوباره تلاش کنید.")
    await state.clear()

@router.message(RegisterState.get_persona)
async def process_persona(message: Message, state: FSMContext):
    data = await state.get_data()
    path = get_path(True, data.get("target_chat_id"))
    type = data.get("type")
    target = data.get("target")
    edit_db(type, path, target, message.text)
    await message.answer("پرسونا با موفقیت ویرایش شد! ✅")
    await state.clear()

@router.message(RegisterState.get_default_persona)
async def update_persona_config(message: Message, state: FSMContext):
    data = await state.get_data()
    index = data.get("index")
    default_persona = get_dyn("default_persona")
    if index:
        default_persona[int(index)] = message.text
    else: 
        default_persona.append(message.text)
    edit_dyn("default_persona", default_persona)
    await message.answer("با موفقیت آپدیت شد! ✅")
    await state.clear()

@router.message(RegisterState.get_answer)
async def answer_using_bot(message: Message, state: FSMContext):
    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")
    await bot.copy_message(target_chat_id, message.chat.id, message.message_id)
    await message.answer("با موفقیت ارسال شد! ✅")
    await state.clear()

@router.message(RegisterState.get_prompt)
async def prompt_process(message: Message, state: FSMContext):
    data = await state.get_data()
    path = get_path(True, data.get("target_chat_id"))
    messages = exp_db(path)
    response = f"📃 خروجی پرسش:\n\n{get_gpt(message.text, messages, None)}"
    await send_split_message(message.chat.id, response)
    await state.clear()

@router.message(RegisterState.get_file)
async def file_process(message: Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        await bot.download_file(file_path, f'db/cli/{message.document.file_name}')
    await message.answer("با موفقیت آپدیت شد! ✅")
    await state.clear()

#msg
@router.message()
async def chatgpt_handler(message: Message):
    chat_name = message.chat.title or message.chat.full_name
    if get_path(True, message.chat.id):
        img = None
        prompt = ""
        if message.photo or message.document or message.voice or message.video or message.audio:
            pr_flg2_chats = get_dyn("pr_flg2")
            for item in pr_flg2_chats:
                if str(message.chat.id) == item["src"]:
                    try:
                        for dest_chat_id in item["dest"]:
                            await message.forward(dest_chat_id)
                            await bot.send_message(dest_chat_id, f"📎 اتچمنت ارسال شده از: {chat_name}")
                    except:
                        pass

            if message.voice: #stt
                recognizer = sr.Recognizer()
                voice_file = await bot.get_file(message.voice.file_id)
                voice_path = f"temp/{voice_file.file_id}.ogg"
                wav_path = f"temp/{voice_file.file_id}.wav"
                await bot.download_file(voice_file.file_path, voice_path)
                subprocess.run(['ffmpeg', '-i', voice_path, wav_path], check=True)
                with sr.AudioFile(wav_path) as source:
                    audio = recognizer.record(source)
                prompt = recognizer.recognize_google(audio, language="fa-IR")

            elif message.document:
                file = await bot.get_file(message.document.file_id)
                if message.document.mime_type == "application/pdf":
                    file_path = f"temp/{message.document.file_id}.pdf"
                    await bot.download_file(file.file_path, file_path)
                    with open(file_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        prompt = "\n".join([page.extract_text() for page in reader.pages])
                elif message.document.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    file_path = f"temp/{message.document.file_id}.docx"
                    await bot.download_file(file.file_path, file_path)
                    doc = docx.Document(file_path)
                    prompt = "\n".join([para.text for para in doc.paragraphs])
                elif message.document.mime_type == "text/csv" or message.document.mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                    file_path = f"temp/{message.document.file_id}.csv" if message.document.mime_type == "text/csv" else f"temp/{message.document.file_id}.xlsx"
                    await bot.download_file(file.file_path, file_path)
                    if message.document.mime_type == "text/csv":
                        df = pd.read_csv(file_path)
                    else:
                        df = pd.read_excel(file_path)
                    df_string = df.to_string(index = False)
                    prompt = df_string

            elif message.photo:
                file_id = message.photo[-1].file_id
                file = await bot.get_file(file_id)
                file_path = file.file_path
                await bot.download_file(file_path, f'temp/{file_id}.jpg')
                with open(f'temp/{file_id}.jpg', "rb") as image_file:
                    img = base64.b64encode(image_file.read()).decode('utf-8')
                    prompt = "توضیح بده!"

            if message.caption:
                prompt = message.caption + "\n" + prompt
        else:
            if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
                prompt = message.reply_to_message.text + "\n" + message.text
            else:
                prompt = message.text
                if "docs.google.com/spreadsheets" in prompt:
                    url = "https://docs.google.com/" + prompt.split("docs.google.com/")[1].split("/edit")[0] + "/export?format=csv"
                    replace_url = "https://docs.google.com/" + prompt.split("docs.google.com/")[1].split(" ")[0]
                    prompt = prompt.replace(replace_url, "")
                    df = pd.read_csv(url)
                    df_string = df.to_string(index = False)
                    prompt += df_string
        
        path = get_path(True, message.chat.id)
        messages = exp_db(path)
        if(prompt != ""):
            response = get_gpt(prompt, messages, img)
        
            #flg_call
            if "fREPORT=ALL" in response:
                await report_to_all_flg(prompt, response, chat_name)
            elif "fREPORT=" in response:
                chat_id = response.split("fREPORT=")[1].split()[0]
                await report_flg(prompt, response, chat_name, chat_id)

            pr_flg1_lst = ["اطلاع", "نمیدانم", "نمی‌دانم", "نمی دانم", "نمیدونم", "نمی‌دونم", "نمی دونم"]
            if any(item in response for item in pr_flg1_lst):
                pr_flg1_chats = get_dyn("pr_flg1")
                for item in pr_flg1_chats:
                    if str(message.chat.id) == item["src"]:
                        try:
                            for dest_chat_id in item["dest"]:
                                await report_flg(prompt, response, chat_name, dest_chat_id)
                        except:
                            pass

            #rm_flags
            try:
                rm_val = response.split("REPORT=")[1].split()[0]
                response = response.replace(rm_val, "")
            except:
                pass
            for flag in get_dyn("flgs"):
                response = response.replace(flag, "")
            
            await message.reply(response)
            
            edit_db(False, path, "user", prompt)
            edit_db(False, path, "assistant", response)

            #clean_temps
            temp_files = os.listdir("temp")
            for temp_file in temp_files:
                try:
                    os.remove(os.path.join("temp", temp_file))
                except:
                    pass
        else:
            await message.reply("بررسی می‌کنم، اطلاع میدم!")
    elif get_path(False, message.chat.id):
        await message.answer("چت پرسنل تنها برای کنترل ربات از طریق پنل هست!")
    else:
        await message.answer("این چت برای ربات ثبت نشده است!")

#callback
@router.callback_query()
async def handle_callback_query(callback_query: CallbackQuery, state: FSMContext):
    chat_id = callback_query.message.chat.id
    chat_name = callback_query.message.chat.title or callback_query.message.chat.full_name
    
    delete_query = True

    if callback_query.data == "reg_cli":
        mk_db(True, chat_id, chat_name)
        await callback_query.message.answer("چت مشتری با موفقیت ثبت شد! ✅")
    elif callback_query.data == "reg_vip":
        mk_db(False, chat_id, chat_name)
        await callback_query.message.answer("چت پرسنل با موفقیت ثبت شد! ✅")
    elif "del_chat_" in callback_query.data:
        target_chat_id = callback_query.data.split("del_chat_")[1]
        if target_chat_id == "vip":
            if get_path(False, chat_id):
                rm_db(get_path(False, chat_id))
        else:
            rm_db(get_path(True, target_chat_id))
            for flag_type in ["pr_flg1", "pr_flg2"]:
                flag_data = get_dyn(flag_type)
                flag_data = [item for item in flag_data if str(target_chat_id) != item["src"]]
                edit_dyn(flag_type, flag_data)
        await callback_query.message.answer("چت با موفقیت حذف شد! ✅")
    elif callback_query.data == "chat_list":
        cli_chats = get_chat_names(True)
        vip_chats = get_chat_names(False)
        cli_chats_str = "\n".join([f"{chat_name} (cli)" for chat_name in cli_chats]) if cli_chats else "هیچ چت مشتری ثبت نشده!"
        vip_chats_str = "\n".join([f"{chat_name} (vip)" for chat_name in vip_chats]) if vip_chats else "هیچ چتی برای مدیریت ثبت نشده!"
        response_message = f"💚 چت‌های پرسنل (vip):\n{vip_chats_str}\n\n🔷 چت‌های مشتری (cli):\n{cli_chats_str}"
        await send_split_message(chat_id, response_message)
        delete_query = False
    elif callback_query.data == "flag_list":
        response_message = f"`fREPORT={chat_id}`\nاین فلگ در صورت ران شدن، پیام مشتری را به *این چت* گزارش می‌دهد\\.\n\n`fREPORT=ALL`\nاین فلگ در صورت ران شدن، پیام مخاطب را به *تمامی چت های پرسنل* گزارش می‌دهد\\."
        await callback_query.message.answer(f"🚩 فلگ‌های قابل استفاده:\nبرای استفاده، فلگ را کپی کرده و از طریق پرسوناسازی به ربات یاد دهید آنرا در شرایطی انتهای پیغام خود بگذارد تا این فلگ ران شود\\.\n\n{response_message}", parse_mode="MarkdownV2")
        delete_query = False
    elif  "export_chat" in callback_query.data:
        target_chat_id = callback_query.data.split("export_chat_")[1]
        chat_file_path = get_path(True, target_chat_id)
        chat_file = FSInputFile(chat_file_path)
        await bot.send_document(chat_id, chat_file)
        delete_query = False
    elif  "import_chat" in callback_query.data:
        await callback_query.message.answer("لطفا فایل چت را بفرستین. دقت کنید نام فایل با نام فایل اکسپورت برابر باشد!")
        await state.set_state(RegisterState.get_file)
    
    #slct_cli
    elif "manage_cli" in callback_query.data :
        cli_chats = get_chat_names(True)
        chat_ids = get_chat_ids(True)
        keyboard = create_keyboard([
            [(chat_name, f"slct_{chat_id}")]
            for chat_name, chat_id in zip(cli_chats, chat_ids)
        ])
        if cli_chats:
            await callback_query.message.answer("لطفا چت مشتری مدنظر را انتخاب کنید:", reply_markup=keyboard)
        else:
            await callback_query.message.answer("هیچ چت مشتری برای مدیریت وجود ندارد!")
    elif "slct_" in callback_query.data:
        target_chat_id = callback_query.data.split("slct_")[1]
        await load_cli_panel(callback_query.message, target_chat_id)

    elif "answer_for_" in callback_query.data:
        target_chat_id = callback_query.data.split("answer_for_")[1]
        await callback_query.message.answer("لطفا پیغام را وارد کنید:")
        await state.update_data(target_chat_id=target_chat_id)
        await state.set_state(RegisterState.get_answer)

    elif "directs" in callback_query.data:
        if "directsd" in callback_query.data:
            await load_persona(callback_query, None, True)
        else:
            target_chat_id = callback_query.data.split("directs_")[1]
            await load_persona(callback_query, target_chat_id, False)
        delete_query = False
    elif "add_persona" in callback_query.data:
        if "add_personad" in callback_query.data:
            await state.update_data(index=False)
            await state.set_state(RegisterState.get_default_persona)
        else:
            target_chat_id = callback_query.data.split("add_persona_")[1]
            await state.update_data(target_chat_id=target_chat_id, type=False, target="system")
            await state.set_state(RegisterState.get_persona)
        await callback_query.message.answer("لطفا پرسونای جدید را وارد کنید:")
    elif "reset_persona" in callback_query.data:
        if "reset_personad" in callback_query.data:
            current_persona = get_dyn("default_persona")
            persona_buttons = [[(f"{index + 1}. {persona[:30]}...", f"del_personad_{index}")] for index, persona in enumerate(current_persona)]
            persona_buttons.append([("حذف کل ابعاد", "del_personad_all")])
        else:
            target_chat_id = callback_query.data.split("reset_persona_")[1]
            current_persona = get_db(False, get_path(True, target_chat_id), None, "system")
            persona_buttons = [[(f"{index + 1}. {persona[:30]}...", f"del_persona_{target_chat_id}_{index}")] for index, persona in enumerate(current_persona)]
            persona_buttons.append([("حذف کل ابعاد", f"del_persona_all_{target_chat_id}")])
        persona_keyboard = create_keyboard(persona_buttons)
        await callback_query.message.answer("لطفا ابعاد مدنظر را انتخاب کنید:", reply_markup=persona_keyboard)
    elif "edit_persona" in callback_query.data:
        if "edit_personad" in callback_query.data:
            current_persona = get_dyn("default_persona")
            persona_buttons = [[(f"{index + 1}. {persona[:30]}...", f"cpersonad_{index}")] for index, persona in enumerate(current_persona)]
        else:
            target_chat_id = callback_query.data.split("edit_persona_")[1]
            current_persona = get_db(False, get_path(True, target_chat_id), None, "system")
            persona_buttons = [[(f"{index + 1}. {persona[:30]}...", f"cpersona_{target_chat_id}_{index}")] for index, persona in enumerate(current_persona)]
        persona_keyboard = create_keyboard(persona_buttons)
        await callback_query.message.answer("لطفا ابعاد مدنظر را انتخاب کنید:", reply_markup=persona_keyboard)
    elif "cpersona" in callback_query.data:
        if "cpersonad" in callback_query.data:
            index = callback_query.data.split("_")[1]
            await state.update_data(index=index)
            await state.set_state(RegisterState.get_default_persona)
        else:
            target_chat_id = callback_query.data.split("_")[1]
            index = callback_query.data.split("_")[2]
            current_persona = get_db(False, get_path(True, target_chat_id), None, "system")
            await state.update_data(target_chat_id=target_chat_id, type=True, target=current_persona[int(index)])
            await state.set_state(RegisterState.get_persona)
        await callback_query.message.answer("لطفا پرسونا جدید را وارد کنید:")
    elif "del_persona" in callback_query.data:
        type = callback_query.data.split("_")[2]
        if type == "all":
            if "del_personad" in callback_query.data:
                edit_dyn("default_persona", [])
            else:
                target_chat_id = callback_query.data.split("_")[3]
                dump_db(False, get_path(True, target_chat_id), "system", None)
            await callback_query.message.answer("پرسونا با موفقیت ریست شد! ✅")
        else:
            if "del_personad" in callback_query.data:
                index = callback_query.data.split("_")[2]
                default_persona = get_dyn("default_persona")
                default_persona.pop(int(index))
                edit_dyn("default_persona", default_persona)
            else:
                target_chat_id = callback_query.data.split("_")[2]
                index = callback_query.data.split("_")[3]
                current_persona = get_db(False, get_path(True, target_chat_id), None, "system")
                dump_db(True, get_path(True, target_chat_id), None, current_persona[int(index)])
            await callback_query.message.answer("پرسونا با موفقیت آپدیت شد! ✅")

    elif "get_report_" in callback_query.data:
        target_chat_id = callback_query.data.split("_")[2]
        await callback_query.message.answer("لطفا پرسش از ربات درباره‌ی این چت را وارد کنید:")
        await state.update_data(target_chat_id=target_chat_id)
        await state.set_state(RegisterState.get_prompt)
    
    elif "pr_flg1_" in callback_query.data:
        await pr_flagging(callback_query, chat_id, "pr_flg1")
    elif "pr_flg2_" in callback_query.data:
        await pr_flagging(callback_query, chat_id, "pr_flg2")

    if delete_query:
        await callback_query.message.delete()
    await callback_query.answer()

async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


