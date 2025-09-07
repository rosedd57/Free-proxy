import requests
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import random
import socket # For DNSBL checks

# --- Configuration ---
PROXY_TEST_URL = "http://www.google.com" # Proxy test ke liye URL
TIMEOUT = 15 # Request timeout in seconds
MAX_WORKERS = 100 # Proxy testing ke liye concurrent workers
OUTPUT_FILE = "working_proxies.txt" # Valid proxies save karne ki file
SCRAPING_CONCURRENCY = 5 # Ek saath kitni websites scrape honge (avoid overwhelming sites)
SCRAPING_DELAY = 2 # Har page request ke beech mein delay (per site)
MAX_SCRAPING_PAGES = 5 # Har site se kitne pages scrape karne hain (avoid infinite loops)
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
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36 Edg/95.0.1020.44"
]

# --- Websites to Scrape ---
# Har entry mein 'base_url', 'ip_port_selector', 'ip_index', 'port_index' zaroori hain.
# 'pagination_selector' ya 'pagination_type' pagination ke liye hain.
# Agar koi site JS se content load karti hai, toh yeh code uske liye kaam nahi karega.
SCRAPING_TARGETS = {
    # Working Examples (verified)
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
        "pagination_type": "offset", # Custom pagination handling
        "offset_param": "start",
        "offset_step": 64,
        "max_pages_to_scrape": MAX_SCRAPING_PAGES,
    },
    "freeproxy.world": {
        "base_url": "https://www.freeproxy.world/",
        "ip_port_selector": "table.table tbody tr",
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
    "proxyelite.info": {
        "base_url": "https://proxyelite.info/free-proxy-list/",
        "ip_port_selector": "table.table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('Next')",
    },
    "free-proxy-list.net_socks": { # Special entry for socks list on free-proxy-list.net
        "base_url": "https://free-proxy-list.net/en/socks-proxy.html",
        "ip_port_selector": "table#proxylisttable tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "div#list div.btn-group a.paginate.btn:contains('Next')",
    },
    # New Sites (selectors adjusted based on common patterns, may need manual fine-tuning)
    "openproxylist.com": { # Complex selector, check if it breaks due to spaces/special chars
        "base_url": "https://openproxylist.com/",
        "ip_port_selector": "table tbody tr", # Simplified, look for direct table body rows
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "a[aria-label='Next']", # Often uses aria-label for next
    },
    "proxyhub.me": {
        "base_url": "https://proxyhub.me/en/all-https-proxy-list.html",
        "ip_port_selector": "table.table.table-striped tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('>')", # Next page arrow
    },
    "proxybros.com": {
        "base_url": "https://proxybros.com/free-proxy-list/",
        "ip_port_selector": "table tbody tr", # Common for proxy tables
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "proxydb.net": {
        "base_url": "https://proxydb.net/",
        "ip_port_selector": "table.table-striped tbody tr", # Look for a table with striped rows
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "a[aria-label='Next']", # Common for next page links
    },
    "proxiware.com": {
        "base_url": "https://proxiware.com/free-proxy-list",
        "ip_port_selector": "table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination a:contains('Next')",
    },
    "fineproxy.org": {
        "base_url": "https://fineproxy.org/free-proxy/",
        "ip_port_selector": "table.proxy-list tbody tr", # Often uses a class like proxy-list
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
    "www.lunaproxy.com": { # This often loads with JS, but trying HTML scrape
        "base_url": "https://www.lunaproxy.com/freeproxy/index.html",
        "ip_port_selector": "table.ant-table-body tbody tr", # Check for ant-design tables
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "li.ant-pagination-next a", # Ant design pagination
    },
    "www.proxy-list.download": { # Has API, but trying HTML as well
        "base_url": "https://www.proxy-list.download/SOCKS5", # You can change to HTTP, HTTPS
        "ip_port_selector": "table.table-striped tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('Next')",
    },
    "proxycompass.com": {
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
    "hide.mn": { # Similar to hidemy.name
        "base_url": "https://hide.mn/en/proxy-list",
        "ip_port_selector": "table.proxy__t tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_type": "offset", "offset_param": "start", "offset_step": 64,
        "max_pages_to_scrape": MAX_SCRAPING_PAGES,
    },
    "proxy5.net": {
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
    "hideip.me": { # Similar to hidemy.name
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
    "list.proxylistplus.com": {
        "base_url": "https://list.proxylistplus.com/",
        "ip_port_selector": "table.bg tbody tr", # This site has unique table class, needs verification
        "ip_index": 0, # Needs verification
        "port_index": 1, # Needs verification
        "pagination_selector": "td.main-content-text a:contains('Next')",
    },
    "free-proxy.cz": {
        "base_url": "http://free-proxy.cz/en/",
        "ip_port_selector": "table#proxy_list tbody tr", # Specific ID for table
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "div.paginator a:contains('Next')",
    },
}

def get_html_content(url, site_name):
    """Fetches HTML content from a given URL with random User-Agent."""
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status() # HTTP errors ke liye exception raise karega
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"[{site_name}] Error fetching HTML from {url}: {e}")
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
        print(f"[{site_name}] Error: Missing ip_port_selector, ip_index, or port_index in config.")
        return proxies

    rows = soup.select(selector)

    if not rows:
        # print(f"[{site_name}] Warning: No rows found with selector '{selector}' on current page.")
        pass

    for row in rows:
        cells = row.find_all('td')
        if len(cells) > max(ip_index, port_index):
            ip = cells[ip_index].get_text(strip=True)
            port = cells[port_index].get_text(strip=True)

            # Basic validation
            if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', ip) and re.match(r'\d+', port):
                proxies.append(f"{ip}:{port}")
            # else:
            #     print(f"[{site_name}] Skipping invalid IP/Port: {ip}:{port}")
    return proxies

def scrape_website_pages(site_name, config):
    """Scrapes proxies from all pages of a given website."""
    all_site_proxies = []
    visited_urls = set()
    urls_to_visit = [config["base_url"]]

    print(f"\n--- Starting scraping for {site_name} ---")

    page_count = 0
    max_pages = config.get("max_pages_to_scrape", MAX_SCRAPING_PAGES)

    while urls_to_visit and page_count < max_pages:
        current_url = urls_to_visit.pop(0)
        if current_url in visited_urls:
            continue

        print(f"[{site_name}] Scraping page {page_count + 1}/{max_pages}: {current_url}")
        visited_urls.add(current_url)
        html_content = get_html_content(current_url, site_name)

        if not html_content:
            print(f"[{site_name}] Could not get HTML for {current_url}. Skipping.")
            continue

        page_proxies = extract_proxies_from_html(html_content, site_name, config)
        all_site_proxies.extend(page_proxies)
        page_count += 1

        soup = BeautifulSoup(html_content, 'lxml')
        next_url = None

        # --- Pagination Logic ---
        if "pagination_selector" in config:
            next_page_link = soup.select_one(config["pagination_selector"])
            if next_page_link and next_page_link.has_attr('href'):
                next_url = requests.compat.urljoin(current_url, next_page_link['href'])
            else:
                pass
                # print(f"[{site_name}] No 'next' link found with selector '{config['pagination_selector']}' on {current_url}")

        elif config.get("pagination_type") == "offset":
            current_offset = 0
            # Try to get offset from current_url, if not found, use base_url for calculations
            match = re.search(fr'{re.escape(config["offset_param"])}=(\d+)', current_url)
            if match:
                current_offset = int(match.group(1))

            next_offset = current_offset + config.get("offset_step", 64)
            parsed_url = requests.utils.urlparse(config["base_url"])
            query_params = requests.utils.parse_qs(parsed_url.query)
            query_params[config["offset_param"]] = [str(next_offset)]

            # Reconstruct the URL correctly, ensuring existing params are kept
            # For hidemy.name, it's often base_url + ?start=X
            new_query = requests.compat.urlencode(query_params, doseq=True)
            next_url = requests.utils.urlunparse(parsed_url._replace(query=new_query))

        if next_url and next_url not in visited_urls and page_proxies: # Only go to next page if proxies found
            urls_to_visit.append(next_url)
        elif next_url and next_url in visited_urls:
            print(f"[{site_name}] Skipping already visited URL: {next_url}")
        elif next_url and not page_proxies:
            print(f"[{site_name}] No proxies found on {current_url}, stopping pagination for this site early.")
        elif not next_url:
            print(f"[{site_name}] No further pagination link found or recognized for {current_url}.")


        time.sleep(SCRAPING_DELAY)

    print(f"--- Finished scraping {site_name}. Found {len(all_site_proxies)} proxies. ---")
    return all_site_proxies

def test_proxy(proxy):
    """Tests if a proxy is working."""
    try:
        proxies_dict = {
            'http': f'http://{proxy}',
            'https': f'https://{proxy}'
        }
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        # verify=False because some proxies might interfere with SSL certs,
        # but in production, you should handle this carefully.
        response = requests.get(PROXY_TEST_URL, proxies=proxies_dict, timeout=TIMEOUT, headers=headers, verify=False)
        if response.status_code == 200:
            return True
    except requests.exceptions.RequestException as e:
        # print(f"Proxy {proxy} failed: {e}") # Too verbose, uncomment for deep debugging
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
                # DNS query for A record
                socket.gethostbyname(f"{reversed_ip}.{dnsbl}")
                dnsbl_listings += 1
                # print(f"IP {ip} listed on {dnsbl}") # Uncomment to see listings
            except socket.gaierror:
                # Not listed, getaddrinfo failed to find an A record
                pass
            except Exception as e:
                print(f"Error during DNSBL check for {ip} on {dnsbl}: {e}")
    except Exception as e:
        print(f"Error preparing DNSBL check for {ip}: {e}")
    return dnsbl_listings

def test_and_check_proxy(proxy):
    """Combines proxy testing and DNSBL checking."""
    is_working = test_proxy(proxy)
    ip = proxy.split(":")[0]
    dnsbl_listings = 0
    if is_working:
        dnsbl_listings = check_dnsbl(ip)
    return is_working, dnsbl_listings, proxy

def process_scraped_proxies():
    """Main function to scrape, test, and save proxies."""
    all_scraped_proxies = []

    print("Starting proxy scraping from configured websites...")
    with ThreadPoolExecutor(max_workers=SCRAPING_CONCURRENCY) as executor:
        # Filter targets to only include those with necessary config for scraping
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
            if is_working and dnsbl_listings == 0:
                working_clean_proxies.append(proxy)
                print(f"[{tested_count}/{len(unique_proxies)}] Proxy {proxy} is working and clean. (Found: {len(working_clean_proxies)})")
            elif is_working:
                print(f"[{tested_count}/{len(unique_proxies)}] Proxy {proxy} is working but listed on {dnsbl_listings} DNSBLs. Skipping.")
            else:
                # print(f"[{tested_count}/{len(unique_proxies)}] Proxy {proxy} failed connectivity test. Skipping.") # Too verbose
                pass

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
