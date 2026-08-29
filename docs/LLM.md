# LLM Provider — Groq primary + Gemini fallback

Ali OS از یک آداپتور عمومی `OpenAICompatibleProvider` استفاده می‌کند. یعنی هر سرویس
سازگار با مسیر OpenAI Chat Completions با همین سه env قابل تعویض است.

## تنظیم Render

در `render.yaml` مدل اصلی همان Groq نگه داشته شده و Gemini به‌عنوان fallback/مدل دوم اضافه شده است:

```yaml
LLM_BASE_URL: https://api.groq.com/openai/v1
LLM_MODEL: openai/gpt-oss-120b
LLM_API_KEY: sync:false

LLM_BASE_URL_FALLBACK: https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL_FALLBACK: gemini-3.7-flash
LLM_API_KEY_FALLBACK: sync:false
```

هر دو کلید را فقط در داشبورد Render وارد کن؛ هیچ‌وقت در کد، README، لاگ یا PR paste نکن.

مدل fallback بر اساس مستند رسمی OpenAI compatibility گوگل انتخاب شده است؛ اگر Google
بعداً نام مدل‌های Flash را تغییر داد، فقط `LLM_MODEL_FALLBACK` را در env عوض کن.

## تست سریع در Render Shell

بعد از deploy و ست‌کردن کلیدها، برای تست مدل اصلی این دستور باید یک JSON با `content` فارسی برگرداند:

```bash
curl "$LLM_BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -d "$(python - <<'PY'
import json, os
print(json.dumps({
    "model": os.environ["LLM_MODEL"],
    "messages": [
        {"role": "system", "content": "You are a concise Persian assistant."},
        {"role": "user", "content": "فقط بگو: سلام، اتصال Gemini سبز است."},
    ],
    "temperature": 0,
    "max_tokens": 40,
}, ensure_ascii=False))
PY
)"
```

نشانه‌ی سبز:

- HTTP 200
- بدنه‌ی JSON شامل `choices[0].message.content`
- متن فارسی شبیه «سلام، اتصال Gemini سبز است.»

## تست Gemini fallback در Render Shell

برای تست مستقیم Gemini به‌عنوان مدل دوم:

```bash
curl "$LLM_BASE_URL_FALLBACK/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LLM_API_KEY_FALLBACK" \
  -d "$(python - <<'PY'
import json, os
print(json.dumps({
    "model": os.environ["LLM_MODEL_FALLBACK"],
    "messages": [{"role": "user", "content": "فقط بگو: سلام، اتصال Gemini fallback سبز است."}],
    "temperature": 0,
    "max_tokens": 40,
}, ensure_ascii=False))
PY
)"
```

## تست structured output واقعی

اگر خواستی تست pytest زنده هم اجرا شود:

```bash
RUN_LIVE_LLM=1 \
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai \
LLM_MODEL=gemini-3.7-flash \
LLM_API_KEY="$LLM_API_KEY_FALLBACK" \
python -m pytest tests/test_llm_gemini_live.py -q
```

این تست بدون `RUN_LIVE_LLM=1` و کلید واقعی skip می‌شود تا CI و ریپو به secret وابسته نشوند.

## تاب‌آوری خطا

آداپتور برای پاسخ‌های موقت یا محدودکننده مثل 403، 404، 429 و HTML/Cloudflare challenge
یک بار اولیه + سه retry با backoffهای ۳، ۸ و ۱۵ ثانیه انجام می‌دهد. اگر
`LLM_BASE_URL_FALLBACK` یا `LLM_MODEL_FALLBACK` ست شده باشد، بعد از شکست provider اصلی
همان retryها را روی fallback اجرا می‌کند.

اگر در نهایت LLM کاملاً fail شود، چت تلگرام crash نمی‌کند؛ پیام فارسی می‌دهد که مدل
موقتاً در دسترس نیست و دستورهای داده‌محور مثل `/tasks`، `/crm`، `/finance`،
`/morning`، `/business`، `/sales` و `/notify` همچنان بدون مدل کار می‌کنند.
