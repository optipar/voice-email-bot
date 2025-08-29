**Live bot:** https://t.me/vvoice_email_bot

Надішли voice/audio або текст — отримаєш готовий лист (Subject + тіло) польською/англійською/українською.  
Працює з **OpenAI**

## Команди
`/start` — довідка  
`/lang pl|en|ua` — мова листа  
`/tone formal|friendly|firm` — тон

## Швидкий старт (локально)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заповни токени
python app.py
