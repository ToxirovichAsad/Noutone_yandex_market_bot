"""
Pushes the offers built by build_offers.py (../all_offers.json) to Yandex
Market: content+price (RU, then UZ name/description), then sets stock to a
fixed count on the one warehouse. Re-run any time - every call is a full
overwrite of that laptop's data, safe to repeat.

Usage:
    python3 build_offers.py          # fetch + build ../all_offers.json
    python3 submit_to_yandex.py      # push everything built above
    python3 submit_to_yandex.py --stock-only     # only resend stock counts
    python3 submit_to_yandex.py --stock-count 3  # override the default of 5
"""
import json, subprocess, time, os, sys, argparse

from build_offers import load_env, _SCRIPT_DIR

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-only", action="store_true", help="Skip content/price, only resend stock counts")
    parser.add_argument("--stock-count", type=int, default=5, help="Stock count to set per laptop (default 5)")
    parser.add_argument("--skip-stock", action="store_true", help="Push content/price but leave stock untouched")
    args = parser.parse_args()

    env = load_env()
    token = env.get('YANDEX_MARKET_API_KEY')
    business_id = env.get('YANDEX_MARKET_BUSINESS_ID')
    warehouse_id = env.get('YANDEX_MARKET_WAREHOUSE_ID')
    if not (token and business_id and warehouse_id):
        raise SystemExit(
            "Set YANDEX_MARKET_API_KEY, YANDEX_MARKET_BUSINESS_ID, YANDEX_MARKET_WAREHOUSE_ID "
            "in Noutone_yandex_market/.env first (see README.md)."
        )

    offers_path = os.path.join(_SCRIPT_DIR, '..', 'all_offers.json')
    offers = json.load(open(offers_path, encoding='utf-8'))
    print(f"{len(offers)} laptops loaded from {offers_path}")

    base = f"https://api.partner.market.yandex.ru/v2/businesses/{business_id}/offer-mappings/update"

    def post(url, body):
        payload = json.dumps(body)
        out = subprocess.run(
            ["curl", "-s", "-X", "POST", url, "-H", f"Api-Key: {token}",
             "-H", "Content-Type: application/json", "-d", payload, "-w", "\n%{http_code}"],
            capture_output=True, text=True, timeout=30,
        )
        lines = out.stdout.strip().split("\n")
        code = lines[-1]
        resp = "\n".join(lines[:-1])
        return code == "200" and '"status":"OK"' in resp.replace(" ", ""), resp

    t0 = time.time()

    if not args.stock_only:
        for i, item in enumerate(offers):
            lid = item['laptop_id']
            for lang, body, url in [
                ('ru', item['offer_ru'], base),
                ('uz', item['offer_uz'], base + '?language=UZ'),
            ]:
                ok, resp = post(url, {"offerMappings": [{"offer": body}]})
                if not ok:
                    print(f"FAIL {lid} {lang}: {resp[:200]}")
            if (i + 1) % 10 == 0:
                print(f"...content: {i+1}/{len(offers)}, {round(time.time()-t0,1)}s")
        print(f"Content+price pushed for {len(offers)} laptops in {round(time.time()-t0,1)}s")

    if not args.skip_stock:
        stock_url = f"https://api.partner.market.yandex.ru/v3/businesses/{business_id}/offers/stocks/update"
        sku_items = [
            {"sku": item['laptop_id'], "partnerWarehouseId": int(warehouse_id), "count": args.stock_count}
            for item in offers
        ]
        ok, resp = post(stock_url, {"skuItems": sku_items})
        print(f"Stock set to {args.stock_count} for {len(sku_items)} laptops: {'OK' if ok else 'FAILED - ' + resp[:200]}")

    print(f"\nDone in {round(time.time()-t0,1)}s total. Yandex takes several minutes to fully "
          "reprocess a bulk batch - re-check via offer-cards rather than assuming a fresh push "
          "failed if it doesn't show immediately (see README.md).")

if __name__ == "__main__":
    main()
