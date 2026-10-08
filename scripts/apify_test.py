"""Small Apify test: does the Woolworths actor return this week's specials with the details we need?"""
import json, os, time, requests

TOKEN = os.environ["APIFY_TOKEN"]
ACTOR = "crawlplant~woolworths-au"
URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"

tests = {
    "half_price_vegan": {"mode": "specials", "specialsGroups": ["half-price"], "dietary": ["Vegan"],
                         "sortBy": "price_desc", "maxItems": 15, "includeRaw": True, "maxAgeHours": 0},
    "search_vegan_specials": {"mode": "search", "queries": ["Vegan"], "specialsOnly": True,
                              "sortBy": "price_desc", "maxItems": 15, "includeRaw": True, "maxAgeHours": 0},
}
out = {"time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "tests": {}}

def find(o, keys, path="", hits=None):
    hits = {} if hits is None else hits
    if isinstance(o, dict):
        for k, v in o.items():
            if k.lower() in keys and k.lower() not in hits:
                hits[k.lower()] = (path + "." + k, str(v)[:200])
            find(v, keys, path + "." + k, hits)
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]):
            find(v, keys, f"{path}[{i}]", hits)
    return hits

WANT = {"stockcode", "name", "brand", "price", "wasprice", "ishalfprice", "isonspecial", "packagesize",
        "ingredients", "lifestyleclaim", "suitablefor", "lifestyleanddietarystatement", "description",
        "richdescription", "detailsimagepaths", "images", "imageurl", "allergenmaybepresent", "dietary",
        "ismarketproduct", "specialsgroup", "specialstartdate", "specialenddate"}
for name, inp in tests.items():
    t0 = time.time()
    try:
        r = requests.post(URL, params={"token": TOKEN, "timeout": 280}, json=inp, timeout=320)
        rec = {"http": r.status_code, "seconds": round(time.time() - t0)}
        try:
            items = r.json()
        except Exception:
            items = None; rec["text"] = r.text[:300]
        if isinstance(items, list):
            rec["count"] = len(items)
            if items:
                rec["top_keys"] = sorted(items[0].keys())[:60]
                rec["fields_found"] = find(items[0], WANT)
                rec["products"] = [{k: it.get(k) for k in ("stockcode", "id", "name", "brand", "price", "wasPrice",
                                    "isHalfPrice", "isOnSpecial", "dietary") if k in it} for it in items[:15]]
        elif isinstance(items, dict):
            rec["error"] = json.dumps(items)[:400]
    except Exception as e:
        rec = {"error": repr(e)[:300]}
    out["tests"][name] = rec
    print(name, json.dumps(rec)[:500])
json.dump(out, open("apify-test-result.json", "w"), indent=1)
