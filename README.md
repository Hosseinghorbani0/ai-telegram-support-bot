
# AI Telegram Support Bot

An advanced Telegram bot for customer support management powered by OpenAI GPT-4o-mini.  
This bot enables **VIP agents** to manage **client chats** with features like persona customization, flag-based reporting, file processing, and chat import/export.

> Developed for **asrino24.com Company** (عصری نو).

---

## Features

- **Dual chat types** – `cli` (customer) and `vip` (agent)  
- **Persona management** – Global default persona + per‑chat custom persona  
- **Flag system** – Automatically report specific keywords (e.g., “I don’t know”) or using `fREPORT=...`  
- **File support** – PDF, DOCX, Excel (CSV/XLSX), images (GPT‑4 Vision), voice messages (STT)  
- **Chat import/export** – Backup and restore chat history as JSON  
- **Query chat history** – Ask GPT questions about a customer’s entire conversation  
- **Agent reply** – VIP agents can answer directly to a client via bot  
- **Automatic attachment forwarding** – Optional flag to forward media to agents  
- **Persian (Farsi) language UI** – Fully localized

---

## Requirements

- Python 3.9+
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- OpenAI API Key (with access to `gpt-4o-mini` and vision)
- FFmpeg (for voice message conversion)

### Python Dependencies

See `requirements.txt`:

```
openai==1.60.2
aiogram==3.17.0
aiohttp==3.11.11
asyncio==3.4.3
speechrecognition==3.8.1
PyPDF2==3.0.1
python-docx==1.1.2
pandas==2.2.3
openpyxl==3.1.5
ffmpeg-python==0.2.0
```

---

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-username/ai-telegram-support-bot.git
   cd ai-telegram-support-bot
   ```

2. **Create a virtual environment (optional but recommended)**
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   venv\Scripts\activate      # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install FFmpeg**  
   - Windows: download from [ffmpeg.org](https://ffmpeg.org/) and add to PATH  
   - Linux: `sudo apt install ffmpeg`  
   - Mac: `brew install ffmpeg`

5. **Configuration**  
   **IMPORTANT:** Never hardcode secrets. Use environment variables or `.env` file.

   Create a `.env` file in the project root:
   ```ini
   TOKEN=your_telegram_bot_token
   OPENAI_API_KEY=your_openai_api_key
   PASS=a_strong_password_for_vip_registration
   ```

   Then modify `config.py` to load from environment:
   ```python
   import os
   from dotenv import load_dotenv
   load_dotenv()

   TOKEN = os.getenv("TOKEN")
   OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
   PASS = os.getenv("PASS")
   ```

6. **Run the bot**
   ```bash
   python _main_.py
   ```

---

## Usage

### Register a chat

- **For customers (`cli`)**:  
  Send `/reg` → enter the global `PASS` → choose `ثبت چت (مشتری)`

- **For agents (`vip`)**:  
  Same `/reg`, choose `ثبت چت (پرسنل)`

### Agent panel (`/panel`)

After registering as VIP, `/panel` opens a control panel:

- Delete current VIP chat  
- List all registered chats (both types)  
- Manage global default persona  
- Manage client chats (select a client to open its management panel)

### Client management panel

From a client’s panel you can:

- Delete that client’s chat  
- List available flags  
- Toggle flags:  
  - **pr_flg1** – automatically report when GPT says “I don’t know” (Persian variations)  
  - **pr_flg2** – forward all attachments (images, files, voice) from that client to selected agents  
- Manage per‑client persona (overwrites default)  
- Export/import chat (JSON)  
- Query the bot about that client’s conversation history  
- Send a direct answer as the bot (agent replies to client)

### Flags (auto‑reporting)

- `fREPORT=<chat_id>` – if GPT includes this at the end of its answer, the prompt + answer is sent to that specific chat ID.  
- `fREPORT=ALL` – sends to all registered VIP chats.  
- The bot also automatically triggers report when GPT says certain Persian phrases meaning “I don’t know” (if `pr_flg1` is enabled for that client).

### Persona

Personas are system messages that shape GPT’s behavior.  
- **Default persona** – applied to all clients (can be multiple lines/dimensions).  
- **Per‑client persona** – appended after the default.  
You can add, edit, or delete persona dimensions via the panel.

---

## Project Structure

```
.
├── _main_.py            # Main bot logic
├── config.py            # Configuration (use .env in production)
├── db_client.py         # JSON-based database handler
├── gpt_client.py        # OpenAI API wrapper
├── requirements.txt     # Dependencies
├── README.md            # This file
├── README_fa.md         # Persian version
├── db/                  # Created at runtime
│   ├── vip/             # VIP chat databases
│   ├── cli/             # Client chat databases
│   └── dyn_config.json  # Dynamic settings (flags, default persona)
└── temp/                # Temporary files (voice, images, docs)
```

---

## Security Notes

- **Never commit** your `.env` or `config.py` with real secrets.  
- Add `temp/`, `db/`, `*.pyc`, `.env` to `.gitignore`.  
- Change the default `PASS` to a strong password.  
- Consider using a whitelist of Telegram user IDs for VIP registration instead of a shared password.

---

## License

MIT License – free to use, modify, and distribute with attribution.

---

## Author

Developed by [hosseinghorbani0](https://github.com/hosseinghorbani0) for **[asreno] (https://asrino24.com/) Company** (عصری نو).  
2024–2025
