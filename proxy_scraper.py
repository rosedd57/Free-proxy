import requests
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import random
import socket
from urllib.parse import urljoin, urlparse, parse_qs, urlencode # Updated for parsing URLs

# --- Configuration ---
PROXY_TEST_URL = "http://www.google.com" # Proxy test ke liye URL
TIMEOUT = 20 # Request timeout in seconds (bad proxies ke liye zyada wait na kare)
MAX_WORKERS = 150 # Proxy testing ke liye concurrent workers
OUTPUT_FILE = "working_proxies.txt" # Valid proxies save karne ki file
SCRAPING_CONCURRENCY = 3 # Ek saath kitni websites scrape honge (avoid overwhelming sites)
SCRAPING_DELAY = 3 # Har page request ke beech mein delay (per site)
MAX_SCRAPING_PAGES = 7 # Har site से kitne pages scrape karne hain (avoid infinite loops, increase from 5)
RETRY_ATTEMPTS = 3 # Kitni baar request retry kare (403 ya connection errors ke liye)
RETRY_DELAY = 5 # Retry ke beech mein kitna wait kare
# --- End Configuration ---

# Free/Public DNSBL servers for basic blacklist check
FREE_DNSBL_SERVERS = [
    "zen.spamhaus.org",
    "bl.spamcop.net",
    "dnsbl.sorbs.net",
    "b.barracudacentral.org"
]

# Random User-Agents to mimic different browsers and avoid detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36 Edg/95.0.1020.44",
    "Mozilla/5.0 (Android 10; Mobile; rv:91.0) Gecko/91.0 Firefox/91.0",
    "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.210 Mobile Safari/537.36"
]

# --- Websites to Scrape ---
# Har entry mein 'base_url', 'ip_port_selector', 'ip_index', 'port_index' zaroori hain.
# 'pagination_selector' ya 'pagination_type' pagination ke liye hain.
# Agar koi site JS se content load karti hai, toh yeh code uske liye kaam nahi karega.
# Selectors ko latest check ke hisaab se update kiya gaya hai, phir bhi manual verification zaroori hai.
SCRAPING_TARGETS = {
    # Working Examples (verified and updated selectors)
    "free-proxy-list.net": {
        "base_url": "https://free-proxy-list.net/",
        "ip_port_selector": "table#proxylisttable tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "div#list div.btn-group a.paginate.btn:contains('Next')",
    },
    "hidemy.name": {
        "base_url": "https://hidemy.name/en/proxy-list/",
        "ip_port_selector": "table.proxy__t tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_type": "offset",
        "offset_param": "start",
        "offset_step": 64,
        "max_pages_to_scrape": MAX_SCRAPING_PAGES,
    },
    "freeproxy.world": { # Often gives 403, increased retry attempts might help
        "base_url": "https://www.freeproxy.world/",
        "ip_port_selector": "table.table-striped tbody tr", # Changed from table.table
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a[rel='next']",
    },
    "vpnside.com": {
        "base_url": "https://www.vpnside.com/proxy/list/",
        "ip_port_selector": "table.table.table-hover tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a[rel='next']",
    },
    "proxyelite.info": { # Often gives 403
        "base_url": "https://proxyelite.info/free-proxy-list/",
        "ip_port_selector": "table.table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('Next')",
    },
    "free-proxy-list.net_socks": {
        "base_url": "https://free-proxy-list.net/en/socks-proxy.html",
        "ip_port_selector": "table#proxylisttable tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "div#list div.btn-group a.paginate.btn:contains('Next')",
    },
    # New Sites (selectors adjusted based on common patterns, may need manual fine-tuning)
    "openproxylist.com": {
        "base_url": "https://openproxylist.com/",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "a[aria-label='Next Page']", # Common for modern sites, check 'Next' or 'Next Page'
    },
    "proxyhub.me": {
        "base_url": "https://proxyhub.me/en/all-https-proxy-list.html",
        "ip_port_selector": "table.table.table-striped tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('>')",
    },
    "proxybros.com": {
        "base_url": "https://proxybros.com/free-proxy-list/",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "proxydb.net": {
        "base_url": "https://proxydb.net/",
        "ip_port_selector": "table.table-striped tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "a[aria-label='Next']",
    },
    "proxiware.com": { # Often gives 403
        "base_url": "https://proxiware.com/free-proxy-list",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "fineproxy.org": { # Often gives 403
        "base_url": "https://fineproxy.org/free-proxy/",
        "ip_port_selector": "table.proxy-list tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "div.pagination a:contains('Next')",
    },
    "www.proxyrack.com": {
        "base_url": "https://www.proxyrack.com/free-proxy-list/",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "www.lunaproxy.com": { # Likely JS, but trying HTML
        "base_url": "https://www.lunaproxy.com/freeproxy/index.html",
        "ip_port_selector": "table.ant-table-body tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "li.ant-pagination-next a",
    },
    "www.proxy-list.download": {
        "base_url": "https://www.proxy-list.download/SOCKS5",
        "ip_port_selector": "table.table-striped tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('Next')",
    },
    "proxycompass.com": { # Often gives 403
        "base_url": "https://proxycompass.com/free-proxy/",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "advanced.name": {
        "base_url": "https://advanced.name/freeproxy",
        "ip_port_selector": "table.table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "www.iplocation.net": {
        "base_url": "https://www.iplocation.net/proxy-list",
        "ip_port_selector": "table.table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "hide.mn": { # Fixed for parse_qs error
        "base_url": "https://hide.mn/en/proxy-list",
        "ip_port_selector": "table.proxy__t tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_type": "offset", "offset_param": "start", "offset_step": 64,
        "max_pages_to_scrape": MAX_SCRAPING_PAGES,
    },
    "proxy5.net": { # Often gives 403
        "base_url": "https://proxy5.net/free-proxy",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "freeproxyupdate.com": {
        "base_url": "https://freeproxyupdate.com/",
        "ip_port_selector": "table.table.table-striped tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "www.ditatompel.com": {
        "base_url": "https://www.ditatompel.com/proxy",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "hideip.me": { # Fixed for parse_qs error
        "base_url": "https://hideip.me/en/proxy/",
        "ip_port_selector": "table.proxy__t tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_type": "offset", "offset_param": "start", "offset_step": 64,
        "max_pages_to_scrape": MAX_SCRAPING_PAGES,
    },
    "www.proxysharp.com": {
        "base_url": "https://www.proxysharp.com/proxies/",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "list.proxylistplus.com": { # Often gives 403
        "base_url": "https://list.proxylistplus.com/",
        "ip_port_selector": "table.bg tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "td.main-content-text a:contains('Next')",
    },
    "free-proxy.cz": {
        "base_url": "http://free-proxy.cz/en/",
        "ip_port_selector": "table#proxy_list tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "div.paginator a:contains('Next')",
    },
}

def get_html_content(session, url, site_name, attempt=1):
    """Fetches HTML content from a given URL with random User-Agent and retry logic."""
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': url # Referer header
    }
    try:
        response = session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"[{site_name}] Attempt {attempt}/{RETRY_ATTEMPTS}: Error fetching HTML from {url}: {e}")
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY)
            return get_html_content(session, url, site_name, attempt + 1)
        return None

def extract_proxies_from_html(html_content, site_name, config):
    """Extracts IP:PORT proxies from HTML using BeautifulSoup."""
    proxies = []
    if not html_content:
        return proxies

    soup = BeautifulSoup(html_content, 'lxml')
    selector = config.get("ip_port_selector")
    ip_index = config.get("ip_index")
    port_index = config.get("port_index")

    if not all([selector, ip_index is not None, port_index is not None]):
        print(f"[{site_name}] Error: Missing ip_port_selector, ip_index, or port_index in config. Skipping site.")
        return proxies

    rows = soup.select(selector)

    if not rows:
        # print(f"[{site_name}] Warning: No rows found with selector '{selector}' on current page.")
        pass

    for row in rows:
        cells = row.find_all('td')
        if len(cells) > max(ip_index, port_index):
            ip_text = cells[ip_index].get_text(strip=True)
            port_text = cells[port_index].get_text(strip=True)

            # Some sites obfuscate IP, try to decode if not standard IP format
            # For example, free-proxy-list.net often encodes IP in a script
            if site_name == "free-proxy-list.net" and re.match(r'[a-zA-Z0-9]+', ip_text):
                # This part is highly site-specific and may need to be generalized or removed.
                # Currently, free-proxy-list.net IPs are mostly plain text.
                pass # For now, assuming it's plain text. If it's JS encoded, this won't work.

            if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', ip_text) and re.match(r'\d+', port_text):
                proxies.append(f"{ip_text}:{port_text}")
    return proxies

def scrape_website_pages(site_name, config):
    """Scrapes proxies from all pages of a given website."""
    all_site_proxies = []
    visited_urls = set()
    urls_to_visit = [config["base_url"]]
    
    session = requests.Session() # Use a session for better connection management
    
    print(f"\n--- Starting scraping for {site_name} ---")

    page_count = 0
    max_pages = config.get("max_pages_to_scrape", MAX_SCRAPING_PAGES)

    while urls_to_visit and page_count < max_pages:
        current_url = urls_to_visit.pop(0)
        if current_url in visited_urls:
            print(f"[{site_name}] Already visited: {current_url}. Skipping.")
            continue

        print(f"[{site_name}] Scraping page {page_count + 1}/{max_pages}: {current_url}")
        visited_urls.add(current_url)
        html_content = get_html_content(session, current_url, site_name)

        if not html_content:
            print(f"[{site_name}] Failed to get HTML for {current_url} after retries. Skipping page.")
            continue

        page_proxies = extract_proxies_from_html(html_content, site_name, config)
        all_site_proxies.extend(page_proxies)
        
        soup = BeautifulSoup(html_content, 'lxml')
        next_url = None

        # --- Pagination Logic ---
        if "pagination_selector" in config:
            next_page_link = soup.select_one(config["pagination_selector"])
            if next_page_link and next_page_link.has_attr('href'):
                next_url = urljoin(current_url, next_page_link['href'])
                # Some sites like hidemy.name use a 'start' parameter even with a 'next' link selector
                # Check for "start" parameter in next_url, if it's there, convert to offset type pagination if needed
                parsed_next_url = urlparse(next_url)
                query_params = parse_qs(parsed_next_url.query)
                if config.get("pagination_type") == "offset" and config.get("offset_param") in query_params:
                    # If it's an offset type and selector gives a link, prioritize the offset logic
                    # This prevents mixing logic, ensures consistent offset step.
                    print(f"[{site_name}] Pagination selector found, but offset type is preferred. Reverting to offset logic for next URL.")
                    pass # Will be handled by offset logic below if it matches
                elif next_url == current_url:
                    print(f"[{site_name}] Pagination link points to current URL ({current_url}). Stopping.")
                    next_url = None # Stop if next link is current page
            else:
                # print(f"[{site_name}] No 'next' link found with selector '{config['pagination_selector']}' on {current_url}")
                pass # No next link, so next_url remains None

        # Type 2: Offset-based pagination (like hidemy.name) - if primary selector didn't work or this is preferred
        if config.get("pagination_type") == "offset":
            # Re-evaluate next_url based on offset logic, potentially overriding selector-based next_url
            parsed_current_url = urlparse(current_url)
            current_query_params = parse_qs(parsed_current_url.query)
            current_offset = 0
            if config.get("offset_param") in current_query_params:
                try:
                    current_offset = int(current_query_params[config["offset_param"]][0])
                except (ValueError, IndexError):
                    print(f"[{site_name}] Warning: Invalid offset parameter in URL: {current_query_params[config['offset_param']]}")

            next_offset = current_offset + config.get("offset_step", 64)

            # Ensure the base URL's path is used, not just the base domain
            base_url_parsed = urlparse(config["base_url"])
            next_query_params = current_query_params.copy()
            next_query_params[config["offset_param"]] = [str(next_offset)]

            next_url = base_url_parsed._replace(query=urlencode(next_query_params, doseq=True)).geturl()
            # print(f"[{site_name}] Offset pagination: Current offset {current_offset}, Next offset {next_offset}, Next URL: {next_url}")


        if next_url and next_url not in visited_urls and page_proxies:
            urls_to_visit.append(next_url)
        elif not next_url:
            print(f"[{site_name}] No further pagination link found or recognized for {current_url}. Stopping for this site.")
            break # Stop scraping this site
        elif next_url and not page_proxies:
            print(f"[{site_name}] No new proxies found on {current_url}, stopping pagination for this site early.")
            break # Stop scraping this site
        
        page_count += 1 # Increment page count *after* processing next_url to ensure page limit is correctly applied
        time.sleep(SCRAPING_DELAY)

    print(f"--- Finished scraping {site_name}. Found {len(all_site_proxies)} proxies. ---")
    return all_site_proxies

def test_proxy(session, proxy):
    """Tests if a proxy is working using the provided session."""
    try:
        proxies_dict = {
            'http': f'http://{proxy}',
            'https': f'https://{proxy}'
        }
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        response = session.get(PROXY_TEST_URL, proxies=proxies_dict, timeout=TIMEOUT, headers=headers, verify=False)
        if response.status_code == 200:
            return True
    except requests.exceptions.RequestException:
        pass
    except Exception as e:
        # print(f"An unexpected error occurred while testing proxy {proxy}: {e}")
        pass
    return False

def check_dnsbl(ip):
    """Checks an IP against free DNSBL servers using socket."""
    dnsbl_listings = 0
    try:
        reversed_ip = ".".join(ip.split('.')[::-1])
        for dnsbl in FREE_DNSBL_SERVERS:
            try:
                socket.gethostbyname(f"{reversed_ip}.{dnsbl}")
                dnsbl_listings += 1
            except socket.gaierror:
                pass # Not listed
            except Exception as e:
                print(f"Error during DNSBL check for {ip} on {dnsbl}: {e}")
    except Exception as e:
        print(f"Error preparing DNSBL check for {ip}: {e}")
    return dnsbl_listings

def test_and_check_proxy(proxy):
    """Combines proxy testing and DNSBL checking."""
    session = requests.Session() # New session for each proxy test
    is_working = test_proxy(session, proxy)
    ip = proxy.split(":")[0]
    dnsbl_listings = 0
    if is_working:
        dnsbl_listings = check_dnsbl(ip)
    session.close() # Close the session
    return is_working, dnsbl_listings, proxy

def process_scraped_proxies():
    """Main function to scrape, test, and save proxies."""
    all_scraped_proxies = []

    print("Starting proxy scraping from configured websites...")
    with ThreadPoolExecutor(max_workers=SCRAPING_CONCURRENCY) as executor:
        scrape_futures = {executor.submit(scrape_website_pages, site_name, config): site_name
                          for site_name, config in SCRAPING_TARGETS.items()
                          if all(k in config for k in ["ip_port_selector", "ip_index", "port_index"])}

        for future in as_completed(scrape_futures):
            site_name = scrape_futures[future]
            try:
                proxies = future.result()
                all_scraped_proxies.extend(proxies)
            except Exception as exc:
                print(f'[{site_name}] Scraping generated an exception: {exc}')

    unique_proxies = list(set(all_scraped_proxies))
    print(f"\nTotal unique proxies scraped from all sources: {len(unique_proxies)}")

    if not unique_proxies:
        print("No proxies scraped. Exiting.")
        return

    working_clean_proxies = []
    print(f"\nStarting connectivity and DNSBL checks for {len(unique_proxies)} proxies. This may take a while...")

    # Use a separate ThreadPoolExecutor for testing, as it's I/O bound
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        test_futures = {executor.submit(test_and_check_proxy, proxy): proxy for proxy in unique_proxies}
        
        tested_count = 0
        for future in as_completed(test_futures):
            is_working, dnsbl_listings, proxy = future.result()
            tested_count += 1
            if tested_count % 50 == 0 or tested_count == len(unique_proxies):
                print(f"Processed {tested_count}/{len(unique_proxies)} proxies. Found {len(working_clean_proxies)} working and clean.")

            if is_working and dnsbl_listings == 0:
                working_clean_proxies.append(proxy)
            # elif is_working:
            #     print(f"Proxy {proxy} is working but listed on {dnsbl_listings} DNSBLs. Skipping.")
            # else:
            #     print(f"Proxy {proxy} failed connectivity test. Skipping.")

    print(f"\nFound {len(working_clean_proxies)} working and clean proxies.")

    if working_clean_proxies:
        with open(OUTPUT_FILE, "w") as f:
            for proxy in working_clean_proxies:
                f.write(proxy + "\n")
        print(f"Working proxies saved to {OUTPUT_FILE}")
    else:
        print("No working and clean proxies found to save.")

if __name__ == "__main__":
    process_scraped_proxies()
