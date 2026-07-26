#!/usr/bin/env python3
"""
Extract salary figures from a job description.

Anchored on a currency symbol/code (so US "401(k)" retirement plans and bare
years never match). Handles ranges, "up to", "circa/from", and "k" shorthand.

parse_salary(text) -> dict | None
    {"min": int|None, "max": int|None, "currency": "GBP|USD|EUR", "period": "year|hour"}
"""
import re

_CUR = {"£": "GBP", "$": "USD", "€": "EUR",
        "gbp": "GBP", "usd": "USD", "eur": "EUR"}

# A currency-anchored amount, e.g. £55,000 / $135,803.00 / €50.000 / 70k / GBP 60,000
_AMOUNT = re.compile(
    r"(?P<sym>[£$€]|\bGBP|\bUSD|\bEUR)\s*"
    r"(?P<num>\d{1,3}(?:[,\.]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d+)?)\s*(?P<k>k)?",
    re.I,
)
_PER_HOUR = re.compile(r"per\s*hour|/\s*hour|/\s*hr|hourly|an hour", re.I)


def _to_number(num, is_k):
    n = num.replace(",", "")
    # "50.000" (EU thousands) vs "204500.00" (decimal): treat a single dot with
    # exactly 3 trailing digits and no other separators as thousands.
    if n.count(".") == 1:
        intpart, frac = n.split(".")
        if len(frac) == 3 and not is_k:
            n = intpart + frac            # 50.000 -> 50000
        else:
            n = intpart                   # drop cents: 204500.00 -> 204500
    val = int(float(n))
    if is_k:
        val *= 1000
    return val


def parse_salary(text):
    if not text:
        return None
    hits = []
    currency = None
    for m in _AMOUNT.finditer(text):
        sym = m.group("sym").lower()
        cur = _CUR.get(sym) or _CUR.get(sym.strip())
        val = _to_number(m.group("num"), bool(m.group("k")))
        hits.append((m.start(), val, cur))

    period = "hour" if _PER_HOUR.search(text) else "year"
    lo_ok, hi_ok = (8, 500) if period == "hour" else (10_000, 3_000_000)
    vals = [(pos, v, c) for (pos, v, c) in hits if lo_ok <= v <= hi_ok]
    if not vals:
        return None
    currency = next((c for _, _, c in vals if c), "GBP")

    nums = sorted(v for _, v, _ in vals)
    # "up to X" / "maximum" -> treat as an upper bound only
    lowered = text.lower()
    if len(nums) == 1 and re.search(r"up to|maximum|no more than", lowered):
        return {"min": None, "max": nums[0], "currency": currency, "period": period}
    if len(nums) == 1:
        return {"min": nums[0], "max": nums[0], "currency": currency, "period": period}
    return {"min": nums[0], "max": nums[-1], "currency": currency, "period": period}


if __name__ == "__main__":
    for s in ["The salary range is $135,803.00 to $204,500.00 USD",
              "Salary: £55,000 - £70,000 per annum",
              "£55k to £70k depending on experience",
              "Up to £80,000", "circa £60,000", "competitive salary",
              "401(k) matching and benefits", "$45 per hour", "GBP 90,000"]:
        print(f"{s[:45]:45} -> {parse_salary(s)}")
