#!/usr/bin/env python3
"""Resolve catalog search placeholders to official career pages and public ATS feeds."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import pprint
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from product_company_career_catalog import NON_STARTUP_PRODUCT_COMPANY_CAREER_PAGE_URLS
from resolved_product_company_career_targets import RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS

OUTPUT_PATH = REPO_ROOT / "resolved_product_company_career_targets.py"
USER_AGENT = "Mozilla/5.0 (compatible; JobTrackCareerResolver/1.0)"
SEARCH_URL = "https://www.bing.com/search?q={}"
PUBLIC_ATS_DATASET_URL = "https://www.atsresumeai.com/research/ats-2026/sp500-ats-map.csv"
GOOGLE_PLACEHOLDER = "www.google.com/search"
CAREER_WORDS = ("career", "careers", "job", "jobs", "openings", "opportunities")
BLOCKED_HOSTS = {
    "bing.com", "facebook.com", "glassdoor.com", "google.com", "indeed.com",
    "instagram.com", "linkedin.com", "monster.com", "wikipedia.org", "x.com",
    "youtube.com", "ziprecruiter.com",
}
LEGAL_WORDS = {
    "class", "company", "corporation", "corp", "group", "holding", "holdings",
    "inc", "limited", "ltd", "plc", "the",
}
GLOBAL_DOMAIN_HINTS = {
    "Flex Ltd.": "flex.com", "Honeywell Aerospace": "honeywell.com",
    "Honeywell Technologies": "honeywell.com", "Marvell Technology": "marvell.com",
    "ASML Holding": "asml.com", "Taiwan Semiconductor Manufacturing Company": "tsmc.com",
    "Samsung Electronics": "samsung.com", "Sony Group": "sony.com", "Nintendo": "nintendo.com",
    "Toyota Motor Corporation": "global.toyota", "Honda Motor Company": "global.honda",
    "Hyundai Motor Company": "hyundai.com", "Kia Corporation": "kia.com", "LG Electronics": "lg.com",
    "SK Hynix": "skhynix.com", "Panasonic Holdings": "holdings.panasonic",
    "Canon": "global.canon", "Fujitsu": "fujitsu.com", "NEC Corporation": "nec.com",
    "Toshiba": "global.toshiba", "Hitachi Ltd.": "hitachi.com",
    "Mitsubishi Electric": "mitsubishielectric.com", "Schindler Group": "schindler.com",
    "ABB Ltd.": "global.abb", "STMicroelectronics": "st.com", "Infineon Technologies": "infineon.com",
    "ASM International": "asm.com", "BE Semiconductor Industries": "besi.com",
    "Tokyo Electron": "tel.com", "Disco Corporation": "disco.co.jp", "Advantest": "advantest.com",
    "Renesas Electronics": "renesas.com", "MediaTek": "mediatek.com", "Tencent": "tencent.com",
    "Alibaba Group Holding": "alibabagroup.com", "Baidu": "baidu.com", "JD.com": "jd.com",
    "NetEase": "netease.com", "Meituan": "meituan.com", "Mercado Libre": "mercadolibre.com",
    "Shopify": "shopify.com", "Spotify": "spotifyjobs.com", "Yandex": "yandex.com",
    "Rakuten Group": "global.rakuten.com", "Naver": "navercorp.com", "Kakao": "kakaocorp.com",
    "Sea Limited Ltd.": "sea.com",
}
GLOBAL_CAREER_URLS = {
    "Flex Ltd.": "https://flex.com/careers",
    "Honeywell Aerospace": "https://careers.honeywell.com/us/en",
    "Honeywell Technologies": "https://careers.honeywell.com/us/en",
    "Marvell Technology": "https://marvell.wd1.myworkdayjobs.com/MarvellCareers",
    "ASML Holding": "https://www.asml.com/en/careers",
    "Taiwan Semiconductor Manufacturing Company": "https://jobs.tsmc.com/en-US",
    "Samsung Electronics": "https://sec.wd3.myworkdayjobs.com/Samsung_Careers",
    "Sony Group": "https://www.sony.com/en/SonyInfo/Careers/",
    "Nintendo": "https://careers.nintendo.com/",
    "Toyota Motor Corporation": "https://careers.toyota.com/",
    "Honda Motor Company": "https://careers.honda.com/",
    "Hyundai Motor Company": "https://careers.hyundaimotorgroup.com/",
    "Kia Corporation": "https://careers.kia.com/",
    "LG Electronics": "https://careers.lg.com/",
    "SK Hynix": "https://recruit.skhynix.com/",
    "Panasonic Holdings": "https://careers.na.panasonic.com/",
    "Canon": "https://www.usa.canon.com/about-us/careers",
    "Fujitsu": "https://global.fujitsu/en-us/careers",
    "NEC Corporation": "https://careers.nec.com/",
    "Toshiba": "https://www.global.toshiba/ww/recruit/corporate.html",
    "Hitachi Ltd.": "https://careers.hitachi.com/",
    "Mitsubishi Electric": "https://www.mitsubishielectric.com/en/careers/",
    "Schindler Group": "https://group.schindler.com/en/careers.html",
    "ABB Ltd.": "https://careers.abb/global/en",
    "STMicroelectronics": "https://stmicroelectronics.eightfold.ai/careers",
    "Infineon Technologies": "https://www.infineon.com/careers",
    "ASM International": "https://www.asm.com/careers",
    "BE Semiconductor Industries": "https://www.besi.com/careers/a-career-at-besi/",
    "Tokyo Electron": "https://www.tel.com/careers/",
    "Disco Corporation": "https://www.disco.co.jp/recruit/",
    "Advantest": "https://www.advantest.com/careers/",
    "Renesas Electronics": "https://jobs.renesas.com/",
    "MediaTek": "https://careers.mediatek.com/en",
    "Tencent": "https://careers.tencent.com/",
    "Alibaba Group Holding": "https://www.alibabagroup.com/en-US/careers",
    "Baidu": "https://talent.baidu.com/jobs/list",
    "JD.com": "https://zhaopin.jd.com/",
    "NetEase": "https://hr.163.com/job-list.html",
    "Meituan": "https://careers.meituan.com/web/home",
    "Mercado Libre": "https://mercadolibre.com/jobs",
    "Shopify": "https://www.shopify.com/careers",
    "Spotify": "https://www.lifeatspotify.com/jobs",
    "Yandex": "https://yandex.com/jobs",
    "Rakuten Group": "https://global.rakuten.com/corp/careers/",
    "Naver": "https://recruit.navercorp.com/",
    "Kakao": "https://careers.kakao.com/index",
    "Sea Limited Ltd.": "https://www.sea.com/careers",
}
GLOBAL_CAREER_URLS.update({
    "Ameren": "https://ameren.wd1.myworkdayjobs.com/External",
    "American Electric Power": "https://www.aep.com/careers/",
    "Analog Devices": "https://careers.analog.com/",
    "Archer Daniels Midland": "https://www.adm.com/en-us/culture-and-careers/",
    "Ares Management": "https://www.aresmgmt.com/careers",
    "Arthur J. Gallagher & Co.": "https://jobs.ajg.com/",
    "Automatic Data Processing": "https://jobs.adp.com/",
    "AvalonBay Communities": "https://jobs.avalonbay.com/",
    "Becton Dickinson": "https://jobs.bd.com/",
    "Bio-Techne": "https://careers.bio-techne.com/",
    "Booking Holdings": "https://careers.booking.com/",
    "Broadridge Financial Solutions": "https://broadridge.wd5.myworkdayjobs.com/Careers",
    "Bunge Global": "https://www.bunge.com/Careers",
    "CDW Corporation": "https://www.cdwjobs.com/",
    "CME Group": "https://jobs.cmegroup.com/",
    "CMS Energy": "https://www.cmsenergy.com/careers/",
    "CSX Corporation": "https://www.csx.com/index.cfm/working-at-csx/",
    "Cadence Design Systems": "https://cadence.wd1.myworkdayjobs.com/External_Careers",
    "Carrier Global": "https://jobs.carrier.com/en",
    "Casey's": "https://careers.caseys.com/",
    "Caterpillar Inc.": "https://cat.wd5.myworkdayjobs.com/CaterpillarCareers",
    "Charles Schwab Corporation": "https://www.schwabjobs.com/",
    "Charter Communications": "https://jobs.spectrum.com/",
    "Ciena": "https://careers.ciena.com/",
    "Cintas": "https://www.cintas.com/careers/",
    "Clorox": "https://www.thecloroxcompany.com/careers/",
    "Colgate-Palmolive": "https://jobs.colgate.com/",
    "Cooper Companies (The)": "https://careers.coopercos.com/",
    "Corpay": "https://corpay.wd103.myworkdayjobs.com/Ext_001",
    "Deckers Brands": "https://deckers.wd5.myworkdayjobs.com/Deckers",
    "Diamondback Energy": "https://www.diamondbackenergy.com/careers",
    "DoorDash": "https://careersatdoordash.com/",
    "Dover Corporation": "https://www.dovercorporation.com/about-us/careers/",
    "Duke Energy": "https://dukeenergy.wd1.myworkdayjobs.com/search",
    "Emerson Electric": "https://www.emerson.com/en-us/careers",
    "Erie Indemnity": "https://careers.erieinsurance.com/",
    "Evergy": "https://jobs.evergy.com/",
    "Expeditors International": "https://www.expeditors.com/careers",
    "Fidelity National Information Services": "https://careers.fisglobal.com/",
    "Fifth Third Bancorp": "https://fifththird.wd5.myworkdayjobs.com/53careers",
    "Fox Corporation (Class A)": "https://www.foxcareers.com/",
    "GE HealthCare": "https://careers.gehealthcare.com/global/en",
    "Gartner": "https://jobs.gartner.com/",
    "General Motors": "https://search-careers.gm.com/en/jobs/",
    "Global Payments": "https://jobs.globalpayments.com/",
    "HCA Healthcare": "https://careers.hcahealthcare.com/",
    "Hartford (The)": "https://thehartford.wd5.myworkdayjobs.com/Careers_External",
    "Howmet Aerospace": "https://fa-exty-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1",
    "Huntington Bancshares": "https://huntington-careers.com/",
    "Huntington Ingalls Industries": "https://careers.huntingtoningalls.com/",
    "Illinois Tool Works": "https://careers.itw.com/",
    "Ingersoll Rand": "https://careers.irco.com/",
    "Insulet Corporation": "https://insulet.wd5.myworkdayjobs.com/insuletcareers",
    "J.M. Smucker Company (The)": "https://jobs.jmsmucker.com/",
    "Keurig Dr Pepper": "https://careers.keurigdrpepper.com/en",
    "KeyCorp": "https://www.key.com/about/careers.html",
    "Kimberly-Clark": "https://www.careersatkc.com/",
    "Las Vegas Sands": "https://sands.wd1.myworkdayjobs.com/sands_careers",
    "Lululemon Athletica": "https://careers.lululemon.com/",
    "Marathon Petroleum": "https://mpc.wd1.myworkdayjobs.com/MPCCareers",
    "Meta Platforms": "https://www.metacareers.com/",
    "Mid-America Apartment Communities": "https://careers.maac.com/",
    "Monster Beverage": "https://www.monsterbevcorp.com/careers.php",
    "NVR, Inc.": "https://www.nvrcareers.com/",
    "News Corp (Class A)": "https://newscorp.com/careers/",
    "News Corp (Class B)": "https://newscorp.com/careers/",
    "Nordson Corporation": "https://nordsoncareers.com/",
    "Norwegian Cruise Line Holdings": "https://www.ncl.com/about/careers",
    "Nvidia": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "Occidental Petroleum": "https://careers.oxy.com/",
    "Omnicom Group": "https://indiacareers.omnicomglobalsolutions.com/jobs",
    "Otis Worldwide": "https://otis.wd5.myworkdayjobs.com/REC_Ext_Gateway",
    "O’Reilly Automotive": "https://careers.oreillyauto.com/",
    "PPL Corporation": "https://ppluk.wd3.myworkdayjobs.com/PPL_External_Careers",
    "Packaging Corporation of America": "https://www.packagingcorp.com/employment",
    "Paramount Skydance Corporation": "https://careers.paramount.com/",
    "Pinnacle West Capital": "https://careers.aps.com/",
    "Prologis": "https://www.prologis.com/about/careers",
    "PulteGroup": "https://careers.pultegroup.com/",
    "Regeneron Pharmaceuticals": "https://careers.regeneron.com/",
    "Revvity": "https://jobs.revvity.com/",
    "Robinhood Markets": "https://careers.robinhood.com/",
    "Roper Technologies": "https://www.ropertech.com/careers",
    "Royal Caribbean Group": "https://careers.royalcaribbeangroup.com/",
    "Sempra": "https://www.sempra.com/careers",
    "Solventum": "https://healthcare.wd1.myworkdayjobs.com/Search",
    "Stanley Black & Decker": "https://www.stanleyblackanddecker.com/careers",
    "Synchrony Financial": "https://www.synchronycareers.com/",
    "T-Mobile US": "https://tmobile.wd1.myworkdayjobs.com/External",
    "Tesla, Inc.": "https://www.tesla.com/careers/search/",
    "Texas Pacific Land Corporation": "https://recruiting.paylocity.com/recruiting/jobs/All/8cb850d5-bd0b-4ad3-a676-06b1a9cf2fac/Texas-Pacific-Land-Corporation",
    "Tractor Supply": "https://www.tractorsupply.careers/",
    "Trade Desk (The)": "https://careers.thetradedesk.com/",
    "Travelers Companies (The)": "https://travelers.wd5.myworkdayjobs.com/External",
    "Tyson Foods": "https://tysonfoods.wd5.myworkdayjobs.com/TSN",
    "United Parcel Service": "https://www.jobs-ups.com/",
    "Universal Health Services": "https://jobs.uhsinc.com/",
    "Ventas": "https://www.ventasreit.com/careers",
    "Veralto": "https://jobs.veralto.com/global/en",
    "Verisk Analytics": "https://www.verisk.com/company/careers/",
    "Vertex Pharmaceuticals": "https://vrtx.wd501.myworkdayjobs.com/vertex_careers",
    "W. W. Grainger": "https://jobs.grainger.com/",
    "Williams Companies": "https://williams.wd5.myworkdayjobs.com/External",
    "Willis Towers Watson": "https://careers.wtwco.com/",
    "Zoetis": "https://zoetis.wd5.myworkdayjobs.com/zoetis",
})


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _company_tokens(name: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if len(token) > 2 and token not in LEGAL_WORDS
    ]


def _normalized_company(name: str) -> str:
    return "".join(
        token for token in re.findall(r"[a-z0-9]+", name.lower())
        if token not in LEGAL_WORDS
    )


def _load_public_dataset(session: requests.Session) -> dict[str, dict[str, str]]:
    import csv
    import io

    response = session.get(PUBLIC_ATS_DATASET_URL, timeout=30)
    response.raise_for_status()
    return {
        _normalized_company(row.get("company") or ""): row
        for row in csv.DictReader(io.StringIO(response.text))
        if row.get("company") and (row.get("careers_url") or row.get("domain"))
    }


def _blocked(url: str) -> bool:
    host = _host(url)
    return not host or any(host == item or host.endswith(f".{item}") for item in BLOCKED_HOSTS)


def _decode_bing_url(url: str) -> str:
    encoded = parse_qs(urlparse(url).query).get("u", [""])[0]
    if not encoded.startswith("a1"):
        return url
    raw = encoded[2:]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return url


def _search(company: str, session: requests.Session) -> list[SearchResult]:
    query = quote(f'"{company}" official careers jobs')
    response = session.get(SEARCH_URL.format(query), timeout=20)
    response.raise_for_status()
    results: list[SearchResult] = []
    for anchor in BeautifulSoup(response.text, "html.parser").select("li.b_algo h2 a[href]"):
        url = _decode_bing_url(str(anchor.get("href") or ""))
        if url.startswith("http") and not _blocked(url):
            results.append(SearchResult(anchor.get_text(" ", strip=True), url))
    return results


def _candidate_score(company: str, result: SearchResult) -> int:
    host = _host(result.url)
    text = f"{result.title} {result.url}".lower()
    tokens = _company_tokens(company)
    score = sum(5 for token in tokens if token in host)
    score += sum(2 for token in tokens if token in result.title.lower())
    score += 12 if any(word in text for word in CAREER_WORDS) else 0
    score += 15 if _detect_ats(result.url) else 0
    return score


def _clean_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def _same_company_domain(url: str, domain: str) -> bool:
    host = _host(url)
    expected = domain.lower().removeprefix("www.")
    return bool(host and expected and (host == expected or host.endswith(f".{expected}")))


def _career_links(page_url: str, html: str) -> list[SearchResult]:
    links: list[SearchResult] = []
    for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
        title = anchor.get_text(" ", strip=True)
        href = urljoin(page_url, str(anchor.get("href") or ""))
        text = f"{title} {href}".lower()
        if href.startswith("http") and not _blocked(href) and any(word in text for word in CAREER_WORDS):
            links.append(SearchResult(title, href))
    return links


def _detect_ats(url: str) -> dict[str, object] | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host.endswith("myworkdayjobs.com") and parts:
        tenant = host.split(".", 1)[0].split("wd", 1)[0]
        site = next(
            (part for part in parts if part.lower() not in {"en-us", "en_us", "en", "jobs", "login"}),
            "",
        )
        if tenant and site:
            return {"ats": "workday", "host": host, "tenant": tenant, "site": site}
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parts:
        return {"ats": "greenhouse", "slug": parts[0]}
    if host == "jobs.lever.co" and parts:
        return {"ats": "lever", "slug": parts[0]}
    if host == "jobs.ashbyhq.com" and parts:
        return {"ats": "ashby", "slug": parts[0]}
    if host == "jobs.smartrecruiters.com" and parts:
        return {"ats": "smartrecruiters", "slug": parts[0]}
    return None


def _fetch(session: requests.Session, url: str) -> tuple[str, str] | None:
    try:
        response = session.get(url, timeout=20, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            return None
        return _clean_url(response.url), response.text
    except requests.RequestException:
        return None


def _resolve_candidates(
    company: str,
    candidates: list[SearchResult],
    session: requests.Session,
    detected_ats: str = "",
) -> tuple[str, dict[str, object] | None, str]:
    for candidate in candidates:
        ats = _detect_ats(candidate.url)
        if ats:
            return company, {"career_url": _clean_url(candidate.url), **ats}, "ats URL"

    for candidate in candidates:
        fetched = _fetch(session, candidate.url)
        if not fetched:
            continue
        final_url, html = fetched
        page_links = sorted(
            _career_links(final_url, html),
            key=lambda item: _candidate_score(company, item),
            reverse=True,
        )
        for link in page_links:
            ats = _detect_ats(link.url)
            if ats:
                return company, {"career_url": _clean_url(link.url), **ats}, "ats link"
        if page_links:
            chosen = page_links[0].url
            fetched_career = _fetch(session, chosen)
            career_url, career_html = fetched_career or (_clean_url(chosen), "")
            for link in _career_links(career_url, career_html):
                ats = _detect_ats(link.url)
                if ats:
                    return company, {"career_url": _clean_url(link.url), **ats}, "ats on careers page"
            target: dict[str, object] = {"career_url": career_url, "ats": "html"}
            if detected_ats:
                target["detected_ats"] = detected_ats
            return company, target, "official careers page"

        page_title = BeautifulSoup(html, "html.parser").title
        identity_text = f"{final_url} {page_title.get_text(' ', strip=True) if page_title else ''}".lower()
        if not detected_ats and not any(word in identity_text for word in CAREER_WORDS):
            continue
        target = {"career_url": final_url, "ats": "html"}
        if detected_ats:
            target["detected_ats"] = detected_ats
        return company, target, "verified official careers URL"
    return company, None, "official careers page not reachable"


def _resolve_one(company: str, dataset_row: dict[str, str] | None) -> tuple[str, dict[str, object] | None, str]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})

    if dataset_row:
        career_url = dataset_row.get("ats_url") or dataset_row.get("careers_url") or ""
        if career_url:
            ats = _detect_ats(career_url)
            if ats:
                return company, {"career_url": _clean_url(career_url), **ats}, "published ATS URL"
            target: dict[str, object] = {"career_url": _clean_url(career_url), "ats": "html"}
            if dataset_row.get("ats"):
                target["detected_ats"] = dataset_row["ats"]
            return company, target, "published careers dataset"

    domain = GLOBAL_DOMAIN_HINTS.get(company) or (dataset_row or {}).get("domain")
    if domain:
        probes = [
            SearchResult(f"{company} careers", f"https://{domain}/careers"),
            SearchResult(f"{company} jobs", f"https://{domain}/jobs"),
            SearchResult(f"{company} careers", f"https://careers.{domain}"),
            SearchResult(f"{company} jobs", f"https://jobs.{domain}"),
        ]
        resolved = _resolve_candidates(company, probes, session)
        if resolved[1]:
            return resolved

    try:
        results = _search(company, session)
    except requests.RequestException as exc:
        return company, None, f"search failed: {exc}"
    ranked = sorted(results, key=lambda item: _candidate_score(company, item), reverse=True)
    if not ranked or _candidate_score(company, ranked[0]) < 7:
        return company, None, "no confident official domain"

    return _resolve_candidates(company, ranked[:4], session)


def _render(entries: dict[str, dict[str, object]]) -> str:
    formatted = pprint.pformat(dict(sorted(entries.items())), width=120, sort_dicts=False)
    return (
        '"""Verified product-company career targets generated by the resolver script.\n\n'
        "Regenerate with: python scripts/resolve_product_company_careers.py\n"
        '"""\n\n'
        f"RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS: dict[str, dict[str, object]] = {formatted}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--trusted-only",
        action="store_true",
        help="Write only published, curated, or exact official-domain matches without web discovery.",
    )
    args = parser.parse_args()
    companies = [
        name for name, url in NON_STARTUP_PRODUCT_COMPANY_CAREER_PAGE_URLS.items()
        if GOOGLE_PLACEHOLDER in url.lower()
    ]
    if args.limit > 0:
        companies = companies[: args.limit]

    dataset_session = requests.Session()
    dataset_session.headers.update({"User-Agent": USER_AGENT})
    try:
        dataset = _load_public_dataset(dataset_session)
    except requests.RequestException as exc:
        print(f"Warning: public careers dataset unavailable: {exc}")
        dataset = {}

    resolved: dict[str, dict[str, object]] = {}
    for company in companies:
        dataset_row = dataset.get(_normalized_company(company)) or {}
        published_url = dataset_row.get("careers_url") or ""
        curated_url = GLOBAL_CAREER_URLS.get(company) or ""
        chosen_url = curated_url or published_url
        if chosen_url:
            ats = _detect_ats(chosen_url)
            target: dict[str, object] = {"career_url": _clean_url(chosen_url), **(ats or {"ats": "html"})}
            if not ats and dataset_row.get("ats"):
                target["detected_ats"] = dataset_row["ats"]
            resolved[company] = target
            continue

        existing = RESOLVED_PRODUCT_COMPANY_CAREER_TARGETS.get(company)
        official_domain = dataset_row.get("domain") or GLOBAL_DOMAIN_HINTS.get(company) or ""
        if (
            isinstance(existing, dict)
            and existing.get("career_url")
            and _same_company_domain(str(existing["career_url"]), official_domain)
        ):
            resolved[company] = dict(existing)
    failures: list[tuple[str, str]] = []
    pending_companies = [] if args.trusted_only else [company for company in companies if company not in resolved]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(_resolve_one, company, dataset.get(_normalized_company(company))): company
            for company in pending_companies
        }
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            company, target, reason = future.result()
            if target:
                resolved[company] = target
            else:
                failures.append((company, reason))
            if index % 25 == 0 or index == len(pending_companies):
                print(
                    f"Processed {index}/{len(pending_companies)} pending; "
                    f"resolved_total={len(resolved)} unresolved={len(failures)}",
                    flush=True,
                )

    OUTPUT_PATH.write_text(_render(resolved), encoding="utf-8")
    unresolved_companies = [company for company in companies if company not in resolved]
    print(f"Wrote {len(resolved)} verified targets to {OUTPUT_PATH}")
    print(f"Unresolved: {len(unresolved_companies)}; elapsed: {time.monotonic() - started:.1f}s")
    for company, reason in failures:
        print(f"UNRESOLVED\t{company}\t{reason}")
    for company in unresolved_companies:
        if not any(item[0] == company for item in failures):
            print(f"UNRESOLVED\t{company}\tno verified central careers feed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
