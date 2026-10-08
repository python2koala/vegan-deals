"""Weekly fetch: ask Apify for the three Woolworths lists and keep deals that are 40%+ off.

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
SYD = zoneinfo.ZoneInfo("Australia/Sydney")

def this_wednesday(now):
    d = now.date()
    return d - dt.timedelta(days=(d.weekday() - 2) % 7)

def main():
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

    r = requests.post(f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items",
                      params={"token": os.environ["APIFY_TOKEN"], "timeout": 290},
                      json={"mode": "urls", "urls": SOURCES, "maxItems": 1000,
                            "includeRaw": True, "maxAgeHours": 0}, timeout=330)
    if r.status_code >= 300:
        open("data/fetch-log.txt", "w").write(f"HTTP {r.status_code}\n{r.text[:3000]}\n")
        sys.exit(f"Apify HTTP {r.status_code}: {r.text[:300]}")
    items = r.json()
    if not isinstance(items, list) or not items:
        sys.exit(f"Apify returned no items: {str(items)[:300]}")

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
    out = {"week": week, "fetched": now.isoformat(timespec="minutes"), "itemsFromApify": len(items),
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
        open("data/fetch-log.txt", "a").write(traceback.format_exc())
        raise
