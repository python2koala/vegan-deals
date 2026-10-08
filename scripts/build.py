"""Build the live page data from this week's candidates and the saved vegan decisions.

- docs/deals.json : what the page shows (only products with a 'verified' or 'caution' decision)
- data/pending.json : candidates that still need a vegan check (new products, or 'no' decisions older than 56 days)
Products without a decision are never shown, so nothing unchecked can appear on the site.
"""
import datetime as dt, json, re

RECHECK_DAYS = 56
cand = json.load(open("data/candidates.json"))
conf = json.load(open("data/confirmations.json"))["rows"]
today = dt.date.today()

def may(text):
    t = (text or "").lower()
    out = [w for w in ("egg", "milk") if w in t]
    return ", ".join(out)

N, S, U = [""], ["Woolworths label"], [""]
def idx(lst, v):
    if v not in lst: lst.append(v)
    return lst.index(v)

rows, pending = [], []
for c in cand["rows"]:
    d = conf.get(c["code"])
    stale = d and d["status"] == "no" and (today - dt.date.fromisoformat(d["checked"])).days > RECHECK_DAYS
    if not d or stale:
        pending.append({k: c[k] for k in ("code", "name", "brand", "size", "pct", "category", "packClaim",
                                          "suitableFor", "descriptionVegan", "ingredients", "mayContain", "images")})
        continue
    if d["status"] not in ("verified", "caution"):
        continue
    name = re.sub(r"\s+", " ", d.get("name") or c["name"]).strip()
    rows.append([c["code"], name, d.get("brand") or c["brand"], c["size"], c["now"], c["was"], c["half"],
                 1 if d["status"] == "verified" else 0, ",".join(d.get("flags", [])),
                 d.get("mayContain") or may(c["mayContain"]), d.get("cat") or "p",
                 idx(N, d["note"]), idx(S, d["src"]), idx(U, d.get("url") or ""), 1 if d["status"] == "verified" else 0])
rows.sort(key=lambda r: (-r[4], r[1]))
out = {"w": [cand["week"]["from"], cand["week"]["to"]], "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
       "pending": len(pending), "N": N, "S": S, "U": U, "r": rows}
json.dump(out, open("docs/deals.json", "w"), ensure_ascii=False, separators=(",", ":"))
json.dump({"week": cand["week"], "count": len(pending), "rows": pending}, open("data/pending.json", "w"), indent=1, ensure_ascii=False)
print(f"{len(rows)} deals published, {len(pending)} waiting for a vegan check")
