"""Weekly NZ fetch: read Woolworths NZ's vegan-tagged specials and keep deals that are 30%+ off.

Source list (same as the owner's link, sorted highest price first on the page):
  https://www.woolworths.co.nz/specials-offers?page=1&dietary=isVegan&staticFilters=SPECIALS&sortBy=PRICE_HIGH_LOW
Woolworths NZ specials run Monday to the following Sunday (NZ time).

Writes data/nz/candidates.json. Never decides vegan status: that is done by the vegan check step.
Skips (exit 0) if this week's candidates already exist, unless FORCE=1.
If Woolworths NZ blocks this server, falls back to Apify (APIFY_TOKEN) when an NZ actor is configured.
"""
import datetime as dt, json, os, re, sys, time, zoneinfo
import requests
try:
    from curl_cffi import requests as creq  # browser-like TLS, needed to get past Woolworths NZ's bot screen
except ImportError:
    creq = None

SOURCE = "https://www.woolworths.co.nz/specials-offers?page=1&dietary=isVegan&staticFilters=SPECIALS&sortBy=PRICE_HIGH_LOW"
BASE = "https://www.woolworths.co.nz"
MIN_DISCOUNT = 30
AKL = zoneinfo.ZoneInfo("Pacific/Auckland")
OUT = "data/nz/candidates.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")


def this_monday(now):
    d = now.date()
    return d - dt.timedelta(days=d.weekday())


def log(msg):
    os.makedirs("data/nz", exist_ok=True)
    open("data/nz/fetch-log.txt", "a").write(f"{dt.datetime.now(AKL).isoformat(timespec='minutes')} {msg}\n")
    print(msg)


def apify_proxies():
    """Apify Proxy routes to try, best first, using the Apify token already stored in GitHub secrets."""
    tok = os.environ.get("APIFY_TOKEN")
    if not tok:
        return []
    r = requests.get("https://api.apify.com/v2/users/me", params={"token": tok}, timeout=30)
    data = (r.json().get("data") or {}) if r.ok else {}
    px = data.get("proxy") or {}
    pw = px.get("password")
    groups = [g.get("name") for g in px.get("groups") or []]
    plan = (data.get("plan") or {}).get("id")
    log(f"Apify plan {plan}; proxy groups {groups}")
    if not pw:
        return []
    out = []
    for user in ("groups-RESIDENTIAL,country-NZ", "groups-RESIDENTIAL", "country-NZ", "auto"):
        u = f"http://{user}:{pw}@proxy.apify.com:8000"
        out.append((user, {"http": u, "https": u}))
    return out


def session():
    routes = apify_proxies() + [("direct", None)]
    for name, proxies in routes:
        if creq:
            s = creq.Session(impersonate="chrome")
        else:
            s = requests.Session()
            s.headers.update({"User-Agent": UA})
        s.headers.update({"Accept-Language": "en-NZ,en;q=0.9"})
        if proxies:
            s.proxies = proxies
        try:
            r = s.get(BASE + "/", timeout=40)
            log(f"route {name}: home page HTTP {r.status_code}, {len(r.content)} bytes")
            if r.status_code == 200:
                s.headers.update({"x-requested-with": "OnlineShopping.WebApp", "accept": "application/json",
                                  "referer": SOURCE})
                probe = s.get(BASE + "/api/v1/products", params={"target": "specials", "size": 1, "page": 1}, timeout=40)
                log(f"route {name}: API HTTP {probe.status_code}")
                if probe.status_code == 200 and "products" in probe.text[:2000]:
                    return s
        except Exception as e:
            log(f"route {name}: error {str(e)[:160]}")
    sys.exit("Could not reach woolworths.co.nz by any route")


def get_json(s, path, params=None, tries=3):
    for i in range(tries):
        try:
            r = s.get(BASE + path, params=params, timeout=45)
        except Exception as e:
            log(f"{path} error (try {i + 1}): {e}"); time.sleep(5 * (i + 1)); continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                pass
        log(f"{path} HTTP {r.status_code} (try {i + 1}): {r.text[:200]!r}")
        time.sleep(5 * (i + 1))
    sys.exit(f"Woolworths NZ refused {path}; likely blocking this server.")


def text_of(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " ".join(text_of(x) for x in v)
    if isinstance(v, dict):
        return " ".join(text_of(x) for x in v.values())
    return str(v)


def main():
    now = dt.datetime.now(AKL)
    mon = this_monday(now)
    week = {"from": mon.isoformat(), "to": (mon + dt.timedelta(days=6)).isoformat()}
    if os.environ.get("FORCE") != "1" and os.path.exists(OUT):
        old = json.load(open(OUT))
        if old.get("week", {}).get("from") == week["from"]:
            print("This week's NZ candidates already fetched; nothing to do."); return
    if now.weekday() == 0 and now.hour < 6:
        print("Too early on Monday (NZ); new specials may not be live yet."); return

    s = session()
    items, page, total = [], 1, None
    while True:
        j = get_json(s, "/api/v1/products", {
            "target": "specials", "inStockProductsOnly": "false", "size": 48, "page": page,
            "dasFilter": "PiesAttributes;;Vegan;true", "sortBy": "PRICE_HIGH_LOW"})
        prods = (j.get("products") or {})
        got = [x for x in prods.get("items") or [] if x.get("type") == "Product"]
        total = prods.get("totalItems") or 0
        items += got
        if not got or len(items) >= total or page >= 40:
            break
        page += 1
        time.sleep(1.5)
    if not items:
        sys.exit("Woolworths NZ returned no vegan specials")
    log(f"{len(items)} vegan-tagged specials listed (site total {total})")

    seen, keep, skipped = set(), [], {"no_price": 0, "under_min": 0, "out_of_stock": 0}
    for it in items:
        sku = str(it.get("sku") or "").strip()
        if not sku or sku in seen:
            continue
        seen.add(sku)
        p = it.get("price") or {}
        now_p, was_p = p.get("salePrice"), p.get("originalPrice")
        if not now_p or not was_p or was_p <= now_p:
            skipped["no_price"] += 1; continue
        pct = round((1 - now_p / was_p) * 100)
        if pct < MIN_DISCOUNT:
            skipped["under_min"] += 1; continue
        if (it.get("availabilityStatus") or "").lower() == "out of stock":
            skipped["out_of_stock"] += 1; continue
        keep.append((it, now_p, was_p, pct))

    rows, starts, ends = [], {}, {}
    for it, now_p, was_p, pct in keep:
        sku = str(it["sku"])
        time.sleep(1.2)
        d = get_json(s, f"/api/v1/products/{sku}")
        dp = d.get("price") or {}
        if dp.get("promotionStartDate"):
            starts[dp["promotionStartDate"][:10]] = starts.get(dp["promotionStartDate"][:10], 0) + 1
        if dp.get("promotionEndDate"):
            ends[dp["promotionEndDate"][:10]] = ends.get(dp["promotionEndDate"][:10], 0) + 1
        desc = re.sub(r"<[^>]+>", " ", text_of(d.get("description")))
        claims = [text_of(c).strip() for c in (d.get("claims") or []) if text_of(c).strip()]
        endorse = [text_of(c).strip() for c in (d.get("endorsements") or []) if text_of(c).strip()]
        vegan_text = sorted({m.group(0).strip() for m in
                             re.finditer(r"[^.\n]{0,70}\bvegan\w*[^.\n]{0,50}", desc, re.I)})[:3]
        imgs = d.get("images") or it.get("images") or []
        if isinstance(imgs, dict):
            imgs = list(imgs.values())
        img_urls = []
        for im in imgs:
            if isinstance(im, dict):
                img_urls.append(im.get("big") or im.get("small") or "")
            elif isinstance(im, str):
                img_urls.append(im)
        dept = ((it.get("departments") or [{}])[0] or {}).get("name") or ""
        rows.append({
            "code": sku,
            "slug": it.get("slug") or "",
            "name": re.sub(r"\s+", " ", (it.get("name") or d.get("name") or "")).strip(),
            "brand": re.sub(r"\s+", " ", (it.get("brand") or d.get("brand") or "")).strip(),
            "size": ((it.get("size") or {}).get("volumeSize") or "").strip(),
            "now": now_p, "was": was_p, "pct": pct, "half": 1 if pct >= 49 else 0,
            "ingredients": text_of(d.get("ingredients")).strip(),
            "mayContain": text_of(d.get("allergenMaybePresent")).strip(),
            "allergens": text_of(d.get("allergens")).strip(),
            "packClaim": "; ".join(claims + endorse),
            "descriptionVegan": vegan_text,
            "department": dept,
            "promo": [dp.get("promotionStartDate"), dp.get("promotionEndDate")],
            "images": [u for u in img_urls if u],
        })

    if starts:
        st = max(starts, key=starts.get)
        en = max(ends, key=ends.get) if ends else week["to"]
        week = {"from": st, "to": en}
    rows.sort(key=lambda x: -x["now"])
    out = {"week": week, "fetched": now.isoformat(timespec="minutes"), "itemsListed": len(items),
           "skipped": skipped, "minDiscount": MIN_DISCOUNT, "source": SOURCE, "rows": rows}
    os.makedirs("data/nz", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False)
    log(f"{len(items)} listed, {len(rows)} candidates at {MIN_DISCOUNT}%+ off; skipped {skipped}; week {week}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        log(traceback.format_exc())
        raise
