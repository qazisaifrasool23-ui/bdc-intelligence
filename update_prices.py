#!/usr/bin/env python3
"""
BDC Intelligence.AI — Price Updater
=====================================
Run this before each tester session (or 5-6x per day via Cowork reminder).

Usage:
    cd ~/bdc_research/bdc_app
    python3 update_prices.py

Then push:
    git add bdc_prices.json
    git commit -m "price update"
    git push

GitHub Pages updates in ~30 seconds.
Testers refresh their browser to see new prices.
"""

import json, time, urllib.request, os
from datetime import datetime

TICKERS = [
    "ARCC","BBDC","BCIC","BCSF","BXSL","CCAP","CGBD","CION","CSWC","EQS",
    "FDUS","FSK","GAIN","GBDC","GECC","GLAD","GSBD","HRZN","HTGC","ICMB",
    "KBDC","MAIN","MFIC","MRCC","MSIF","NMFC","OBDC","OCSL","OFS","OXSQ",
    "PFLT","PFX","PNNT","PSEC","RAND","RWAY","SAR","SCM","SLRC","SSSS",
    "TCPC","TPVG","TRIN","TSLX","WHF"
]

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bdc_prices.json")

def fetch_price(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return round(float(data["chart"]["result"][0]["meta"]["regularMarketPrice"]), 2)
    except:
        return None

print("=" * 45)
print("  BDC Intelligence.AI — Price Updater")
print("=" * 45)
print()

prices = {}
failed = []

for i, ticker in enumerate(TICKERS):
    price = fetch_price(ticker)
    if price:
        prices[ticker] = price
        print(f"  {ticker:<6} ${price:>8.2f}")
    else:
        prices[ticker] = None
        failed.append(ticker)
        print(f"  {ticker:<6}   FAILED")
    time.sleep(0.2)

timestamp = datetime.now().strftime("%b %d %Y %H:%M EST")
output = {
    "updated": timestamp,
    "prices": prices
}

with open(OUTPUT, "w") as f:
    json.dump(output, f, indent=2)

print()
print(f"✅ {len(prices) - len(failed)}/{len(TICKERS)} prices fetched")
if failed:
    print(f"⚠  Failed: {', '.join(failed)}")
print(f"✅ Saved to bdc_prices.json")
print(f"   Timestamp: {timestamp}")
print()
print("─" * 45)
print("Now run:")
print()
print("  git add bdc_prices.json")
print('  git commit -m "price update"')
print("  git push")
print()
print("GitHub Pages updates in ~30 seconds.")
print("─" * 45)
