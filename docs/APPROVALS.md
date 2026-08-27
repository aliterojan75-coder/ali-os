# Approval System (§19) — راهنمای توسعه‌دهنده

سیستم تأیید سه‌سطحی Ali OS. **هیچ Agentی حق ندارد عملیات دارای side effect را
مستقیم اجرا کند** — همه چیز از `request_action()` رد می‌شود.

## سه سطح ریسک

| سطح | معنی | تأیید لازم | TTL | مثال |
|-----|------|-----------|-----|------|
| 🟢 green | برگشت‌پذیر، بدون هزینه و بدون اثر بیرونی | ۰ (مستقیم اجرا) | ۱۵ دقیقه | `task.create`, `memory.add` |
| 🟡 yellow | تغییر واقعی یا اثر بیرونی | ۱ تأیید | ۲۴ ساعت | `wordpress.create_draft`, `budget.add_line` |
| 🔴 red | برگشت‌ناپذیر / پرهزینه / عمومی | ۲ تأیید (دو مرحله‌ای) | ۲ ساعت | `wordpress.publish`, `payment.execute` |

سطح ریسک در `app/approvals/risk.py` تعریف می‌شود، نه در Agent. اگر `action_type`
در جدول سیاست نباشد، heuristic کلیدواژه‌ای اعمال می‌شود و **در بدترین حالت 🟡** برمی‌گردد —
یعنی یک اکشن ناشناخته هرگز خودکار اجرا نمی‌شود.

## افزودن یک عملیات جدید

۱. سطح ریسکش را در `ACTION_RISK` بنویس:

```python
# app/approvals/risk.py
ACTION_RISK = {
    ...
    "wordpress.publish": RED,
}
```

۲. اجراکننده‌اش را ثبت کن (فقط بعد از تأیید صدا زده می‌شود):

```python
# app/approvals/actions.py  (یا هر ماژول Agent)
from app.approvals.registry import executor

@executor("wordpress.publish")
def _publish(payload: dict, ctx: dict) -> str:
    post_id = payload["post_id"]
    ...
    return f"مقاله {post_id} منتشر شد"   # این متن در کارت تأیید نمایش داده می‌شود
```

۳. از داخل Agent درخواست بده:

```python
from app import approvals

res = approvals.request_action(
    action_type="wordpress.publish",
    title="انتشار مقاله «گلاب را با چی بخوریم؟»",
    summary="روی سایت گیاهکده",
    payload={"post_id": 12},
    requested_by=user_id,
    project_id=project_id,
    chat_id=chat_id,      # بدون این، کارت تأیید فرستاده نمی‌شود
)
if res.executed:
    ...   # 🟢 بود و همان‌جا اجرا شد
else:
    ...   # 🟡/🔴 — کارت تأیید در تلگرام رفت
```

> اگر برای یک `action_type` اجراکننده ثبت نشده باشد، تأیید کاربر باعث crash نمی‌شود؛
> رکورد با وضعیت `failed` و پیام روشن ثبت می‌شود.

## چرخه‌ی وضعیت

```
                 🟢
request_action ──────────────────────────────► executed
      │
      │ 🟡/🔴
      ▼
   pending ──[✅]──► (🔴: confirming ──[✅]──►) approved ──► executed
      │                                                  └──► failed
      ├──[❌]──► rejected
      └──TTL──► expired
```

## جریان تلگرام

```
Agent → request_action() → sendMessage + inline_keyboard [✅ تأیید][❌ لغو]
Ali فشار می‌دهد → callback_query → /webhook → approvals.handle_callback()
   → answerCallbackQuery (توست)
   → editMessageText (کارت قفل و نتیجه ثبت می‌شود)
```

`callback_data` قالب `ap:<kind>:<action_uid>` دارد و زیر محدودیت ۶۴ بایتی تلگرام می‌ماند.
`kind` یکی از `ok` (تأیید)، `ok2` (تأیید نهایی 🔴)، `no` (لغو) است.

## محافظت‌های امنیتی

- فقط **درخواست‌دهنده** می‌تواند تصمیم بگیرد (`_load_open` بررسی می‌کند).
- تصمیم تکراری رد می‌شود — دکمه‌ی کهنه دوباره اجرا نمی‌کند.
- انقضا هم موقع فشار دادن دکمه و هم با `repo.expire_stale_actions()` بررسی می‌شود.
- خطای اجراکننده در ستون `error` ثبت و در کارت نمایش داده می‌شود؛ webhook هرگز ۵۰۰ نمی‌دهد.
- اگر تلگرام در لحظه‌ی پاسخ down باشد، تصمیمِ ثبت‌شده در دیتابیس برنمی‌گردد.
- همه‌چیز در `events` لاگ می‌شود: `approval_requested`, `approval_step`,
  `approval_rejected`, `action_executed`.

## API (Mini App)

| متد | مسیر | کار |
|-----|------|-----|
| GET | `/api/approvals` | صف تأیید (`?all=1` برای تاریخچه) |
| POST | `/api/approvals/<uid>/approve` | تأیید (برای 🔴 دو بار) |
| POST | `/api/approvals/<uid>/reject` | لغو |
| GET | `/api/projects/<slug>/dossier` | پرونده‌ی کامل پروژه |
| POST | `/api/projects/<slug>/kpis` \| `/people` \| `/budget` | افزودن به پرونده |

## تست

```bash
python -m pytest tests -q     # ۲۴ تست، بدون شبکه و بدون تلگرام واقعی
```
