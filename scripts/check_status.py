"""
Reports the real processing/content status for every submitted laptop -
`offer-mappings` (plain GET) does NOT reliably show this; `offer-cards`
(getOfferCardsContentStatus) is the endpoint that actually surfaces
cardStatus, contentRating (0-100), and real validation errors. A response of
{"status":"OK"} on submit does not mean an offer is live - always check here
after pushing, and expect several minutes of NO_CARD_PROCESSING /
HAS_CARD_CAN_UPDATE_PROCESSING before it settles on a bulk batch.

Usage: python3 check_status.py
"""
import json, subprocess, collections, os
from build_offers import load_env, _SCRIPT_DIR

env = load_env()
token = env.get('YANDEX_MARKET_API_KEY')
business_id = env.get('YANDEX_MARKET_BUSINESS_ID')
if not (token and business_id):
    raise SystemExit("Set YANDEX_MARKET_API_KEY and YANDEX_MARKET_BUSINESS_ID in ../.env first.")

out = subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"https://api.partner.market.yandex.ru/v2/businesses/{business_id}/offer-cards?limit=100",
     "-H", f"Api-Key: {token}", "-H", "Content-Type: application/json", "-d", "{}"],
    capture_output=True, text=True, timeout=30,
)
cards = json.loads(out.stdout)['result']['offerCards']
print(f"total cards: {len(cards)}")
print("statuses:", collections.Counter(c.get('cardStatus') for c in cards))
ratings = [c['contentRating'] for c in cards if c.get('contentRating') is not None]
if ratings:
    print(f"ratings: min={min(ratings)} max={max(ratings)} avg={sum(ratings)/len(ratings):.1f} ({len(ratings)} rated)")
errs = collections.Counter()
for c in cards:
    for e in (c.get('errors') or []):
        errs[e['message']] += 1
print("error messages:", dict(errs) if errs else "none")
below90 = [(c['offerId'], c['contentRating']) for c in cards if c.get('contentRating') is not None and c['contentRating'] < 90]
if below90:
    print("below 90:", below90)
