#!/usr/bin/env python3
"""
Workday API Scraper

Scrapes job listings from companies using Workday's career platform.
The Workday API follows a consistent pattern across companies.

Usage:
    python scrapers/workday_scraper.py --all --search London           # All companies sequentially
    python scrapers/workday_scraper.py --all --search London --parallel  # All companies in parallel
    python scrapers/workday_scraper.py --all -p -w 10                  # Parallel with 10 workers
    python scrapers/workday_scraper.py --company nvidia --search UK    # Specific company
    python scrapers/workday_scraper.py --list                          # List available companies
    python scrapers/workday_scraper.py --test nvidia                   # Test API endpoint
"""

import json
import requests
import argparse
import time
import os
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# For I/O-bound tasks, use more threads than CPUs (they're mostly waiting on network)
DEFAULT_WORKERS = max(10, (os.cpu_count() or 4) * 2)

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# Workday company configurations
# Pattern: https://{subdomain}.wd{N}.myworkdayjobs.com/wday/cxs/{company}/{site}/jobs
WORKDAY_COMPANIES = {
    "adobe": {
        "name": "Adobe",
        "api_url": "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs",
        "careers_url": "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced",
        "location_filter": ["bc33aa3152ec42d4995f4791a106ed09"],  # UK
    },
    "nvidia": {
        "name": "NVIDIA",
        "api_url": "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs",
        "careers_url": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
        "location_filter": [],  # Empty = all locations
    },
    "intel": {
        "name": "Intel",
        "api_url": "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs",
        "careers_url": "https://intel.wd1.myworkdayjobs.com/en-US/External",
        "location_filter": [],
    },
    "disney": {
        "name": "Disney",
        "api_url": "https://disney.wd5.myworkdayjobs.com/wday/cxs/disney/disneycareer/jobs",
        "careers_url": "https://disney.wd5.myworkdayjobs.com/en-US/disneycareer",
        "location_filter": [],
    },
    "hp": {
        "name": "HP",
        "api_url": "https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs",
        "careers_url": "https://hp.wd5.myworkdayjobs.com/en-US/ExternalCareerSite",
        "location_filter": [],
    },
    "samsung": {
        "name": "Samsung",
        "api_url": "https://sec.wd3.myworkdayjobs.com/wday/cxs/sec/Samsung_Careers/jobs",
        "careers_url": "https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers",
        "location_filter": [],
    },
    "sony": {
        "name": "Sony",
        "api_url": "https://sonyglobal.wd1.myworkdayjobs.com/wday/cxs/sonyglobal/SonyGlobalCareers/jobs",
        "careers_url": "https://sonyglobal.wd1.myworkdayjobs.com/en-US/SonyGlobalCareers",
        "location_filter": [],
    },
    "redhat": {
        "name": "Red Hat",
        "api_url": "https://redhat.wd5.myworkdayjobs.com/wday/cxs/redhat/jobs/jobs",
        "careers_url": "https://redhat.wd5.myworkdayjobs.com/en-US/jobs",
        "location_filter": [],
    },
    "capital_one": {
        "name": "Capital One",
        "api_url": "https://capitalone.wd12.myworkdayjobs.com/wday/cxs/capitalone/Capital_One/jobs",
        "careers_url": "https://capitalone.wd12.myworkdayjobs.com/en-US/Capital_One",
        "location_filter": [],
    },
    "walmart": {
        "name": "Walmart",
        "api_url": "https://walmart.wd5.myworkdayjobs.com/wday/cxs/walmart/WalmartExternal/jobs",
        "careers_url": "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal",
        "location_filter": [],
    },
    "target": {
        "name": "Target",
        "api_url": "https://target.wd5.myworkdayjobs.com/wday/cxs/target/targetcareers/jobs",
        "careers_url": "https://target.wd5.myworkdayjobs.com/en-US/targetcareers",
        "location_filter": [],
    },
    "comcast": {
        "name": "Comcast",
        "api_url": "https://comcast.wd5.myworkdayjobs.com/wday/cxs/comcast/Comcast_Careers/jobs",
        "careers_url": "https://comcast.wd5.myworkdayjobs.com/en-US/Comcast_Careers",
        "location_filter": [],
    },
    "medtronic": {
        "name": "Medtronic",
        "api_url": "https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs",
        "careers_url": "https://medtronic.wd1.myworkdayjobs.com/en-US/MedtronicCareers",
        "location_filter": [],
    },
    "cvs": {
        "name": "CVS Health",
        "api_url": "https://cvshealth.wd1.myworkdayjobs.com/wday/cxs/cvshealth/CVS_Health_Careers/jobs",
        "careers_url": "https://cvshealth.wd1.myworkdayjobs.com/en-US/CVS_Health_Careers",
        "location_filter": [],
    },
    "barclays_wd": {
        "name": "Barclays (Workday)",
        "api_url": "https://barclays.wd3.myworkdayjobs.com/wday/cxs/barclays/External_Career_Site_Barclays/jobs",
        "careers_url": "https://barclays.wd3.myworkdayjobs.com/en-US/External_Career_Site_Barclays",
        "location_filter": [],
    },
    # New companies discovered from Workday customer list
    "netflix": {
        "name": "Netflix",
        "api_url": "https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs",
        "careers_url": "https://netflix.wd1.myworkdayjobs.com/en-US/Netflix",
        "location_filter": [],
    },
    "pfizer": {
        "name": "Pfizer",
        "api_url": "https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs",
        "careers_url": "https://pfizer.wd1.myworkdayjobs.com/en-US/PfizerCareers",
        "location_filter": [],
    },
    "blackrock": {
        "name": "BlackRock",
        "api_url": "https://blackrock.wd1.myworkdayjobs.com/wday/cxs/blackrock/BlackRock_Professional/jobs",
        "careers_url": "https://blackrock.wd1.myworkdayjobs.com/en-US/BlackRock_Professional",
        "location_filter": [],
    },
    "mastercard": {
        "name": "Mastercard",
        "api_url": "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs",
        "careers_url": "https://mastercard.wd1.myworkdayjobs.com/en-US/CorporateCareers",
        "location_filter": [],
    },
    "ebay": {
        "name": "eBay",
        "api_url": "https://ebay.wd5.myworkdayjobs.com/wday/cxs/ebay/apply/jobs",
        "careers_url": "https://ebay.wd5.myworkdayjobs.com/en-US/apply",
        "location_filter": [],
    },
    "morgan_stanley": {
        "name": "Morgan Stanley",
        "api_url": "https://ms.wd5.myworkdayjobs.com/wday/cxs/ms/External/jobs",
        "careers_url": "https://ms.wd5.myworkdayjobs.com/en-US/External",
        "location_filter": [],
    },
    "bofa": {
        "name": "Bank of America",
        "api_url": "https://ghr.wd1.myworkdayjobs.com/wday/cxs/ghr/Lateral-US/jobs",
        "careers_url": "https://ghr.wd1.myworkdayjobs.com/en-US/Lateral-US",
        "location_filter": [],
    },
    # UK and International companies
    "bupa": {
        "name": "Bupa",
        "api_url": "https://bupa.wd3.myworkdayjobs.com/wday/cxs/bupa/EXT_CAREER/jobs",
        "careers_url": "https://bupa.wd3.myworkdayjobs.com/en-GB/EXT_CAREER",
        "location_filter": [],
    },
    "talktalk": {
        "name": "TalkTalk",
        "api_url": "https://talktalk.wd3.myworkdayjobs.com/wday/cxs/talktalk/TalkTalkCareers/jobs",
        "careers_url": "https://talktalk.wd3.myworkdayjobs.com/en-US/TalkTalkCareers",
        "location_filter": [],
    },
    "zendesk": {
        "name": "Zendesk",
        "api_url": "https://zendesk.wd1.myworkdayjobs.com/wday/cxs/zendesk/zendesk/jobs",
        "careers_url": "https://zendesk.wd1.myworkdayjobs.com/en-US/zendesk",
        "location_filter": [],
    },
    "sutter_health": {
        "name": "Sutter Health",
        "api_url": "https://sutterhealth.wd1.myworkdayjobs.com/wday/cxs/sutterhealth/sh/jobs",
        "careers_url": "https://sutterhealth.wd1.myworkdayjobs.com/en-US/sh",
        "location_filter": [],
    },
    # Entertainment & Consumer Goods
    "warner_bros": {
        "name": "Warner Bros Discovery",
        "api_url": "https://warnerbros.wd5.myworkdayjobs.com/wday/cxs/warnerbros/global/jobs",
        "careers_url": "https://warnerbros.wd5.myworkdayjobs.com/en-US/global",
        "location_filter": [],
    },
    "pg": {
        "name": "Procter & Gamble",
        "api_url": "https://pg.wd5.myworkdayjobs.com/wday/cxs/pg/1000/jobs",
        "careers_url": "https://pg.wd5.myworkdayjobs.com/en-US/1000",
        "location_filter": [],
    },
    # Financial Services
    "fis": {
        "name": "FIS Global",
        "api_url": "https://fis.wd5.myworkdayjobs.com/wday/cxs/fis/SearchJobs/jobs",
        "careers_url": "https://fis.wd5.myworkdayjobs.com/en-US/SearchJobs",
        "location_filter": [],
    },
    "wfs": {
        "name": "World Fuel Services",
        "api_url": "https://wfscorp.wd5.myworkdayjobs.com/wday/cxs/wfscorp/wfscareers/jobs",
        "careers_url": "https://wfscorp.wd5.myworkdayjobs.com/en-US/wfscareers",
        "location_filter": [],
    },
    # Tech & Consulting
    "workday_inc": {
        "name": "Workday",
        "api_url": "https://workday.wd5.myworkdayjobs.com/wday/cxs/workday/Workday/jobs",
        "careers_url": "https://workday.wd5.myworkdayjobs.com/en-US/Workday",
        "location_filter": [],
    },
    "crowdstrike": {
        "name": "CrowdStrike",
        "api_url": "https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers/jobs",
        "careers_url": "https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers",
        "location_filter": [],
    },
    "guidehouse": {
        "name": "Guidehouse",
        "api_url": "https://guidehouse.wd1.myworkdayjobs.com/wday/cxs/guidehouse/External/jobs",
        "careers_url": "https://guidehouse.wd1.myworkdayjobs.com/en-US/External",
        "location_filter": [],
    },
    "pwc": {
        "name": "PwC",
        "api_url": "https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/Global_Experienced_Careers/jobs",
        "careers_url": "https://pwc.wd3.myworkdayjobs.com/en-US/Global_Experienced_Careers",
        "location_filter": [],
    },
    # Healthcare & Manufacturing
    "resmed": {
        "name": "ResMed",
        "api_url": "https://resmed.wd3.myworkdayjobs.com/wday/cxs/resmed/ResMed_External_Careers/jobs",
        "careers_url": "https://resmed.wd3.myworkdayjobs.com/en-US/ResMed_External_Careers",
        "location_filter": [],
    },
    "transunion": {
        "name": "TransUnion",
        "api_url": "https://transunion.wd5.myworkdayjobs.com/wday/cxs/transunion/TransUnion/jobs",
        "careers_url": "https://transunion.wd5.myworkdayjobs.com/en-US/TransUnion",
        "location_filter": [],
    },
    "ciena": {
        "name": "Ciena",
        "api_url": "https://ciena.wd5.myworkdayjobs.com/wday/cxs/ciena/Careers/jobs",
        "careers_url": "https://ciena.wd5.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "aveva": {
        "name": "AVEVA",
        "api_url": "https://aveva.wd3.myworkdayjobs.com/wday/cxs/aveva/AVEVA_careers/jobs",
        "careers_url": "https://aveva.wd3.myworkdayjobs.com/en-US/AVEVA_careers",
        "location_filter": [],
    },
    "jabil": {
        "name": "Jabil",
        "api_url": "https://jabil.wd5.myworkdayjobs.com/wday/cxs/jabil/Jabil_Careers/jobs",
        "careers_url": "https://jabil.wd5.myworkdayjobs.com/en-US/Jabil_Careers",
        "location_filter": [],
    },
    # ============================================================
    # Companies discovered from Google search (London/UK jobs)
    # ============================================================
    "aegislondon": {
        "name": "Aegis London",
        "api_url": "https://aegislondon.wd3.myworkdayjobs.com/wday/cxs/aegislondon/Careers/jobs",
        "careers_url": "https://aegislondon.wd3.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "alantra": {
        "name": "Alantra",
        "api_url": "https://alantra.wd3.myworkdayjobs.com/wday/cxs/alantra/Alantra/jobs",
        "careers_url": "https://alantra.wd3.myworkdayjobs.com/en-US/Alantra",
        "location_filter": [],
    },
    "arriva": {
        "name": "Arriva",
        "api_url": "https://arriva.wd3.myworkdayjobs.com/wday/cxs/arriva/Careers/jobs",
        "careers_url": "https://arriva.wd3.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "bbva": {
        "name": "BBVA",
        "api_url": "https://bbva.wd3.myworkdayjobs.com/wday/cxs/bbva/BBVA/jobs",
        "careers_url": "https://bbva.wd3.myworkdayjobs.com/en-US/BBVA",
        "location_filter": [],
    },
    "biogen": {
        "name": "Biogen",
        "api_url": "https://biibhr.wd3.myworkdayjobs.com/wday/cxs/biibhr/external/jobs",
        "careers_url": "https://biibhr.wd3.myworkdayjobs.com/en-US/external",
        "location_filter": [],
    },
    "blackstone": {
        "name": "Blackstone",
        "api_url": "https://blackstone.wd1.myworkdayjobs.com/wday/cxs/blackstone/blackstone_Careers/jobs",
        "careers_url": "https://blackstone.wd1.myworkdayjobs.com/en-US/blackstone_Careers",
        "location_filter": [],
    },
    "broadridge": {
        "name": "Broadridge",
        "api_url": "https://broadridge.wd5.myworkdayjobs.com/wday/cxs/broadridge/Careers/jobs",
        "careers_url": "https://broadridge.wd5.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "cibc": {
        "name": "CIBC",
        "api_url": "https://cibc.wd3.myworkdayjobs.com/wday/cxs/cibc/search/jobs",
        "careers_url": "https://cibc.wd3.myworkdayjobs.com/en-US/search",
        "location_filter": [],
    },
    "erm": {
        "name": "ERM",
        "api_url": "https://erm.wd3.myworkdayjobs.com/wday/cxs/erm/erm_Careers/jobs",
        "careers_url": "https://erm.wd3.myworkdayjobs.com/en-US/erm_Careers",
        "location_filter": [],
    },
    "fca": {
        "name": "FCA (Financial Conduct Authority)",
        "api_url": "https://fca.wd3.myworkdayjobs.com/wday/cxs/fca/FCA_Careers/jobs",
        "careers_url": "https://fca.wd3.myworkdayjobs.com/en-US/FCA_Careers",
        "location_filter": [],
    },
    "fourseasons": {
        "name": "Four Seasons",
        "api_url": "https://fourseasons.wd3.myworkdayjobs.com/wday/cxs/fourseasons/search/jobs",
        "careers_url": "https://fourseasons.wd3.myworkdayjobs.com/en-US/search",
        "location_filter": [],
    },
    "gsk": {
        "name": "GSK",
        "api_url": "https://gsknch.wd3.myworkdayjobs.com/wday/cxs/gsknch/GSKCareers/jobs",
        "careers_url": "https://gsknch.wd3.myworkdayjobs.com/en-US/GSKCareers",
        "location_filter": [],
    },
    "jll": {
        "name": "JLL",
        "api_url": "https://jll.wd1.myworkdayjobs.com/wday/cxs/jll/jllcareers/jobs",
        "careers_url": "https://jll.wd1.myworkdayjobs.com/en-US/jllcareers",
        "location_filter": [],
    },
    "lseg": {
        "name": "London Stock Exchange Group",
        "api_url": "https://lseg.wd3.myworkdayjobs.com/wday/cxs/lseg/Careers/jobs",
        "careers_url": "https://lseg.wd3.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "novartis": {
        "name": "Novartis",
        "api_url": "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/Novartis_Careers/jobs",
        "careers_url": "https://novartis.wd3.myworkdayjobs.com/en-US/Novartis_Careers",
        "location_filter": [],
    },
    "wellcome": {
        "name": "Wellcome Trust",
        "api_url": "https://wellcome.wd3.myworkdayjobs.com/wday/cxs/wellcome/Wellcome/jobs",
        "careers_url": "https://wellcome.wd3.myworkdayjobs.com/en-US/Wellcome",
        "location_filter": [],
    },
    "wmeimg": {
        "name": "WME/IMG (Endeavor)",
        "api_url": "https://wmeimg.wd1.myworkdayjobs.com/wday/cxs/wmeimg/IMG/jobs",
        "careers_url": "https://wmeimg.wd1.myworkdayjobs.com/en-US/IMG",
        "location_filter": [],
    },
    "wmg": {
        "name": "Warner Music Group",
        "api_url": "https://wmg.wd1.myworkdayjobs.com/wday/cxs/wmg/WMGGLOBAL/jobs",
        "careers_url": "https://wmg.wd1.myworkdayjobs.com/en-US/WMGGLOBAL",
        "location_filter": [],
    },
    # ============================================================
    # Additional UK-Focused Companies
    # ============================================================
    "psr": {
        "name": "PSR (Payment Systems Regulator)",
        "api_url": "https://fca.wd3.myworkdayjobs.com/wday/cxs/fca/PSR_Careers/jobs",
        "careers_url": "https://fca.wd3.myworkdayjobs.com/en-US/PSR_Careers",
        "location_filter": [],
    },
    "ofcom": {
        "name": "Ofcom",
        "api_url": "https://ofcom.wd3.myworkdayjobs.com/wday/cxs/ofcom/Ofcom_Careers/jobs",
        "careers_url": "https://ofcom.wd3.myworkdayjobs.com/en-US/Ofcom_Careers",
        "location_filter": [],
    },
    "ico": {
        "name": "ICO (Information Commissioner's Office)",
        "api_url": "https://ico.wd3.myworkdayjobs.com/wday/cxs/ico/ICO/jobs",
        "careers_url": "https://ico.wd3.myworkdayjobs.com/en-GB/ICO",
        "location_filter": [],
    },
    "lloyds_tech": {
        "name": "Lloyds Banking Group (Technology)",
        "api_url": "https://lbg.wd3.myworkdayjobs.com/wday/cxs/lbg/Lloyds_Technology_Centre/jobs",
        "careers_url": "https://lbg.wd3.myworkdayjobs.com/en-US/Lloyds_Technology_Centre",
        "location_filter": [],
    },
    "hargreaves_lansdown": {
        "name": "Hargreaves Lansdown",
        "api_url": "https://hargreaveslansdown.wd3.myworkdayjobs.com/wday/cxs/hargreaveslansdown/HargreavesLansdown/jobs",
        "careers_url": "https://hargreaveslansdown.wd3.myworkdayjobs.com/en-US/HargreavesLansdown",
        "location_filter": [],
    },
    "baillie_gifford": {
        "name": "Baillie Gifford",
        "api_url": "https://bailliegifford.wd3.myworkdayjobs.com/wday/cxs/bailliegifford/BaillieGiffordCareers/jobs",
        "careers_url": "https://bailliegifford.wd3.myworkdayjobs.com/en-US/BaillieGiffordCareers",
        "location_filter": [],
    },
    "fnz": {
        "name": "FNZ",
        "api_url": "https://fnz.wd3.myworkdayjobs.com/wday/cxs/fnz/fnz_careers/jobs",
        "careers_url": "https://fnz.wd3.myworkdayjobs.com/en-US/fnz_careers",
        "location_filter": [],
    },
    "abrdn": {
        "name": "abrdn",
        "api_url": "https://abrdn.wd3.myworkdayjobs.com/wday/cxs/abrdn/abrdn/jobs",
        "careers_url": "https://abrdn.wd3.myworkdayjobs.com/en-US/abrdn",
        "location_filter": [],
    },
    "skipton": {
        "name": "Skipton Building Society",
        "api_url": "https://skipton.wd3.myworkdayjobs.com/wday/cxs/skipton/Careers-Skipton/jobs",
        "careers_url": "https://skipton.wd3.myworkdayjobs.com/en-US/Careers-Skipton",
        "location_filter": [],
    },
    "equiniti": {
        "name": "Equiniti",
        "api_url": "https://equiniti.wd3.myworkdayjobs.com/wday/cxs/equiniti/Opportunities/jobs",
        "careers_url": "https://equiniti.wd3.myworkdayjobs.com/en-US/Opportunities",
        "location_filter": [],
    },
    "newday": {
        "name": "NewDay",
        "api_url": "https://newday.wd3.myworkdayjobs.com/wday/cxs/newday/NewDay/jobs",
        "careers_url": "https://newday.wd3.myworkdayjobs.com/en-US/NewDay",
        "location_filter": [],
    },
    "lloyds_of_london": {
        "name": "Lloyd's of London",
        "api_url": "https://lloyds.wd3.myworkdayjobs.com/wday/cxs/lloyds/Lloyds-of-London/jobs",
        "careers_url": "https://lloyds.wd3.myworkdayjobs.com/en-US/Lloyds-of-London",
        "location_filter": [],
    },
    "hiscox": {
        "name": "Hiscox",
        "api_url": "https://hiscox.wd3.myworkdayjobs.com/wday/cxs/hiscox/Hiscox_External_Site/jobs",
        "careers_url": "https://hiscox.wd3.myworkdayjobs.com/en-US/Hiscox_External_Site",
        "location_filter": [],
    },
    "direct_line": {
        "name": "Direct Line Group",
        "api_url": "https://dlg.wd3.myworkdayjobs.com/wday/cxs/dlg/mediacom_external/jobs",
        "careers_url": "https://dlg.wd3.myworkdayjobs.com/en-US/mediacom_external",
        "location_filter": [],
    },
    "first_central": {
        "name": "First Central",
        "api_url": "https://firstcentral.wd3.myworkdayjobs.com/wday/cxs/firstcentral/External/jobs",
        "careers_url": "https://firstcentral.wd3.myworkdayjobs.com/en-US/External",
        "location_filter": [],
    },
    "ncc_group": {
        "name": "NCC Group",
        "api_url": "https://nccgroup.wd3.myworkdayjobs.com/wday/cxs/nccgroup/NCC_Group/jobs",
        "careers_url": "https://nccgroup.wd3.myworkdayjobs.com/en-US/NCC_Group",
        "location_filter": [],
    },
    "astrazeneca": {
        "name": "AstraZeneca",
        "api_url": "https://astrazeneca.wd3.myworkdayjobs.com/wday/cxs/astrazeneca/Careers/jobs",
        "careers_url": "https://astrazeneca.wd3.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "relx": {
        "name": "RELX",
        "api_url": "https://relx.wd3.myworkdayjobs.com/wday/cxs/relx/relx/jobs",
        "careers_url": "https://relx.wd3.myworkdayjobs.com/en-US/relx",
        "location_filter": [],
    },
    "cirium": {
        "name": "Cirium (RELX)",
        "api_url": "https://relx.wd3.myworkdayjobs.com/wday/cxs/relx/ciriumcareers/jobs",
        "careers_url": "https://relx.wd3.myworkdayjobs.com/en-US/ciriumcareers",
        "location_filter": [],
    },
    "john_lewis": {
        "name": "John Lewis Partnership",
        "api_url": "https://jlp.wd3.myworkdayjobs.com/wday/cxs/jlp/JLPjobs_careers/jobs",
        "careers_url": "https://jlp.wd3.myworkdayjobs.com/en-US/JLPjobs_careers",
        "location_filter": [],
    },
    "centrica": {
        "name": "Centrica",
        "api_url": "https://centrica.wd3.myworkdayjobs.com/wday/cxs/centrica/Centrica/jobs",
        "careers_url": "https://centrica.wd3.myworkdayjobs.com/en-US/Centrica",
        "location_filter": [],
    },
    "eon_next": {
        "name": "E.ON Next",
        "api_url": "https://eonnext.wd3.myworkdayjobs.com/wday/cxs/eonnext/EON_Next_Careers/jobs",
        "careers_url": "https://eonnext.wd3.myworkdayjobs.com/en-US/EON_Next_Careers",
        "location_filter": [],
    },
    "planet_payments": {
        "name": "Planet (Payments)",
        "api_url": "https://planet.wd3.myworkdayjobs.com/wday/cxs/planet/Planet/jobs",
        "careers_url": "https://planet.wd3.myworkdayjobs.com/en-US/Planet",
        "location_filter": [],
    },
    "flutter_uki": {
        "name": "Flutter (UKI)",
        "api_url": "https://flutterbe.wd3.myworkdayjobs.com/wday/cxs/flutterbe/FlutterUKI_External/jobs",
        "careers_url": "https://flutterbe.wd3.myworkdayjobs.com/en-US/FlutterUKI_External",
        "location_filter": [],
    },
    "capita": {
        "name": "Capita",
        "api_url": "https://capita.wd3.myworkdayjobs.com/wday/cxs/capita/CapitaGlobal/jobs",
        "careers_url": "https://capita.wd3.myworkdayjobs.com/en-US/CapitaGlobal",
        "location_filter": [],
    },
    "innovate_uk": {
        "name": "Innovate UK",
        "api_url": "https://innovateuk.wd3.myworkdayjobs.com/wday/cxs/innovateuk/innovateukcareers/jobs",
        "careers_url": "https://innovateuk.wd3.myworkdayjobs.com/en-US/innovateukcareers",
        "location_filter": [],
    },
    "national_archives": {
        "name": "The National Archives",
        "api_url": "https://nationalarchives.wd3.myworkdayjobs.com/wday/cxs/nationalarchives/Careers/jobs",
        "careers_url": "https://nationalarchives.wd3.myworkdayjobs.com/en-US/Careers",
        "location_filter": [],
    },
    "awe": {
        "name": "AWE (Atomic Weapons Establishment)",
        "api_url": "https://awepeople.wd3.myworkdayjobs.com/wday/cxs/awepeople/External_Careers/jobs",
        "careers_url": "https://awepeople.wd3.myworkdayjobs.com/en-US/External_Careers",
        "location_filter": [],
    },
    "cancer_research_uk": {
        "name": "Cancer Research UK",
        "api_url": "https://cancerresearchuk.wd3.myworkdayjobs.com/wday/cxs/cancerresearchuk/broadbean_external/jobs",
        "careers_url": "https://cancerresearchuk.wd3.myworkdayjobs.com/en-US/broadbean_external",
        "location_filter": [],
    },
    "johnson_matthey": {
        "name": "Johnson Matthey",
        "api_url": "https://matthey.wd3.myworkdayjobs.com/wday/cxs/matthey/Ext_Career_Site/jobs",
        "careers_url": "https://matthey.wd3.myworkdayjobs.com/en-US/Ext_Career_Site",
        "location_filter": [],
    },
    "renishaw": {
        "name": "Renishaw",
        "api_url": "https://renishaw.wd3.myworkdayjobs.com/wday/cxs/renishaw/Renishaw/jobs",
        "careers_url": "https://renishaw.wd3.myworkdayjobs.com/en-US/Renishaw",
        "location_filter": [],
    },
    "brompton": {
        "name": "Brompton Bicycle",
        "api_url": "https://brompton.wd3.myworkdayjobs.com/wday/cxs/brompton/Brompton/jobs",
        "careers_url": "https://brompton.wd3.myworkdayjobs.com/en-US/Brompton",
        "location_filter": [],
    },
}

# Common headers for Workday API
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_jobs(company_key: str, config: dict, location_search: str = None, max_jobs: int = 500, quiet: bool = False) -> list:
    """Fetch all jobs from a Workday company API."""
    jobs = []
    offset = 0
    limit = 20

    # Build payload
    payload = {
        "appliedFacets": {},
        "limit": limit,
        "offset": offset,
        "searchText": location_search or ""
    }

    # Add location filter if configured
    if config.get("location_filter"):
        payload["appliedFacets"]["locationCountry"] = config["location_filter"]

    if not quiet:
        print(f"Fetching jobs from {config['name']}...")

    while offset < max_jobs:
        payload["offset"] = offset

        try:
            response = requests.post(
                config["api_url"],
                headers=HEADERS,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            job_postings = data.get("jobPostings", [])
            total = data.get("total", 0)

            if not job_postings:
                break

            for job in job_postings:
                # Extract job_id from bulletFields (first item is usually the requisition ID)
                bullet_fields = job.get("bulletFields", [])
                job_id = bullet_fields[0] if bullet_fields else ""

                jobs.append({
                    "title": job.get("title", ""),
                    "location": job.get("locationsText", ""),
                    "posted_date": job.get("postedOn", ""),
                    "job_id": job_id,
                    "external_path": job.get("externalPath", ""),
                    # Additional fields from API
                    "remote_type": job.get("remoteType", ""),
                    "time_type": job.get("timeType", ""),
                    "job_family": job.get("jobFamilyGroup", []),
                    "job_category": job.get("jobCategory", ""),
                })

            if not quiet:
                print(f"  Fetched {len(jobs)}/{total} jobs...")

            if len(job_postings) < limit:
                break

            offset += limit
            time.sleep(0.5)  # Rate limiting

        except requests.RequestException as e:
            if not quiet:
                print(f"  Error fetching jobs: {e}")
            break

    return jobs


def fetch_job_details(company_key: str, config: dict, external_path: str) -> dict:
    """Fetch detailed job description from Workday API."""
    # The job detail URL follows a pattern
    base_url = config["api_url"].rsplit("/jobs", 1)[0]
    detail_url = f"{base_url}{external_path}"

    try:
        response = requests.get(detail_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()

        job_data = data.get("jobPostingInfo", {})
        return {
            "description": job_data.get("jobDescription", ""),
            "additional_info": job_data.get("additionalInfo", ""),
            "requirements": job_data.get("qualifications", ""),
            # Additional metadata from detail page
            "remote_type": job_data.get("remoteType", ""),
            "time_type": job_data.get("timeType", ""),
            "job_requisition_id": job_data.get("jobRequisitionId", "") or job_data.get("externalJobRequisitionId", ""),
            "start_date": job_data.get("startDate", ""),
            "end_date": job_data.get("endDate", ""),
            "job_schedule": job_data.get("jobSchedule", ""),
            "worker_type": job_data.get("workerType", ""),
            "worker_sub_type": job_data.get("workerSubType", ""),
        }
    except Exception as e:
        return {"description": "", "error": str(e)}


def scrape_company(company_key: str, location_search: str = None, fetch_descriptions: bool = True, quiet: bool = False) -> dict:
    """Scrape all jobs for a company. Use quiet=True for parallel execution."""
    if company_key not in WORKDAY_COMPANIES:
        if not quiet:
            print(f"Unknown company: {company_key}")
        return None

    config = WORKDAY_COMPANIES[company_key]

    if not quiet:
        print("=" * 60)
        print(f"{config['name'].upper()} JOB SCRAPER (Workday API)")
        print("=" * 60)

    # Fetch job listings
    jobs = fetch_jobs(company_key, config, location_search, quiet=quiet)

    if not jobs:
        if not quiet:
            print("No jobs found.")
        return {
            "company": config["name"],
            "scraped_at": datetime.now().isoformat(),
            "platform": "workday",
            "total_jobs": 0,
            "jobs": []
        }

    if not quiet:
        print(f"\nFound {len(jobs)} jobs")

    # Build full job URLs
    careers_base = config["careers_url"]
    for job in jobs:
        if job.get("external_path"):
            job["url"] = f"{careers_base}{job['external_path']}"
        else:
            job["url"] = careers_base

    # Fetch descriptions and additional details
    if fetch_descriptions:
        if not quiet:
            print("\nFetching job descriptions and details...")
        desc_count = 0
        for i, job in enumerate(jobs):
            if job.get("external_path"):
                if not quiet:
                    print(f"  [{i+1}/{len(jobs)}] {job['title'][:50]}...")
                details = fetch_job_details(company_key, config, job["external_path"])
                if details.get("description"):
                    job["description"] = details["description"]
                    desc_count += 1
                else:
                    job["description"] = ""
                # Merge additional metadata (prefer detail page values if available)
                if details.get("remote_type"):
                    job["remote_type"] = details["remote_type"]
                if details.get("time_type"):
                    job["time_type"] = details["time_type"]
                if details.get("job_requisition_id"):
                    job["job_requisition_id"] = details["job_requisition_id"]
                job["job_schedule"] = details.get("job_schedule", "")
                job["worker_type"] = details.get("worker_type", "")
                time.sleep(0.3)  # Rate limiting
            else:
                job["description"] = ""

        if not quiet:
            print(f"\nFetched {desc_count}/{len(jobs)} descriptions")
    else:
        for job in jobs:
            job["description"] = ""

    # Build output
    output = {
        "company": config["name"],
        "scraped_at": datetime.now().isoformat(),
        "platform": "workday",
        "careers_url": config["careers_url"],
        "total_jobs": len(jobs),
        "jobs_with_description": sum(1 for j in jobs if j.get("description")),
        "jobs": [{
            "title": j["title"],
            "location": j["location"],
            "url": j["url"],
            "job_id": j.get("job_id", ""),
            "job_requisition_id": j.get("job_requisition_id", j.get("job_id", "")),
            "posted_date": j.get("posted_date", ""),
            "remote_type": j.get("remote_type", ""),
            "time_type": j.get("time_type", ""),
            "job_schedule": j.get("job_schedule", ""),
            "worker_type": j.get("worker_type", ""),
            "job_family": j.get("job_family", []),
            "job_category": j.get("job_category", ""),
            "description": j.get("description", ""),
            "company": config["name"]
        } for j in jobs]
    }

    return output


def test_api(company_key: str):
    """Test if a Workday API endpoint is working."""
    if company_key not in WORKDAY_COMPANIES:
        print(f"Unknown company: {company_key}")
        return

    config = WORKDAY_COMPANIES[company_key]
    print(f"Testing {config['name']} API...")
    print(f"  URL: {config['api_url']}")

    payload = {
        "appliedFacets": {},
        "limit": 5,
        "offset": 0,
        "searchText": ""
    }

    try:
        response = requests.post(
            config["api_url"],
            headers=HEADERS,
            json=payload,
            timeout=30
        )
        print(f"  Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            total = data.get("total", 0)
            jobs = data.get("jobPostings", [])
            print(f"  Total jobs available: {total}")
            if jobs:
                print(f"  Sample job: {jobs[0].get('title', 'N/A')}")
            print("  API is working!")
        else:
            print(f"  Response: {response.text[:200]}")
    except Exception as e:
        print(f"  Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Workday Job Scraper")
    parser.add_argument("--company", "-c", help="Scrape specific company")
    parser.add_argument("--list", "-l", action="store_true", help="List available companies")
    parser.add_argument("--test", "-t", help="Test API endpoint for a company")
    parser.add_argument("--search", "-s", help="Search text (e.g., 'London', 'Engineer')")
    parser.add_argument("--no-desc", action="store_true", help="Skip fetching descriptions")
    parser.add_argument("--all", "-a", action="store_true", help="Scrape all companies")
    parser.add_argument("--parallel", "-p", action="store_true", help="Scrape companies in parallel")
    parser.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS,
                        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    if args.list:
        print("Available Workday companies:")
        for key, config in WORKDAY_COMPANIES.items():
            print(f"  {key:15} - {config['name']}")
        return

    if args.test:
        test_api(args.test)
        return

    companies_to_scrape = []

    if args.company:
        companies_to_scrape = [args.company]
    elif args.all:
        companies_to_scrape = list(WORKDAY_COMPANIES.keys())
    else:
        # Default: test with nvidia
        print("No company specified. Use --company NAME or --all")
        print("Use --list to see available companies")
        return

    def process_company(company_key, quiet=False):
        """Process a single company and save results."""
        result = scrape_company(
            company_key,
            location_search=args.search,
            fetch_descriptions=not args.no_desc,
            quiet=quiet
        )

        if result and result["total_jobs"] > 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = OUTPUT_DIR / f"{company_key}_workday_{timestamp}.json"

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            return company_key, result["total_jobs"], result.get("jobs_with_description", 0), output_file
        return company_key, 0, 0, None

    if args.parallel and len(companies_to_scrape) > 1:
        # Parallel execution with clean output
        print(f"\nScraping {len(companies_to_scrape)} companies in PARALLEL ({args.workers} workers)...")
        print("-" * 60)
        results_summary = []
        completed = 0

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_company, key, quiet=True): key for key in companies_to_scrape}

            for future in as_completed(futures):
                company_key = futures[future]
                completed += 1
                try:
                    key, count, desc_count, output_file = future.result()
                    results_summary.append((key, count, desc_count, output_file))
                    name = WORKDAY_COMPANIES[key]['name']
                    if count > 0:
                        print(f"[{completed:3}/{len(companies_to_scrape)}] {name:30} {count:4} jobs ({desc_count} with desc)")
                    else:
                        print(f"[{completed:3}/{len(companies_to_scrape)}] {name:30}    0 jobs")
                except Exception as e:
                    print(f"[{completed:3}/{len(companies_to_scrape)}] {company_key:30} ERROR: {str(e)[:30]}")
                    results_summary.append((company_key, 0, 0, None))

        # Final summary
        print("-" * 60)
        total_jobs = sum(r[1] for r in results_summary)
        total_desc = sum(r[2] for r in results_summary)
        successful = sum(1 for r in results_summary if r[1] > 0)
        failed = len(companies_to_scrape) - successful
        print(f"DONE: {successful} companies, {total_jobs} jobs ({total_desc} with descriptions)")
        if failed > 0:
            print(f"FAILED: {failed} companies")
    else:
        # Sequential execution
        for company_key in companies_to_scrape:
            result = scrape_company(
                company_key,
                location_search=args.search,
                fetch_descriptions=not args.no_desc
            )

            if result and result["total_jobs"] > 0:
                # Save output
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = OUTPUT_DIR / f"{company_key}_workday_{timestamp}.json"

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)

                print(f"\nSaved to {output_file}")

                # Summary
                print("\n" + "=" * 60)
                print("SUMMARY")
                print("=" * 60)
                for job in result["jobs"][:5]:
                    print(f"- {job['title'][:40]}")
                    print(f"  {job['location']}")
                    if job.get("description"):
                        print(f"  {job['description'][:50]}...")
                if len(result["jobs"]) > 5:
                    print(f"\n... and {len(result['jobs']) - 5} more jobs")


if __name__ == "__main__":
    main()
