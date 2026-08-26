"""
Notifies the staff Telegram group about new Yandex Market (DBS) orders that
need action. Yandex auto-cancels a DBS order (substatus SHOP_FAILED) if the
seller doesn't respond in time, so getting this in front of staff fast is
the whole point - this isn't a nice-to-have digest, it's a "don't lose the
order" alert.

Polls orders with status=PROCESSING (the dashboard's "dbsProcessing" tab),
tracks which order ids have already been notified in ../notified_orders.json
(so a re-run every few minutes doesn't re-send the same order), and sends
one Telegram message per order the first time it's seen - via @noutone_shop_bot,
the same bot that already sends consult/lead notifications from the Mini App
and website, into the same staff group.

Usage:
  python3 notify_new_orders.py            # check and send
  python3 notify_new_orders.py --dry-run  # print what would be sent, don't send or save state
"""
import json, subprocess, os, sys
from build_offers import load_env, _SCRIPT_DIR

STATE_PATH = os.path.join(_SCRIPT_DIR, '..', 'notified_orders.json')
DASHBOARD_URL = "https://partner.market.yandex.uz/business/216979546/orders?campaignId=149239236&tabId=dbsProcessing&tabGroupId=dbs"


def load_state():
    if os.path.exists(STATE_PATH):
        return set(json.load(open(STATE_PATH, encoding='utf-8')))
    return set()


def save_state(ids):
    json.dump(sorted(ids), open(STATE_PATH, 'w', encoding='utf-8'), indent=2)


def fetch_processing_orders(token, campaign_id):
    out = subprocess.run(
        ["curl", "-s", f"https://api.partner.market.yandex.ru/campaigns/{campaign_id}/orders?status=PROCESSING&pageSize=50",
         "-H", f"Api-Key: {token}"],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(out.stdout)
    if 'orders' not in data:
        raise SystemExit(f"Unexpected Yandex API response: {out.stdout[:500]}")
    return data['orders']


def format_message(order):
    items = order.get('items', [])
    item_lines = "\n".join(f"• {i['offerName']} x{i['count']} — {i['price']:,.0f} so'm" for i in items)

    buyer = order.get('buyer', {})
    buyer_name = f"{buyer.get('firstName', '')} {buyer.get('lastName', '')}".strip() or "—"
    phone = buyer.get('phone') or "—"

    address = order.get('delivery', {}).get('address', {})
    addr_str = ", ".join(filter(None, [address.get('city'), address.get('street'), address.get('house')])) or "—"

    notes = order.get('notes')

    lines = [
        "🛒 <b>Yangi Yandex Market buyurtma</b>",
        "",
        f"Buyurtma ID: <code>{order['id']}</code>",
        item_lines,
        "",
        f"👤 {buyer_name}",
        f"📞 {phone}",
        f"📍 {addr_str}",
    ]
    if notes:
        lines.append(f"📝 {notes}")
    lines += [
        "",
        f"💰 Jami: {order.get('buyerTotal', 0):,.0f} so'm",
        "",
        "⚠️ Yandex belgilangan vaqt ichida javob bo'lmasa buyurtmani avtomatik bekor qiladi — tezroq javob bering.",
        DASHBOARD_URL,
    ]
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


def main():
    dry_run = '--dry-run' in sys.argv

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

    notified = load_state()
    orders = fetch_processing_orders(token, campaign_id)

    new_count = 0
    for order in orders:
        oid = str(order['id'])
        if oid in notified:
            continue
        message = format_message(order)
        if dry_run:
            print(f"--- would notify order {oid} ---\n{message}\n")
        else:
            send_telegram(bot_token, chat_id, message)
            notified.add(oid)
        new_count += 1

    if new_count and not dry_run:
        save_state(notified)

    print(f"checked {len(orders)} processing order(s), {'would notify' if dry_run else 'notified'} {new_count} new")


if __name__ == '__main__':
    main()
