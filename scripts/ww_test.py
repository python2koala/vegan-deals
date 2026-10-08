"""Test whether GitHub's servers can read Woolworths' specials data."""
import json, time, requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                  "Accept-Language": "en-AU,en;q=0.9"})
out = {"time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "steps": []}

def step(name, fn):
    try:
        r = fn()
        rec = {"step": name, "status": r.status_code, "bytes": len(r.content),
               "start": r.text[:160].replace("\n", " ")}
        try:
            j = r.json(); rec["json_keys"] = list(j)[:8] if isinstance(j, dict) else None
            if isinstance(j, dict):
                rec["total"] = j.get("TotalRecordCount") or j.get("SearchResultsCount")
        except Exception:
            pass
    except Exception as e:
        rec = {"step": name, "error": repr(e)[:200]}
    out["steps"].append(rec); print(rec); time.sleep(2)

B = "https://www.woolworths.com.au"
step("home page", lambda: S.get(B + "/", headers={"Accept": "text/html"}, timeout=30))
step("half-price vegan list", lambda: S.post(B + "/apis/ui/browse/category", timeout=30, json={
    "categoryId": "specialsgroup.3676", "pageNumber": 1, "pageSize": 36, "sortType": "PriceDesc",
    "url": "/shop/browse/specials/half-price", "location": "/shop/browse/specials/half-price",
    "formatObject": '{"name":"Half Price"}', "isSpecial": True, "isBundle": False, "isMobile": False,
    "filters": [{"Key": "Lifestyle", "Items": [{"Term": "Vegan"}]}], "token": "", "gpBoost": 0,
    "isHideUnavailableProducts": False, "isRegisteredRewardCardPromotion": False,
    "enableAdReRanking": False, "groupEdmVariants": True, "categoryVersion": "v2"}))
step("search 'Vegan' specials", lambda: S.post(B + "/apis/ui/Search/products", timeout=30, json={
    "SearchTerm": "Vegan", "PageNumber": 1, "PageSize": 36, "SortType": "PriceDesc", "IsSpecial": True,
    "Location": "/shop/search/products?searchTerm=Vegan", "Filters": [],
    "IsRegisteredRewardCardPromotion": None, "ExcludeSearchTypes": ["UntraceableVendors"],
    "GpBoost": 0, "GroupEdmVariants": False, "EnableAdReRanking": False}))
step("product detail", lambda: S.get(B + "/apis/ui/product/detail/229702", timeout=30))
step("product photo", lambda: S.get("https://cdn0.woolworths.media/content/wowproductimages/large/229702.jpg", timeout=30))
json.dump(out, open("test-result.json", "w"), indent=1)
