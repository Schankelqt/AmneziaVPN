import hashlib
import hmac
import time
from typing import Any


def verify_telegram_login_widget(
    auth_data: dict[str, Any],
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
) -> bool:
    if not bot_token:
        return False
    data = {str(k): v for k, v in auth_data.items() if str(k) != "hash"}
    check_hash = auth_data.get("hash")
    if check_hash is None:
        return False
    check_hash = str(check_hash)

    try:
        auth_date = int(str(data.get("auth_date", 0)))
    except (TypeError, ValueError):
        return False
    if auth_date <= 0 or (int(time.time()) - auth_date) > max_age_seconds:
        return False

    parts = []
    for key in sorted(data.keys()):
        value = data[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    data_check_string = "\n".join(parts)

    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed_hash, check_hash)
