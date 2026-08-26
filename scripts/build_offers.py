import json, re, html, math, os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(_SCRIPT_DIR, 'laptop_category_params.json'), encoding='utf-8'))
PARAMS = {p['id']: p for p in CAT['result']['parameters']}

CATEGORY_ID = 91013
IKPU = "08443001001001001"
MARKUP_USD = 9
FX_RATE = 12000
YANDEX_MARKUP = 1.05

def norm(s):
    return re.sub(r'\s+', ' ', (s or '').strip()).lower()

def find_enum(param_id, target, contains=False):
    p = PARAMS[param_id]
    t = norm(target)
    if not t:
        return None
    for v in p.get('values', []):
        vn = norm(v['value'])
        if vn == t:
            return (v['id'], v['value'])
    if contains:
        for v in p.get('values', []):
            vn = norm(v['value'])
            if vn and (vn in t or t in vn):
                return (v['id'], v['value'])
    return None

def md_to_html(text):
    if not text:
        return None
    lines = text.split('\n')
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('### '):
            out.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
        else:
            out.append(f"<p>{html.escape(line)}</p>")
    return ''.join(out)

def parse_inches(screen_size):
    m = re.search(r'(\d+(?:\.\d+)?)', screen_size or '')
    return m.group(1) if m else None

def diagonal_range_value(inches):
    if inches is None:
        return None
    try:
        n = float(inches)
    except ValueError:
        return None
    p = PARAMS[24896250]
    for v in p['values']:
        val = v['value']
        m = re.match(r'до (\d+(?:\.\d+)?)"$', val)
        if m and n < float(m.group(1)):
            return (v['id'], val)
        m = re.match(r'(\d+(?:\.\d+)?)"-(\d+(?:\.\d+)?)"$', val)
        if m and float(m.group(1)) <= n <= float(m.group(2)):
            return (v['id'], val)
        m = re.match(r'(\d+(?:\.\d+)?)" и более$', val)
        if m and n >= float(m.group(1)):
            return (v['id'], val)
    return None

COLOR_MAP = [
    (r'silver|серебр', 'серебристый'),
    (r'black|черн', 'черный'),
    (r'dark.?gr[ae]y|тёмно.?сер|темно.?сер', 'темно-серый'),
    (r'gr[ae]y|сер(?!ебр)', 'серый'),
    (r'blue|син|голуб', 'синий'),
    (r'white|бел', 'белый'),
    (r'gold|золот', 'золотистый'),
    (r'red|красн', 'красный'),
    (r'green|зелен', 'зеленый'),
    (r'purple|violet|фиолет', 'фиолетовый'),
    (r'pink|розов', 'розовый'),
    (r'orange|оранж', 'оранжевый'),
    (r'brown|коричнев', 'коричневый'),
    (r'beige|беж', 'бежевый'),
]

def match_color_filter(raw_color):
    t = norm(raw_color).replace('_', ' ')
    for pattern, canonical in COLOR_MAP:
        if re.search(pattern, t):
            return find_enum(13887626, canonical)
    return None

OS_MAP = {
    'windows_11_pro': 'Windows 11 Pro',
    'windows 11 pro': 'Windows 11 Pro',
    'windows 11': 'Windows 11 Home',
    'windows_11': 'Windows 11 Home',
}

def match_os(raw_os):
    t = norm(raw_os)
    display = OS_MAP.get(t)
    if display:
        r = find_enum(34812830, display)
        if r:
            return r
    return find_enum(34812830, raw_os)

def gpu_type_value(raw_type):
    t = norm(raw_type)
    if 'встроенная' in t and 'дискрет' in t:
        return (53328476, 'дискретная и встроенная')
    if 'дискрет' in t:
        return (53328474, 'дискретная')
    if 'встроен' in t:
        return (53328473, 'встроенная')
    return None

UZ_UNIT_FIXES = [
    (r'\bГГц\b', 'GGts'), (r'\bГц\b', 'Gts'),
    (r'\bГБ\b', 'GB'), (r'\bТБ\b', 'TB'), (r'\bМБ\b', 'MB'), (r'\bКБ\b', 'KB'),
    (r'\bмм\b', 'mm'), (r'\bкг\b', 'kg'), (r'\bВт\b', 'Vt'), (r'\bВт·ч\b', "Vt soat"),
]

def clean_uz_text(text):
    if not text:
        return text, True
    for pattern, repl in UZ_UNIT_FIXES:
        text = re.sub(pattern, repl, text)
    still_cyrillic = bool(re.search(r'[а-яё]', text.lower()))
    return text, not still_cyrillic

COLOR_UZ_LATIN = {
    'чёрный': 'Qora', 'черный': 'Qora',
    'серебристый': 'Kumush', 'silver': 'Silver',
    'серый': 'Kulrang', 'тёмно-серый': "To'q kulrang", 'темно-серый': "To'q kulrang",
    'синий': "Ko'k", 'белый': 'Oq',
}

# Word-for-word Cyrillic->Latin transliteration for the small, closed set of
# Cyrillic tokens that actually appear in our RU names (category word +
# units + occasional color word) - NOT a general Cyrillic transliterator.
# Per Asadbek's correction: the UZ name must mirror the RU name structure,
# not be rebuilt from spec fields - only the technical units/words change.
NAME_UZ_WORD_FIXES = [
    (r'\bИгровой ноутбук\b', "O'yin noutbuki"),
    (r'\bНоутбук\b', 'Noutbuk'),
    (r'\bГБ\b', 'GB'), (r'\bГб\b', 'GB'), (r'\bгб\b', 'GB'),
    (r'\bТБ\b', 'TB'), (r'\bТб\b', 'TB'), (r'\bтб\b', 'TB'),
    (r'\bГц\b', 'Hz'), (r'\bГГц\b', 'GHz'),
]

def latin_uz_name(name_ru):
    """Mirror the Russian name structure exactly, only swapping the small,
    known set of Cyrillic words/units for their Latin equivalents - per
    Asadbek's explicit correction against the earlier from-scratch rebuild.
    Falls back to a spec-field-free simple strip if stray Cyrillic remains
    (e.g. an unmapped color word)."""
    name = name_ru
    # A few source titles have a Latin "c" typo'd in place of Cyrillic "с"
    # at the start of a Cyrillic word (visually identical, different
    # codepoint) - normalize before the dict-based color replacement below,
    # or the lookalike silently fails to match and leaves stray Cyrillic.
    name = re.sub(r'\bc(?=[а-яё]{3,})', 'с', name)
    for pattern, repl in NAME_UZ_WORD_FIXES:
        name = re.sub(pattern, repl, name)
    # Longest keys first - "тёмно-серый" must match before the shorter
    # "серый" it contains, or the short key corrupts it mid-replacement
    # (confirmed live: produced "Тёмно-Kulranый" instead of "To'q kulrang").
    for cyr, lat in sorted(COLOR_UZ_LATIN.items(), key=lambda kv: -len(kv[0])):
        name = re.sub(re.escape(cyr), lat, name, flags=re.IGNORECASE)
    if re.search(r'[а-яё]', name.lower()):
        # Something not in our known word list still leaked through - strip
        # whatever Cyrillic token remains rather than submit invalid text;
        # better a slightly shorter name than a rejected one.
        name = re.sub(r'[а-яёА-ЯЁ]+', '', name)
        name = re.sub(r'\s{2,}', ' ', name).strip(' /,')
    return name

def round_price_uzs(raw):
    """Round to the nearest '...99,000' mark, using an explicit threshold
    (not plain nearest-rounding): look at the position within the current
    100,000 band, in thousands (0-99.9); below 70 rounds down to the lower
    band's 99,000 mark, 70+ rounds up to the next band's. Matches both of
    Asadbek's worked examples exactly (6,413,400 -> 6,399,000 [13.4 -> down],
    7,780,000 -> 7,799,000 [80 -> up])."""
    lower = math.floor(raw / 100000) * 100000
    upper = lower + 100000
    remainder_thousands = (raw - lower) / 1000
    return (lower if remainder_thousands < 70 else upper) - 1000

def old_price_uzs(final_price):
    """Crossed-out 'was' price: round the final price down to the nearest
    million, add 2,000,000. Matches Asadbek's example (7,799,000 -> 7,000,000
    + 2,000,000 = 9,000,000)."""
    return math.floor(final_price / 1000000) * 1000000 + 2000000

def compute_price(billz_price_usd):
    adjusted = billz_price_usd + MARKUP_USD
    raw_uzs = adjusted * FX_RATE * YANDEX_MARKUP
    final = round_price_uzs(raw_uzs)
    old = old_price_uzs(final)
    return final, old

def build_offer(l):
    specs = l['specs']
    proc = specs.get('processor', {})
    ram = specs.get('ram', {})
    disp = specs.get('display', {})
    gpu = specs.get('gpu', {})
    storage = specs.get('storage', {})
    general = specs.get('general', {})

    pictures = [p['url'] for p in sorted(l['photos'], key=lambda p: p['sortOrder']) if p['platform'] == 'alif']
    if not pictures:
        return None, "no alif photos"

    name_source = l.get('webTitle') or l['title']
    name_source = re.sub(r'^(Ноутбук|Игровой ноутбук)\s+', '', name_source).strip()
    brand = l.get('brand') or ''
    _ram_sz = (ram.get('size') or '').strip()
    _cap = (storage.get('capacity') or '').strip()
    _color = (l.get('color') or '').strip()
    extras = []
    if _ram_sz and norm(_ram_sz.replace(' ', '')) not in norm(name_source.replace(' ', '')):
        extras.append(_ram_sz)
    if _cap and norm(_cap.replace(' ', '')) not in norm(name_source.replace(' ', '')):
        extras.append(_cap)
    if _color and norm(_color) not in norm(name_source):
        extras.append(_color)
    if extras:
        name_source = f"{name_source} {'/'.join(extras)}"
    name_ru = f"Ноутбук {name_source}"[:256]
    name_uz = latin_uz_name(name_ru)[:256]

    desc_ru = md_to_html(l.get('description'))
    if not desc_ru:
        return None, "no description"
    uz_raw_clean, uz_is_clean = clean_uz_text(l.get('descriptionUz'))
    desc_uz = md_to_html(uz_raw_clean) if uz_is_clean else None

    weight = None
    m = re.search(r'(\d+(?:\.\d+)?)', general.get('weight') or '')
    if m:
        weight = float(m.group(1))

    pv = []
    notes = []

    def add_numeric(pid, value):
        if value is None or value == '':
            return
        pv.append({"parameterId": pid, "value": str(value)})

    def add_enum(pid, target, contains=False, custom_ok=True):
        r = find_enum(pid, target, contains=contains)
        if r:
            pv.append({"parameterId": pid, "valueId": r[0], "value": r[1]})
        elif custom_ok and target:
            pv.append({"parameterId": pid, "value": str(target)})
            notes.append(f"custom(no catalog match): {PARAMS[pid]['name']}={target}")

    def add_pair(pid, pair):
        if pair:
            pv.append({"parameterId": pid, "valueId": pair[0], "value": pair[1]})

    inches = parse_inches(disp.get('screenSize'))
    add_numeric(14805766, inches)
    storage_type = norm(storage.get('type'))
    cap = (storage.get('capacity') or '').replace(' ', ' ').strip()
    cap_norm = re.sub(r'(\d)(ГБ|ТБ)', r'\1 \2', cap, flags=re.I)
    if 'ssd' in storage_type or 'sdd' in storage_type or 'nvme' in storage_type:
        add_enum(37699290, cap_norm, contains=True)
    elif 'hdd' in storage_type:
        add_enum(37699070, cap_norm, contains=True)
    add_enum(24892510, ram.get('size'), contains=True)
    add_pair(21194330, (36779198, 'ноутбук'))
    add_enum(36036031, gpu.get('model'), contains=True)
    add_pair(34812830, match_os(general.get('os')))

    res = re.sub(r'\(.*?\)', '', disp.get('resolution') or '').replace(' ', '').lower()
    add_enum(14806501, res)
    cpu_model = proc.get('model') or ''
    cpu_full = f"{proc.get('series','')} {cpu_model}".strip()
    r = find_enum(34814970, cpu_full) or find_enum(34814970, cpu_model)
    if r:
        pv.append({"parameterId": 34814970, "valueId": r[0], "value": r[1]})
    elif cpu_model:
        pv.append({"parameterId": 34814970, "value": cpu_model})
    add_pair(37708450, gpu_type_value(gpu.get('type')))
    gpu_type_norm = norm(gpu.get('type'))
    if 'дискрет' in gpu_type_norm and gpu.get('vram'):
        add_enum(45123612, gpu.get('vram'), contains=True)
    elif gpu_type_norm and 'дискрет' not in gpu_type_norm:
        add_pair(45123612, (50195408, 'SMA'))
    rr = (disp.get('refreshRate') or '').strip()
    add_enum(16499888, rr)
    add_pair(24896250, diagonal_range_value(inches))
    cores = (proc.get('cores') or '').strip()
    add_enum(34814810, cores)
    add_pair(13887626, match_color_filter(l.get('color')))
    add_enum(44079570, str(bool(storage.get('keyboardBacklight'))).lower(), custom_ok=True)
    add_enum(14806037, str(bool(disp.get('touchscreen'))).lower(), custom_ok=True)
    add_enum(44080002, str(bool(storage.get('fingerprintScanner'))).lower(), custom_ok=True)
    add_enum(37845410, str(bool(disp.get('stylus'))).lower(), custom_ok=True)
    add_enum(37338070, ram.get('type'), contains=True)
    add_enum(27142471, ram.get('speed'))
    add_enum(45131230, disp.get('coating'), contains=True)
    add_numeric(23674510, weight)
    pv.append({"parameterId": 33663230, "value": "1"})
    add_enum(24281010, disp.get('keyboardLayout'), contains=True)
    if 'ssd' in storage_type or 'sdd' in storage_type or 'nvme' in storage_type:
        add_pair(37699070, (39025551, 'отсутствует'))
    if l.get('color'):
        color_latin = COLOR_UZ_LATIN.get(norm(l['color']), l['color'])
        pv.append({"parameterId": 14871214, "value": color_latin})
    add_pair(45131744, (50217896, 'Touchpad'))
    add_pair(50047971, (50212669, 'нет'))
    # 23476910 "Версия" (region badge) deliberately NOT set anymore -
    # Asadbek asked for the "Global" badge to be removed.
    add_pair(16476541, (37514291, 'нет'))
    pv.append({"parameterId": 35324530, "value": "USB, HDMI"})
    sku_clean = re.sub(r'^(Ноутбук|Игровой ноутбук)\s+', '', l.get('sku') or '').strip()
    if sku_clean and not re.search(r'[а-яё]', sku_clean.lower()):
        pv.append({"parameterId": 17431917, "value": sku_clean[:100]})
    raw_desc = (l.get('description') or '').lower()
    if 'onboard' in raw_desc or 'встроенная память' in raw_desc:
        pv.append({"parameterId": 44076031, "value": "0"})

    if uz_is_clean and uz_raw_clean:
        desc_lines = [ln.strip().lstrip('#').strip() for ln in uz_raw_clean.split('\n') if ln.strip()]
        if desc_lines:
            pv.append({"parameterId": 7351754, "value": desc_lines[0][:500]})
            rest = ' '.join(ln for ln in desc_lines[1:] if not ln.startswith('###') and len(ln) > 3)
            rest = re.sub(r'^###\s*', '', rest)
            if rest:
                pv.append({"parameterId": 57046341, "value": rest[:1900]})

    billz_usd = float(l['price'])
    final_price, old_price = compute_price(billz_usd)

    offer = {
        "offerId": l['id'],
        "name": name_ru,
        "marketCategoryId": CATEGORY_ID,
        "pictures": pictures,
        "vendor": brand,
        "barcodes": [l['barcode']] if l.get('barcode') else None,
        "description": desc_ru,
        "basicPrice": {"value": final_price, "currencyId": "UZS", "discountBase": old_price},
        "weightDimensions": ({"length": 40, "width": 30, "height": 35, "weight": weight} if weight else None),
        "guaranteePeriod": {"timePeriod": 1, "timeUnit": "YEAR", "comment": "Гарантия предоставляется магазином-продавцом"},
        "commodityCodes": [{"code": IKPU, "type": "IKPU_CODE"}],
        "parameterValues": pv,
    }
    offer = {k: v for k, v in offer.items() if v is not None}
    offer_uz = {"offerId": l['id'], "name": name_uz, "description": desc_uz}
    offer_uz = {k: v for k, v in offer_uz.items() if v is not None}
    return (offer, offer_uz, billz_usd, final_price, old_price), notes

def load_env():
    """Reads KEY=VALUE pairs from the sibling .env (never committed - see
    .gitignore). Deliberately not python-dotenv to avoid a dependency for
    a two-line need."""
    env = {}
    env_path = os.path.join(_SCRIPT_DIR, '..', '.env')
    if os.path.exists(env_path):
        for line in open(env_path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

def fetch_candidates(inserter_url, inserter_key):
    """Pulls every laptop from the inserter and keeps only what this pipeline
    can actually list: new condition (never CREF/REF/openbox/used - Asadbek's
    explicit rule), has a real description, has real specs, has real Alif
    photos. Paginates until a short page confirms the end."""
    import urllib.request
    all_laptops = []
    page = 1
    while True:
        req = urllib.request.Request(
            f"{inserter_url}/api/v1/laptops?limit=100&page={page}",
            headers={"x-api-key": inserter_key},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
        batch = data.get('laptops', [])
        all_laptops.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    cands = [
        l for l in all_laptops
        if l['conditionType'] == 'new'
        and l.get('description')
        and l.get('specs', {}).get('processor', {}).get('model')
        and any(p['platform'] == 'alif' for p in l.get('photos', []))
    ]
    return cands

if __name__ == "__main__":
    env = load_env()
    inserter_url = env.get('INSERTER_API_URL', 'https://noutone-inserter.vercel.app')
    inserter_key = env.get('INSERTER_API_KEY') or env.get('INTERNAL_API_KEY')
    if not inserter_key:
        raise SystemExit("Set INSERTER_API_KEY (or INTERNAL_API_KEY) in Noutone_yandex_market/.env first.")

    print(f"Fetching current new-condition, Alif-enriched laptops from {inserter_url} ...")
    cands = fetch_candidates(inserter_url, inserter_key)
    print(f"{len(cands)} candidates")

    results = []
    for l in cands:
        res, notes = build_offer(l)
        if res is None:
            print("SKIP", l['id'], notes)
            continue
        offer_ru, offer_uz, billz_usd, final_price, old_price = res
        results.append({"laptop_id": l['id'], "offer_ru": offer_ru, "offer_uz": offer_uz})
        print(f"{l['id'][:8]} | billz=${billz_usd:.0f} -> {final_price:,.0f} UZS (was {old_price:,.0f}) | uz_name: {offer_uz['name'][:70]}")

    out_path = os.path.join(_SCRIPT_DIR, '..', 'all_offers.json')
    json.dump(results, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"\ntotal built: {len(results)} -> {out_path}")
    print("Next: python3 submit_to_yandex.py")
