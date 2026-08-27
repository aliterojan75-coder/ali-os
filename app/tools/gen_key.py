"""Generate an ENCRYPTION_KEY for integration credentials.

    python -m app.tools.gen_key

Copy the printed value into the server environment (Render/Koyeb dashboard or
.env locally) as ENCRYPTION_KEY. Never commit it.

⚠️ Changing this key later makes already-stored credentials unreadable — they
would have to be re-entered.
"""
from __future__ import annotations


def main() -> None:
    from app.integrations.crypto import new_key

    key = new_key()
    print()
    print("ENCRYPTION_KEY=" + key)
    print()
    print("این خط را در متغیرهای محیطی سرور بگذار (نه داخل کد، نه در گیت).")
    print("با عوض کردن این کلید، اطلاعات ذخیره‌شده‌ی قبلی قابل خواندن نخواهند بود.")


if __name__ == "__main__":
    main()
