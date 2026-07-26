#!/usr/bin/env python3
"""Normalise a messy free-text location into a country.

Handles the shapes the scrapers produce:
  "United States-Florida-Melbourne", "USA - North Charleston, SC",
  "US-IA-CEDAR RAPIDS-105 ~ ...", "Bristol, England, United Kingdom",
  "GBR - Cheltenham", "Bengaluru - Indraprastha", "2 Locations".
"""
import re

_UK = ("united kingdom", "england", "scotland", "wales", "northern ireland")
_US_STATES = (
    "florida", "california", "oklahoma", "utah", "georgia", "maryland",
    "south dakota", "ohio", "colorado", "virginia", "west virginia", "iowa",
    "texas", "arizona", "new mexico", "connecticut", "massachusetts", "missouri",
    "north carolina", "south carolina", "kansas", "illinois", "alabama",
    "pennsylvania", "new york", "washington", "minnesota", "indiana", "oregon",
)
_US_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "ia", "id",
    "il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo", "ms",
    "mt", "nc", "nd", "ne", "nh", "nj", "nm", "nv", "ny", "oh", "ok", "or",
    "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa", "wi", "wv", "wy",
}
_CITIES = {
    "United Kingdom": ("london", "bristol", "glasgow", "belfast", "manchester",
        "cheltenham", "farnborough", "abingdon", "witney", "cambridge",
        "edinburgh", "yeovil", "luton", "basildon", "stevenage", "filton",
        "portsmouth", "reading", "crawley", "gloucester", "broughton", "cwmbran",
        "linthouse", "cheadle", "derby", "whiteley", "havant", "alton", "bicester",
        "southampton", "gaydon", "ampthill", "market deeping", "brough", "frimley"),
    "India": ("bengaluru", "bangalore", "noida", "hyderabad", "pune", "mumbai",
        "delhi", "gurugram", "chennai", "indraprastha"),
    "France": ("toulouse", "elancourt", "cholet", "gennevilliers", "rennes",
        "valence", "orleans", "etrelles", "meudon", "bordeaux"),
    "Germany": ("stuttgart", "munich", "ulm", "bremen", "manching", "taufkirchen",
        "immenstaad", "friedrichshafen", "donauworth"),
    "Spain": ("madrid", "getafe", "tres cantos", "sevilla", "seville", "barcelona"),
    "Canada": ("quebec", "ontario", "ottawa", "toronto", "montreal", "calgary"),
    "Singapore": ("singapore",),
    "Australia": ("sydney", "melbourne", "canberra", "rydalmere", "brisbane"),
    "Italy": ("rome", "milan", "turin", "genoa"),
    "Belgium": ("zaventem", "brussels"),
}


def normalize_country(loc):
    if not loc or not loc.strip():
        return None
    s = loc.lower()
    if re.search(r"\d+\s+locations", s):
        return "Multiple"
    if any(k in s for k in _UK) or re.search(r"\b(gbr|uk)\b", s):
        return "United Kingdom"
    if ("united states" in s or "u.s.a" in s or re.search(r"\busa?\b", s)
            or re.search(r"\bus-[a-z]{2}-", s) or re.search(r"\bafb\b", s)):
        return "United States"
    for country, cities in _CITIES.items():
        if any(c in s for c in cities):
            return country
    if any(st in s for st in _US_STATES):
        return "United States"
    m = re.search(r",\s*([a-z]{2})\b\s*$", s)      # trailing ", TX"
    if m and m.group(1) in _US_CODES:
        return "United States"
    return None


if __name__ == "__main__":
    for s in ["United States-Florida-Melbourne", "USA - North Charleston, SC",
              "US-IA-CEDAR RAPIDS-105 ~ 400 Collins Rd NE", "United Kingdom",
              "Bristol, England, United Kingdom", "GBR - Cheltenham",
              "Bengaluru - Indraprastha", "Toulouse Area", "2 Locations", ""]:
        print(f"{s[:42]:42} -> {normalize_country(s)}")
