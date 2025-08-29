import os, tempfile, time
from collections import defaultdict
from dotenv import load_dotenv
import telebot
from telebot import apihelper

# ========= Robust connection settings =========
apihelper.RETRY_ON_ERROR = True
apihelper.EXCEPTION_SLEEP = 3        # pause between automatic retries
apihelper.SESSION_TIME_TO_LIVE = 300
apihelper.CONNECT_TIMEOUT = 15
apihelper.READ_TIMEOUT = 90

# ========= Provider selection =========
# PROVIDER=openai (default) or groq
load_dotenv()
PROVIDER = os.getenv("PROVIDER", "openai").lower()

if PROVIDER == "groq":
    from groq import Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    if not GROQ_API_KEY:
        raise RuntimeError("Set GROQ_API_KEY in .env when PROVIDER=groq")
    llm_client = Groq(api_key=GROQ_API_KEY)
    TRANSCRIBE_MODEL = "whisper-large-v3"
    CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "llama-3.1-8b-instant")
else:
    from openai import OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY:
        raise RuntimeError("Set OPENAI_API_KEY in .env (or PROVIDER=groq with GROQ_API_KEY)")
    llm_client = OpenAI(api_key=OPENAI_API_KEY)
    TRANSCRIBE_MODEL = "whisper-1"
    CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

# ========= Telegram =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "pl").lower()
DEFAULT_TONE = os.getenv("DEFAULT_TONE", "formal").lower()
if not BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# per-chat settings
settings = defaultdict(lambda: {"lang": DEFAULT_LANG, "tone": DEFAULT_TONE})

HELP = (
    "🎙️ *Voice→Email Bot*\n"
    "Надішли voice/audio або текст — згенерую лист (Subject + тіло).\n\n"
    "*Команди:*\n"
    "• /lang pl|en|ua — мова листа\n"
    "• /tone formal|friendly|firm — тон\n"
    "• /start — довідка\n"
    "_Приклад:_ /lang pl, /tone friendly\n\n"
    f"_Provider_: {PROVIDER.upper()}"
)

def chunk(text: str, size: int = 3800):
    return [text[i:i+size] for i in range(0, len(text), size)]

def write_email_from_text(text: str, lang: str, tone: str) -> str:
    system = (
        "You write concise professional emails. "
        "Output strictly in this format:\n"
        "Subject: <short subject>\n\n<body>\n"
        "No extra notes."
    )
    user = (
        f"Language: {lang}. Tone: {tone}. "
        "Draft a short, clear, polite email based on this input:\n---\n"
        f"{text}\n---"
    )
    if PROVIDER == "groq":
        resp = llm_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role":"system","content":system},
                      {"role":"user","content":user}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    else:
        resp = llm_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role":"system","content":system},
                      {"role":"user","content":user}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()

def transcribe(local_path: str) -> str:
    with open(local_path, "rb") as f:
        if PROVIDER == "groq":
            tr = llm_client.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=f)
        else:
            tr = llm_client.audio.transcriptions.create(model=TRANSCRIBE_MODEL, file=f)
    return tr.text.strip()

@bot.message_handler(commands=['start'])
def cmd_start(message):
    st = settings[message.chat.id]
    bot.reply_to(message, f"{HELP}\n\nПоточні: lang={st['lang']}, tone={st['tone']}")

@bot.message_handler(commands=['lang'])
def cmd_lang(message):
    args = message.text.split()
    if len(args) < 2 or args[1].lower() not in ("pl","en","ua"):
        bot.reply_to(message, "Використай: /lang pl|en|ua")
        return
    lang = args[1].lower()
    settings[message.chat.id]["lang"] = lang
    bot.reply_to(message, f"✅ Language set to {lang.upper()}")

@bot.message_handler(commands=['tone'])
def cmd_tone(message):
    args = message.text.split()
    if len(args) < 2 or args[1].lower() not in ("formal","friendly","firm"):
        bot.reply_to(message, "Використай: /tone formal|friendly|firm")
        return
    tone = args[1].lower()
    settings[message.chat.id]["tone"] = tone
    bot.reply_to(message, f"✅ Tone set to {tone}")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    st = settings[message.chat.id]
    try:
        email = write_email_from_text(message.text, st["lang"], st["tone"])
        for part in chunk(email):
            bot.reply_to(message, part)
    except Exception as e:
        msg = str(e)
        if "insufficient_quota" in msg or "429" in msg:
            bot.reply_to(message, "❌ Ключ перевищив ліміт/квоту. Додай баланс або переключись на GROQ:\n"
                                  "1) Отримай GROQ_API_KEY\n2) У .env постав PROVIDER=groq і GROQ_API_KEY=...\n3) Перезапусти бот.")
        else:
            bot.reply_to(message, f"❌ Error: {e}")

def download_file(file_id) -> str:
    file_info = bot.get_file(file_id)
    data = bot.download_file(file_info.file_path)
    suffix = ".oga"
    if "." in file_info.file_path:
        suffix = "." + file_info.file_path.rsplit(".", 1)[-1]
    import tempfile
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path

@bot.message_handler(content_types=['voice', 'audio', 'document'])
def handle_audio(message):
    st = settings[message.chat.id]
    file_id = None
    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id
    elif message.document:
        mime = (message.document.mime_type or "").lower()
        if not (mime.startswith("audio/") or mime in ("application/ogg", "video/mp4")):
            bot.reply_to(message, "⚠️ Надішли аудіо/voice (mp3/m4a/ogg/opus).")
            return
        file_id = message.document.file_id
    if not file_id:
        return

    try:
        local_path = download_file(file_id)
        transcript = transcribe(local_path)
        email = write_email_from_text(transcript, st["lang"], st["tone"])
        out = f"📝 *Transcript:*\n{transcript}\n\n{email}"
        for part in chunk(out):
            bot.reply_to(message, part)
    except Exception as e:
        msg = str(e)
        if "insufficient_quota" in msg or "429" in msg:
            bot.reply_to(message, "❌ Ключ перевищив ліміт/квоту. Додай баланс або переключись на GROQ (див. /start).")
        else:
            bot.reply_to(message, f"❌ Error: {e}")
    finally:
        try: os.remove(local_path)
        except Exception: pass

if __name__ == "__main__":
    print(f"Bot starting… Provider={PROVIDER.upper()}")
    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=25,
                long_polling_timeout=60
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[polling error] {e}")
            time.sleep(3)
