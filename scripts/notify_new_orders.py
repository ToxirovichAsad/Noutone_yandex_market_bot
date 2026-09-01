"""
Notifies the staff Telegram group about Yandex Market (DBS) orders that need
action or attention - both new orders sitting in PROCESSING, and orders that
have since been CANCELLED (with the reason), so a decline is never silent.

Originally polled status=PROCESSING only and only ever sent a "new order"
message. That missed orders cancelled fast: order 61086716033 was created
and CANCELLED (substatus USER_REFUSED_DELIVERY) under 2 minutes later; order
61079158019 similarly (USER_BOUGHT_CHEAPER, ~71 seconds). A 10-minute poll
against PROCESSING-only can't ever catch those - by the time it runs, the
order has already left PROCESSING and drops out of that filter entirely, and
there was no code path for reporting a cancellation anyway. Fetching
PROCESSING+CANCELLED together and tracking each order's last-notified status
(not just "seen or not") fixes both: a short-lived order is reported once,
already showing CANCELLED and why; a longer-lived one gets the original "new
order" ping, then a follow-up when it's cancelled later.

Yandex still auto-cancels a DBS order (substatus SHOP_FAILED) if the seller
doesn't respond in time, so the "new order" ping is still the main point -
this just adds "and here's what happened to it" as a second guarantee.

Also sends a daily heartbeat and a Telegram alert on any real failure
(bad API response, network error, etc.) - a notifier that only ever speaks
when there's an order is indistinguishable, from the staff side, from one
that's silently broken. Asadbek asked for exactly this: "I don't know
whether it is working or not unless someone creates an order."

Usage:
  python3 notify_new_orders.py            # check and send
  python3 notify_new_orders.py --dry-run  # print what would be sent, don't send, save nothing
"""
import json, subprocess, os, sys, traceback
from datetime import datetime, timezone
from build_offers import load_env, _SCRIPT_DIR

YANDEX_DATE_FORMAT = "%d-%m-%Y %H:%M:%S"
# Reserved key in the same state dict as order ids - order ids from Yandex
# are always numeric strings, so this can never collide with a real one.
HEARTBEAT_KEY = "__last_heartbeat_date__"

STATE_PATH = os.path.join(_SCRIPT_DIR, '..', 'notified_orders.json')
DASHBOARD_URL = "https://partner.market.yandex.uz/business/216979546/orders?campaignId=149239236&tabId=dbsProcessing&tabGroupId=dbs"

# Cancellation reasons actually seen, translated for the staff message.
# Anything not listed here still gets reported - just with the raw Yandex
# code instead of a translated label - so a new/rare substatus never
# silently vanishes from the notification.
CANCEL_REASONS = {
    "USER_REFUSED_DELIVERY": "Xaridor yetkazib berish/olib ketishdan voz kechdi",
    "USER_REFUSED_PRODUCT": "Xaridor mahsulotdan voz kechdi",
    "USER_REFUSED_QUALITY": "Xaridor mahsulot sifatidan norozi bo'ldi",
    "USER_CHANGED_MIND": "Xaridor fikridan qaytdi",
    "USER_UNREACHABLE": "Xaridor bilan bog'lanib bo'lmadi",
    "USER_BOUGHT_CHEAPER": "Xaridor arzonroq narxda boshqa joydan oldi",
    "SHOP_FAILED": "Do'kon belgilangan vaqtda javob bermadi (avtomatik bekor qilindi)",
    "OUT_OF_DATE": "Buyurtma muddati tugadi",
    "REPLACING_ORDER": "Buyurtma boshqasi bilan almashtirildi",
}


def load_state():
    """
    {order_id: last_notified_status} - upgraded from a flat "seen" list so a
    status change (PROCESSING -> CANCELLED) can be detected and reported,
    not just the order's first appearance. Transparently upgrades the old
    flat-list format (every id treated as already-fully-handled) so a
    re-run right after this change doesn't re-notify every historical order.
    """
    if not os.path.exists(STATE_PATH):
        return {}
    data = json.load(open(STATE_PATH, encoding='utf-8'))
    if isinstance(data, list):
        return {oid: 'CANCELLED' for oid in data}
    return data


def save_state(state):
    json.dump(state, open(STATE_PATH, 'w', encoding='utf-8'), indent=2, sort_keys=True, ensure_ascii=False)


def fetch_orders(token, campaign_id):
    out = subprocess.run(
        ["curl", "-s", f"https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders"
                        f"?status=PROCESSING,CANCELLED&pageSize=50",
         "-H", f"Api-Key: {token}"],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(out.stdout)
    if 'orders' not in data:
        raise SystemExit(f"Unexpected Yandex API response: {out.stdout[:500]}")
    return data['orders']


def format_elapsed(created_str, updated_str):
    """'2 daqiqa', '10 soat 37 daqiqa' - or None if either timestamp is
    missing/unparseable, in which case the caller falls back to not
    claiming a duration at all rather than showing a wrong one."""
    if not created_str or not updated_str:
        return None
    try:
        created = datetime.strptime(created_str, YANDEX_DATE_FORMAT)
        updated = datetime.strptime(updated_str, YANDEX_DATE_FORMAT)
    except ValueError:
        return None
    total_minutes = max(0, int((updated - created).total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0:
        return f"{minutes} daqiqa" if minutes else "1 daqiqadan kam"
    return f"{hours} soat {minutes} daqiqa" if minutes else f"{hours} soat"


def order_summary_lines(order):
    items = order.get('items', [])
    item_lines = "\n".join(f"• {i['offerName']} x{i['count']} — {i['price']:,.0f} so'm" for i in items)

    buyer = order.get('buyer', {})
    buyer_name = f"{buyer.get('firstName', '')} {buyer.get('lastName', '')}".strip() or "—"
    phone = buyer.get('phone') or "—"

    address = order.get('delivery', {}).get('address', {})
    addr_str = ", ".join(filter(None, [address.get('city'), address.get('street'), address.get('house')])) or "—"

    lines = [
        f"Buyurtma ID: <code>{order['id']}</code>",
        item_lines,
        "",
        f"👤 {buyer_name}",
        f"📞 {phone}",
        f"📍 {addr_str}",
    ]
    notes = order.get('notes')
    if notes:
        lines.append(f"📝 {notes}")
    lines.append(f"💰 Jami: {order.get('buyerTotal', 0):,.0f} so'm")
    return lines


def format_new_order_message(order):
    lines = ["🛒 <b>Yangi Yandex Market buyurtma</b>", ""]
    lines += order_summary_lines(order)
    lines += [
        "",
        "⚠️ Yandex belgilangan vaqt ichida javob bo'lmasa buyurtmani avtomatik bekor qiladi — tezroq javob bering.",
        DASHBOARD_URL,
    ]
    return "\n".join(lines)


def format_cancelled_message(order, *, already_cancelled_on_first_sight):
    substatus = order.get('substatus') or ''
    reason = CANCEL_REASONS.get(substatus, substatus or "Sabab ko'rsatilmagan")

    if already_cancelled_on_first_sight:
        # We never saw this order while it was still PROCESSING - it was
        # created and cancelled inside one polling gap. Say so explicitly so
        # staff don't wonder why there was no earlier "new order" ping. Show
        # the actual elapsed time rather than asserting it was fast - this
        # message also fires for old orders that sat for hours before being
        # auto-cancelled (never caught because this script didn't exist
        # yet), where "cancelled instantly" would be misleading.
        header = "⚠️ <b>Buyurtma yaratilib, keyin bekor qilingan</b>"
        elapsed = format_elapsed(order.get('creationDate'), order.get('updatedAt'))
        note = (
            f"Bu buyurtma {elapsed} ichida bekor qilingani uchun \"yangi buyurtma\" xabari yuborilmagan edi."
            if elapsed
            else "Bu buyurtma \"yangi buyurtma\" bosqichida ko'rinmay, to'g'ridan-to'g'ri bekor qilingan holda topildi."
        )
    else:
        header = "❌ <b>Yandex Market buyurtma bekor qilindi</b>"
        note = None

    lines = [header, ""]
    lines += order_summary_lines(order)
    lines += ["", f"🚫 Sabab: {reason}"]
    if note:
        lines += ["", note]
    lines.append(DASHBOARD_URL)
    return "\n".join(lines)


def send_telegram(bot_token, chat_id, text):
    out = subprocess.run(
        ["curl", "-s", f"https://api.telegram.org/bot{bot_token}/sendMessage",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"})],
        capture_output=True, text=True, timeout=15,
    )
    result = json.loads(out.stdout) if out.stdout else {}
    if not result.get('ok'):
        raise RuntimeError(f"Telegram sendMessage failed: {out.stdout}")


def maybe_send_heartbeat(state, bot_token, chat_id, active_count, dry_run):
    """
    Once per UTC calendar day: a short "still alive" ping. A notifier that
    only ever speaks when there's an order is indistinguishable, from the
    staff side, from one that's silently broken - this is the difference
    between "no orders today" and "is this thing even running?".
    Returns True if a heartbeat was (or, in dry-run, would be) sent.
    """
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if state.get(HEARTBEAT_KEY) == today:
        return False

    text = (
        "✅ <b>Yandex Market bot ishlamoqda</b>\n\n"
        f"Kunlik holat tekshiruvi — {today} (UTC)\n"
        f"Hozir faol (PROCESSING) buyurtmalar: {active_count}\n\n"
        "Bu xabar botning har 5 daqiqada ishlab turganini tasdiqlash uchun "
        "kuniga bir marta yuboriladi - agar bu xabar kelmasa, bot ishlamayapti demakdir."
    )
    if dry_run:
        print(f"--- would send heartbeat ---\n{text}\n")
    else:
        send_telegram(bot_token, chat_id, text)
        state[HEARTBEAT_KEY] = today
    return True


def send_failure_alert(bot_token, chat_id, exc):
    """
    Best-effort - if this itself fails (network down, bad credentials),
    there's nothing left to do but let the GitHub Actions run show red,
    which is the fallback signal when even the alert can't get out.
    """
    try:
        send_telegram(
            bot_token, chat_id,
            "🔴 <b>Yandex Market bot xatolik bilan to'xtadi</b>\n\n"
            f"<code>{escape_html(f'{type(exc).__name__}: {exc}')}</code>\n\n"
            "Keyingi (5 daqiqadan keyingi) urinish avtomatik bo'ladi. Agar bu "
            "takrorlansa, GitHub Actions loglarini tekshiring.",
        )
    except Exception:
        pass


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run(dry_run):
    env = load_env()
    token = env.get('YANDEX_MARKET_API_KEY')
    campaign_id = env.get('YANDEX_MARKET_CAMPAIGN_ID')
    bot_token = env.get('TELEGRAM_BOT_TOKEN')
    chat_id = env.get('TELEGRAM_STAFF_CHAT_ID')
    if not all([token, campaign_id, bot_token, chat_id]):
        raise SystemExit(
            "Set YANDEX_MARKET_API_KEY, YANDEX_MARKET_CAMPAIGN_ID, TELEGRAM_BOT_TOKEN, "
            "TELEGRAM_STAFF_CHAT_ID in ../.env"
        )

    state = load_state()

    try:
        orders = fetch_orders(token, campaign_id)
    except Exception as exc:
        # The one failure mode staff actually need to know about in real
        # time: the check itself is broken (bad token, Yandex API change,
        # network issue). Everything below this can't run without `orders`,
        # so there's nothing left to do but alert and stop.
        traceback.print_exc()
        if not dry_run:
            send_failure_alert(bot_token, chat_id, exc)
        raise

    sent = 0
    for order in orders:
        oid = str(order['id'])
        status = order['status']
        last_notified = state.get(oid)

        if last_notified is None and status == 'PROCESSING':
            message = format_new_order_message(order)
        elif last_notified is None and status == 'CANCELLED':
            message = format_cancelled_message(order, already_cancelled_on_first_sight=True)
        elif last_notified == 'PROCESSING' and status == 'CANCELLED':
            message = format_cancelled_message(order, already_cancelled_on_first_sight=False)
        else:
            # Already fully reported for its current status (or nothing new
            # to say - e.g. still PROCESSING and we already pinged that).
            continue

        if dry_run:
            print(f"--- would notify order {oid} ({status}) ---\n{message}\n")
        else:
            send_telegram(bot_token, chat_id, message)
            state[oid] = status
        sent += 1

    active_count = sum(1 for o in orders if o['status'] == 'PROCESSING')
    heartbeat_sent = maybe_send_heartbeat(state, bot_token, chat_id, active_count, dry_run)

    if (sent or heartbeat_sent) and not dry_run:
        save_state(state)

    print(
        f"checked {len(orders)} order(s), "
        f"{'would notify' if dry_run else 'notified'} {sent}"
        f"{', heartbeat sent' if heartbeat_sent else ''}"
    )


def main():
    run(dry_run='--dry-run' in sys.argv)


if __name__ == '__main__':
    main()
