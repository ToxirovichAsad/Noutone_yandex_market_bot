# Noutone → Yandex Market sync

Pushes Noutone's new-condition, Alif-enriched laptops to Yandex Market
(market.yandex.uz) via the Partner API. Pre-pipeline/exploratory as of
2026-08-22 — a manually-run set of scripts, not a deployed service.

## Setup

1. Copy `.env.example` → `.env` and fill in the values (see "Where things
   live" below). **Never commit `.env`** — it's already gitignored.
2. `pip install` nothing extra needed — stdlib only (`urllib`, `subprocess`
   calling `curl`).

## Usage

```bash
cd scripts
python3 build_offers.py        # fetch current laptops from the inserter, build ../all_offers.json
python3 submit_to_yandex.py    # push content+price (RU, then UZ), then set stock=5 for all
python3 check_status.py        # see real processing status/errors (see note below)
python3 notify_new_orders.py   # check for new DBS orders needing action, notify staff (see below)
```

Options on `submit_to_yandex.py`:
- `--stock-only` — only resend stock counts, skip content/price
- `--skip-stock` — push content/price, leave stock alone
- `--stock-count N` — override the default stock count of 5

Re-running is always safe — every push is a full overwrite of that laptop's
offer, not an incremental patch.

## What's currently applied (as of 2026-08-22)

- **Category**: all laptops go under `marketCategoryId` 91013 (Ноутбуки)
- **Price formula**: `(Billz USD price + $9 markup) × 12,000 (fixed FX rate)
  × 1.05 (Yandex-channel markup)`, then rounded to the nearest "...99,000"
  mark: if the position within the current 100,000 band is < 70 (in
  thousands) round down, else round up, then subtract 1,000. Crossed-out
  "was" price = `floor(final / 1,000,000) × 1,000,000 + 2,000,000`.
  Exact rule and worked examples are in `compute_price()` /
  `round_price_uzs()` / `old_price_uzs()` in `build_offers.py` - Asadbek
  gave this formula directly, don't reinterpret it.
- **Stock**: fixed at 5 units per laptop, one warehouse
  (`YANDEX_MARKET_WAREHOUSE_ID`)
- **IKPU** (Uzbekistan product tax code): fixed at `08443001001001001` for
  every laptop (matches the code already used on Asadbek's own pre-existing
  reference listing, "Asus66")
- **Naming**: Russian name is built from `webTitle` (or `title`), Uzbek name
  mirrors the Russian one exactly - only swaps the small closed set of
  things that must be Latin (Ноутбук→Noutbuk, ГБ/ТБ→GB/TB, the handful of
  Cyrillic color words). **Do not rebuild the Uzbek name from structured
  spec fields** - Asadbek explicitly corrected this once already, he wants
  it to visibly match the Russian name, not be a shorter reconstruction.
- **No "Версия" (region) parameter set** - Asadbek asked for the "Global"
  badge removed; don't re-add it without asking.
- Warranty: fixed 1 year, "provided by the seller/shop" (not "official
  service center" - real correction from Asadbek, the two are different
  claims).
- Package dimensions: fixed 40×30×35 cm + real per-laptop weight.

## Order notifications (added 2026-08-26)

`notify_new_orders.py` polls `GET /campaigns/{campaignId}/orders?status=PROCESSING`
(the dashboard's "dbsProcessing" tab) and sends one Telegram message per new
order to the staff group - the same bot (`@noutone_shop_bot`) and group
(`TELEGRAM_STAFF_CHAT_ID`) that Mini App/website consult and order
notifications already use. This exists because **Yandex auto-cancels a DBS
order** (`substatus: SHOP_FAILED`) if the seller doesn't respond in time -
first-hand confirmed, order `60838046467` was auto-cancelled this way before
this script existed. So this isn't a nice-to-have digest, it's the thing
that stops orders getting silently lost.

Dedup is a plain JSON file, `../notified_orders.json` (tracked in git, not
gitignored) - each order id is added the first time it's seen so re-running
every few minutes doesn't re-send the same order. `.github/workflows/notify-orders.yml`
runs this every 10 minutes via GitHub Actions and commits the updated state
file back to the repo (`contents: write` permission, no extra secret needed
for that part - `GITHUB_TOKEN` covers it). Needs 4 repo secrets set in
GitHub (Settings → Secrets and variables → Actions): `YANDEX_MARKET_API_KEY`,
`YANDEX_MARKET_CAMPAIGN_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_STAFF_CHAT_ID`.

Note: `buyer.phone` has been empty on every order seen so far (at least on
cancelled ones - unconfirmed whether it's populated on live PROCESSING
orders). The message still includes the buyer's name, delivery address, and
a dashboard link either way.

## Real bugs hit building this - don't re-discover these the hard way

1. **`{"status":"OK"}` on submit does not mean the offer is live or even
   valid.** The only reliable status/error source is
   `POST /v2/businesses/{businessId}/offer-cards`
   (`getOfferCardsContentStatus`) - `check_status.py` wraps it. Expect
   `cardStatus: NO_CARD_PROCESSING` → `HAS_CARD_CAN_UPDATE_PROCESSING` →
   settled, over several minutes for a bulk batch. Don't conclude a push
   failed from checking right after submitting.
2. **ENUM `parameterValues` sent as `{parameterId, valueId}` with no
   `value` are silently dropped** - always send both together.
3. **market.yandex.uz rejects Cyrillic in the UZ-language `name`, and in
   certain free-text `parameterValues` (7351754, 57046341, 14871214,
   17431917) even when submitted through the plain/RU-default call** -
   error `"Недопустимые символы: Укажите на узбекском языке латиницей"`.
   ENUM values sent with a real `valueId` alongside Cyrillic `value` text
   are fine; it's specifically free-text-only values that must be Latin.
4. **NUMERIC parameter units aren't consistently GHz/kg/cm** - check
   `unit.defaultUnitId`'s name in `laptop_category_params.json` before
   assuming (processor base-clock parameter defaults to MHz, for example -
   this pipeline skips it entirely rather than guess a conversion, since
   our specs data only has turbo clock anyway).
5. **A large price drop (2×+) from whatever price was live before triggers
   Yandex's own fraud-guard "price quarantine"** - the item stays hidden
   from the storefront with error `"Цена сильно снизилась"` until a human
   manually confirms the new price in the dashboard. This is expected and
   NOT fixable via the API - it happened to 8 laptops the first time this
   pipeline replaced an earlier flat 20,000,000 UZS placeholder price with
   the real per-item formula price. If you ever see this again after a
   price change, that's why - tell Asadbek to confirm in the dashboard,
   don't try to work around it.
6. Two laptops (`20003efc-...`, `cf33721a-...`, plus a third seen once,
   `cc6504d2-...`) have consistently scored slightly under 90/100 content
   rating across every resubmission so far, with zero actual errors - cause
   not yet identified (richer names didn't move it). Not urgent, just
   flagging so it isn't re-investigated from scratch as if it were new.

## Where things live

- **Yandex API token, business/campaign/warehouse IDs, inserter API
  key**: this folder's `.env` (gitignored, chmod 600) - see `.env.example`
  for the exact variable names. **Never write the actual token value
  anywhere else** (not memory, not a commit, not a different file) - if it
  ever needs rotating, that has to happen in the Yandex partner dashboard
  itself.
- **Category characteristics reference** (the ~58 parameters for the
  laptop category, with every ENUM's valid `valueId`s):
  `scripts/laptop_category_params.json`, fetched once via
  `POST /v2/category/91013/parameters` - re-fetch only if Yandex changes
  the category's schema, not on every run.
- **Dashboard** (login-gated, Asadbek's own Yandex account):
  `partner.market.yandex.ru/business/216979546/`
