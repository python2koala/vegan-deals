"""Weekly fetch: ask Apify (main key, then backup keys) for the three Woolworths lists and keep deals that are 40%+ off.

Writes data/candidates.json. Never decides vegan status — that is done by the vegan check step.
Skips (exit 0) if this week's candidates already exist, unless FORCE=1.
"""
import datetime as dt, json, os, re, sys, time, zoneinfo, requests

SOURCES = [
    "https://www.woolworths.com.au/shop/browse/specials/half-price?pageNumber=1&sortBy=PriceDesc&filter=Lifestyle(Vegan)",
    "https://www.woolworths.com.au/shop/search/products?searchTerm=Vegan&isSpecial=true&pageNumber=1&sortBy=PriceDesc",
    "https://www.woolworths.com.au/shop/search/products?searchTerm=Plant%20Based&isSpecial=true&pageNumber=1&sortBy=PriceDesc",
]
MIN_DISCOUNT = 40
ACTOR = "crawlplant~woolworths-au"
MIN_CREDIT_USD = 0.50   # skip a key with less than this much monthly credit left
MIN_ITEMS = 40         # a normal week returns 150-250 items; fewer means the run was cut short
SYD = zoneinfo.ZoneInfo("Australia/Sydney")

def this_wednesday(now):
    d = now.date()
    return d - dt.timedelta(days=(d.weekday() - 2) % 7)

def main():
    os.makedirs("data", exist_ok=True)
    now = dt.datetime.now(SYD)
    wed = this_wednesday(now)
    week = {"from": wed.isoformat(), "to": (wed + dt.timedelta(days=6)).isoformat()}
    path = "data/candidates.json"
    if os.environ.get("FORCE") != "1" and os.path.exists(path):
        old = json.load(open(path))
        if old.get("week", {}).get("from") == week["from"]:
            print("This week's candidates already fetched; nothing to do."); return
    if now.weekday() == 2 and now.hour < 7:
        print("Too early on Wednesday (Sydney); new specials may not be live yet."); return

    def vegan_tag(it):
        aa = (it.get("raw") or {}).get("AdditionalAttributes") or {}
        return "vegan" in (aa.get("lifestyleanddietarystatement") or "").lower()

    log = []
    def note(msg):
        print(msg); log.append(msg)

    def credit_left(token):
        """Remaining Apify credit this month in USD, or None if it can't be read."""
        try:
            r = requests.get("https://api.apify.com/v2/users/me/limits", params={"token": token}, timeout=30)
            d = r.json().get("data", {})
            cur = d.get("current", {}).get("monthlyUsageUsd")
            cap = d.get("limits", {}).get("maxMonthlyUsageUsd")
            return None if cur is None or cap is None else round(cap - cur, 2)
        except Exception:
            return None

    def apify(token, urls):
        r = requests.post(f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items",
                          params={"token": token, "timeout": 290},
                          json={"mode": "urls", "urls": urls, "maxItems": 1500,
                                "includeRaw": True, "maxAgeHours": 0}, timeout=330)
        if r.status_code >= 300:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        got = r.json()
        if not isinstance(got, list):
            raise RuntimeError(f"unexpected reply: {str(got)[:300]}")
        return got

    # Keys are tried in order: APIFY_TOKEN first, then APIFY_TOKEN_2, APIFY_TOKEN_3 ... as backups.
    keys = [(n, os.environ[n].strip()) for n in ["APIFY_TOKEN"] + [f"APIFY_TOKEN_{i}" for i in range(2, 6)]
            if os.environ.get(n, "").strip()]
    if not keys:
        sys.exit("No Apify key found (APIFY_TOKEN / APIFY_TOKEN_2 ...)")
    items, used = None, None
    for name, token in keys:
        left = credit_left(token)
        if left is not None and left < MIN_CREDIT_USD:
            note(f"{name}: only ${left} credit left this month, skipping to the next key"); continue
        try:
            # Link A is the half-price page filtered to Woolworths' Lifestyle "Vegan" tag: apply that filter here.
            half = [it for it in apify(token, [SOURCES[0]]) if vegan_tag(it)]
            # Links B and C are Woolworths' own "Vegan" / "Plant Based" searches limited to specials.
            search = [it for it in apify(token, SOURCES[1:]) if it.get("isOnSpecial") or (it.get("raw") or {}).get("IsOnSpecial")]
        except Exception as e:
            note(f"{name}: failed ({str(e)[:200]}), trying the next key"); continue
        if len(half) + len(search) < MIN_ITEMS:
            note(f"{name}: only {len(half) + len(search)} items came back (credit may have run out mid-run), trying the next key"); continue
        items, used = half + search, name
        note(f"{name}: OK ({len(half)} half-price vegan-tagged, {len(search)} from searches; ${left} credit left before this run)")
        break
    open("data/fetch-log.txt", "w").write("\n".join(log) + "\n")
    if items is None:
        sys.exit("All Apify keys failed or are out of credit: " + " | ".join(log))
    counts = {"halfPriceVeganTag": len(half), "searches": len(search)}

    seen, rows, skipped = set(), [], {"no_price": 0, "under_40": 0, "out_of_stock": 0, "marketplace": 0}
    for it in items:
        raw = it.get("raw") or {}
        code = str(raw.get("Stockcode") or it.get("productId") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        aa = raw.get("AdditionalAttributes") or {}
        now_p, was_p = it.get("price") or raw.get("Price"), it.get("wasPrice") or raw.get("WasPrice")
        if not now_p or not was_p or was_p <= now_p:
            skipped["no_price"] += 1; continue
        pct = round((1 - now_p / was_p) * 100)
        if raw.get("IsMarketProduct") or it.get("isMarketplace"):
            skipped["marketplace"] += 1; continue
        if raw.get("IsInStock") is False or it.get("inStock") is False:
            skipped["out_of_stock"] += 1; continue
        if pct < MIN_DISCOUNT:
            skipped["under_40"] += 1; continue
        desc = " ".join(filter(None, [raw.get("RichDescription"), raw.get("Description"), it.get("description")]))
        desc = re.sub(r"<[^>]+>", " ", desc)
        vegan_text = sorted({m.group(0).strip() for m in re.finditer(r"[^.\n]{0,70}\bvegan\w*[^.\n]{0,50}", desc, re.I)})[:3]
        rows.append({
            "code": code,
            "name": raw.get("Name") or it.get("name"),
            "brand": raw.get("Brand") or it.get("brand") or "",
            "size": raw.get("PackageSize") or it.get("size") or "",
            "now": now_p, "was": was_p, "pct": pct,
            "half": 1 if raw.get("IsHalfPrice") else 0,
            "ingredients": aa.get("ingredients") or it.get("ingredients") or "",
            "mayContain": aa.get("allergenmaybepresent") or "",
            "allergyStatement": aa.get("allergystatement") or "",
            "packClaim": aa.get("lifestyleclaim") or "",
            "suitableFor": aa.get("suitablefor") or "",
            "woolworthsTag": aa.get("lifestyleanddietarystatement") or "",
            "descriptionVegan": vegan_text,
            "department": aa.get("sapdepartmentname") or "",
            "category": aa.get("sapcategoryname") or "",
            "images": raw.get("DetailsImagePaths") or it.get("images") or [],
        })
    rows.sort(key=lambda x: -x["now"])
    out = {"week": week, "fetched": now.isoformat(timespec="minutes"), "itemsFromApify": len(items), "bySource": counts, "fetchedWith": used,
           "skipped": skipped, "minDiscount": MIN_DISCOUNT, "sources": SOURCES, "rows": rows}
    json.dump(out, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"{len(items)} items from Apify, {len(rows)} candidates at {MIN_DISCOUNT}%+ off; skipped {skipped}")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        os.makedirs("data", exist_ok=True)
        open("data/fetch-log.txt", "a").write(traceback.format_exc())
        raise
