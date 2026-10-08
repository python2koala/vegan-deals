# vegan-deals

Weekly Woolworths half-price and special-price **vegan** deals for happyvegan.au.

Google Sites: paste `docs/embed-paste-once.html` once (Insert > Embed > Embed code). It loads `docs/deals.json` live from this repository, so it updates by itself.
Optional GitHub Pages address (if Pages is switched on): https://python2koala.github.io/vegan-deals/

## How it updates (no computer needed)
1. **Wednesday morning (Sydney)**: `fetch.yml` asks Apify for the three Woolworths lists and keeps deals 40%+ off (`data/candidates.json`). Retries Wednesday evening and Thursday.
2. **Vegan check**: a Claude scheduled task researches every product in `data/pending.json` using the owner's standing protocol and records each decision in `data/confirmations.json`.
3. `scripts/build.py` turns candidates + decisions into `docs/deals.json`; the page `docs/index.html` loads it.

Only products with a recorded vegan decision are ever shown. When a specials week ends, old deals hide automatically.

A separate **manual weekly backup** (Claude scheduled task using the Claude desktop app) still produces paste-in embed code.
