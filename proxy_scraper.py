import requests
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time

# --- Configuration ---
PROXY_TEST_URL = "http://www.google.com" 
TIMEOUT = 10 
MAX_WORKERS = 200 
OUTPUT_FILE = "proxy.txt"
SCRAPING_CONCURRENCY = 10 # Number of scraping tasks to run concurrently (to avoid overwhelming sites)
SCRAPING_DELAY = 1 # Seconds to wait between page requests for a single site
# --- End Configuration ---

# Free/Public DNSBL servers for basic blacklist check
FREE_DNSBL_SERVERS = [
    "zen.spamhaus.org", 
    "bl.spamcop.net",
    "dnsbl.sorbs.net",
    "b.barracudacentral.org"
]

# --- Websites to Scrape ---
# Each entry requires careful configuration based on the website's HTML structure.
# Use your browser's developer tools (Inspect Element) to find selectors and pagination logic.
SCRAPING_TARGETS = {
    # Working Example: free-proxy-list.net
    "free-proxy-list.net": {
        "base_url": "https://free-proxy-list.net/",
        "ip_port_selector": "table#proxylisttable tbody tr", 
        "ip_index": 0, 
        "port_index": 1, 
        "pagination_selector": "div#list div.btn-group a.paginate.btn:contains('Next')",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    # Working Example: hidemy.name
    "hidemy.name": {
        "base_url": "https://hidemy.name/en/proxy-list/",
        "ip_port_selector": "table.proxy__t tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_type": "offset", # Custom pagination handling
        "offset_param": "start",
        "offset_step": 64, 
        "max_pages_to_scrape": 10, # Limit to avoid infinite loops or rate limits
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    # New Site Example: freeproxy.world
    "freeproxy.world": {
        "base_url": "https://www.freeproxy.world/",
        "ip_port_selector": "table.table tbody tr", 
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a[rel='next']", # Common 'next' link pattern
        "headers": {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    # New Site Example: www.vpnside.com
    "vpnside.com": {
        "base_url": "https://www.vpnside.com/proxy/list/",
        "ip_port_selector": "table.table.table-hover tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a[rel='next']",
        "headers": {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    # New Site Example: proxyelite.info
    "proxyelite.info": {
        "base_url": "https://proxyelite.info/free-proxy-list/",
        "ip_port_selector": "table.table tbody tr",
        "ip_index": 0,
        "port_index": 1,
        "pagination_selector": "ul.pagination li a:contains('Next')", # Check the text or rel attribute
        "headers": {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    # New Site Example: openproxylist.com
    "openproxylist.com": {
        "base_url": "https://openproxylist.com/",
        "ip_port_selector": "table.w-full.text-sm.text-left.rtl:text-right.text-gray-500 tbody tr", # This is a complex selector, might break
        "ip_index": 0, # Needs verification
        "port_index": 1, # Needs verification
        "pagination_selector": "a.relative.inline-flex.items-center.px-4.py-2.text-sm.font-semibold", # Needs specific text like "Next" or arrow
        "headers": {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    # New Site Example: proxyhub.me (https://proxyhub.me/en/all-https-proxy-list.html)
    "proxyhub.me": {
        "base_url": "https://proxyhub.me/en/all-https-proxy-list.html",
        "ip_port_selector": "table.table.table-striped tbody tr",
        "ip_index": 0, # Needs verification
        "port_index": 1, # Needs verification
        "pagination_selector": "ul.pagination li a:contains('>')", # Likely a next page arrow
        "headers": {'User-Agent': 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    
    # --- Requires Investigation ---
    # You will need to inspect these sites manually to find the correct selectors and pagination logic.
    "free.geonix.com": {
        "base_url": "https://free.geonix.com/en/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "proxybros.com": {
        "base_url": "https://proxybros.com/free-proxy-list/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "iproyal.com": { # Likely uses JavaScript for loading content
        "base_url": "https://iproyal.com/free-proxy-list/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "proxydb.net": { # Might have unique table structure
        "base_url": "https://proxydb.net/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "proxiware.com": { # Needs investigation
        "base_url": "https://proxiware.com/free-proxy-list",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "fineproxy.org": { # Needs investigation
        "base_url": "https://fineproxy.org/free-proxy/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "www.proxyrack.com": { # Needs investigation
        "base_url": "https://www.proxyrack.com/free-proxy-list/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "www.lunaproxy.com": { # Needs investigation
        "base_url": "https://www.lunaproxy.com/freeproxy/index.html",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "proxyscrape.com": { # API source, not HTML scraping
        "base_url": "https://proxyscrape.com/free-proxy-list", 
        # This one is trickier as it might be an API endpoint.
        # If it's pure HTML, then selectors are needed.
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "free-proxy-list.net_socks": { # Special entry for socks list on free-proxy-list.net
        "base_url": "https://free-proxy-list.net/en/socks-proxy.html",
        "ip_port_selector": "table#proxylisttable tbody tr", 
        "ip_index": 0, 
        "port_index": 1, 
        "pagination_selector": "div#list div.btn-group a.paginate.btn:contains('Next')",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "www.proxy-list.download": { # Has API, but might have HTML as well. Need to differentiate.
        "base_url": "https://www.proxy-list.download/SOCKS5",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/55.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "proxycompass.com": { # Needs investigation
        "base_url": "https://proxycompass.com/free-proxy/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "advanced.name": { # Needs investigation
        "base_url": "https://advanced.name/freeproxy",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "www.iplocation.net": { # Needs investigation
        "base_url": "https://www.iplocation.net/proxy-list",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "hide.mn": { # Similar to hidemy.name, but check exact selectors
        "base_url": "https://hide.mn/en/proxy-list", 
        # "ip_port_selector": "table.proxy__t tbody tr",
        # "ip_index": 0, "port_index": 1,
        # "pagination_type": "offset", "offset_param": "start", "offset_step": 64, 
        # "max_pages_to_scrape": 10,
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "proxy5.net": { # Needs investigation
        "base_url": "https://proxy5.net/free-proxy",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "freeproxyupdate.com": { # Needs investigation
        "base_url": "https://freeproxyupdate.com/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "www.ditatompel.com": { # Needs investigation
        "base_url": "https://www.ditatompel.com/proxy",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "hideip.me": { # Similar to hidemy.name
        "base_url": "https://hideip.me/en/proxy/",
        # "ip_port_selector": "table.proxy__t tbody tr",
        # "ip_index": 0, "port_index": 1,
        # "pagination_type": "offset", "offset_param": "start", "offset_step": 64,
        # "max_pages_to_scrape": 10,
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "www.proxysharp.com": { # Needs investigation
        "base_url": "https://www.proxysharp.com/proxies/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "list.proxylistplus.com": { # Needs investigation
        "base_url": "https://list.proxylistplus.com/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
    "free-proxy.cz": { # Needs investigation
        "base_url": "http://free-proxy.cz/en/",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },

  "geonode.com": { # Needs investigation
        "base_url": "https://geonode.com/free-proxy-list",
        # "ip_port_selector": "", 
        # "ip_index": 0, "port_index": 1,
        # "pagination_selector": "",
        "headers": {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    },
}


def get_html_content(url, headers=None):
    """Fetches HTML content from a given URL."""
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching HTML from {url}: {e}")
        return None

def extract_proxies_from_html(html_content, selector, ip_index, port_index):
    """Extracts IP:PORT proxies from HTML using BeautifulSoup."""
    proxies = []
    if not html_content:
        return proxies

    soup = BeautifulSoup(html_content, 'lxml') 
    
    rows = soup.select(selector)
    
    for row in rows:
        cells = row.find_all('td') 
        if len(cells) > max(ip_index, port_index):
            ip = cells[ip_index].get_text(strip=True)
            port = cells[port_index].get_text(strip=True)
            
            if re.match(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', ip) and re.match(r'\d+', port):
                proxies.append(f"{ip}:{port}")
    return proxies

def scrape_website_pages(site_name, config):
    """Scrapes proxies from all pages of a given website."""
    all_site_proxies = []
    visited_urls = set()
    urls_to_visit = [config["base_url"]]
    
    print(f"Starting scraping for {site_name}...")
    
    page_count = 0
    while urls_to_visit and (config.get("max_pages_to_scrape", float('inf')) > page_count):
        current_url = urls_to_visit.pop(0)
        if current_url in visited_urls:
            continue
        
        print(f"Scraping page {page_count+1}: {current_url}")
        visited_urls.add(current_url)
        html_content = get_html_content(current_url, config.get("headers"))
        if not html_content:
            continue
        
        page_proxies = extract_proxies_from_html(
            html_content, 
            config["ip_port_selector"], 
            config["ip_index"], 
            config["port_index"]
        )
        all_site_proxies.extend(page_proxies)
        page_count += 1

        soup = BeautifulSoup(html_content, 'lxml')
        
        # --- Generic Pagination Logic ---
        # This tries to handle common pagination patterns.
        # You can add more specific logic for unique sites.
        next_url = None
        
        # Type 1: Standard 'Next' button or rel='next' link
        if "pagination_selector" in config:
            next_page_link = soup.select_one(config["pagination_selector"])
            if next_page_link and next_page_link.has_attr('href'):
                # Handle relative URLs correctly
                next_url = requests.compat.urljoin(current_url, next_page_link['href'])
        
        # Type 2: Offset-based pagination (like hidemy.name)
        elif config.get("pagination_type") == "offset":
            current_offset = 0
            match = re.search(fr'{config["offset_param"]}=(\d+)', current_url)
            if match:
                current_offset = int(match.group(1))
            
            next_offset = current_offset + config.get("offset_step", 64)
            # Reconstruct the URL, preserving other parameters if any
            parsed_url = requests.utils.urlparse(config["base_url"])
            query_params = requests.utils.parse_qs(parsed_url.query)
            query_params[config["offset_param"]] = [str(next_offset)] # Update/add offset
            
            next_url = requests.utils.urlunparse(parsed_url._replace(query=requests.compat.urlencode(query_params, doseq=True)))
        
        if next_url and next_url not in visited_urls and page_proxies:
            urls_to_visit.append(next_url)
        elif next_url and next_url in visited_urls:
            print(f"Skipping already visited URL: {next_url}")
        elif next_url and not page_proxies:
            print(f"No proxies found on {current_url}, stopping pagination for this site.")

        time.sleep(SCRAPING_DELAY) 

    print(f"Finished scraping {site_name}. Found {len(all_site_proxies)} proxies.")
    return all_site_proxies

def test_proxy(proxy):
    """Tests if a proxy is working."""
    try:
        proxies_dict = {
            'http': f'http://{proxy}',
            'https': f'https://{proxy}'
        }
        response = requests.get(PROXY_TEST_URL, proxies=proxies_dict, timeout=TIMEOUT, verify=False) 
        if response.status_code == 200:
            return True
    except requests.exceptions.RequestException:
        pass
    return False

def check_dnsbl(ip):
    """Checks an IP against free DNSBL servers."""
    try:
        reversed_ip = ".".join(ip.split('.')[::-1])
        listed_count = 0
        for dnsbl in FREE_DNSBL_SERVERS:
            try:
                requests.get(f"http://{reversed_ip}.{dnsbl}", timeout=0.5) 
                listed_count += 1
            except requests.exceptions.RequestException:
                pass
            except Exception as e:
                print(f"Error during DNSBL check for {ip} on {dnsbl}: {e}")
        return listed_count
    except Exception as e:
        print(f"Error checking DNSBL for {ip}: {e}")
        return 0

def process_scraped_proxies():
    """Main function to scrape, test, and save proxies."""
    all_scraped_proxies = []

    with ThreadPoolExecutor(max_workers=SCRAPING_CONCURRENCY) as executor:
        future_to_site = {executor.submit(scrape_website_pages, site_name, config): site_name 
                          for site_name, config in SCRAPING_TARGETS.items() if "ip_port_selector" in config} # Only scrape configured sites
        
        for future in as_completed(future_to_site):
            site_name = future_to_site[future]
            try:
                proxies = future.result()
                all_scraped_proxies.extend(proxies)
            except Exception as exc:
                print(f'{site_name} scraping generated an exception: {exc}')

    unique_proxies = list(set(all_scraped_proxies))
    print(f"Total unique proxies scraped from all sources: {len(unique_proxies)}")

    working_clean_proxies = []
    print("Testing proxies for connectivity and checking basic DNSBLs...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_proxy = {executor.submit(test_and_check_proxy, proxy): proxy for proxy in unique_proxies}
        
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            is_working, dnsbl_listings = future.result()
            
            if is_working and dnsbl_listings == 0: 
                working_clean_proxies.append(proxy)

    print(f"Found {len(working_clean_proxies)} working and clean proxies.")

    with open(OUTPUT_FILE, "w") as f:
        for proxy in working_clean_proxies:
            f.write(proxy + "\n")
    print(f"Working proxies saved to {OUTPUT_FILE}")

def test_and_check_proxy(proxy):
    """Combines proxy testing and DNSBL checking."""
    is_working = test_proxy(proxy)
    ip = proxy.split(":")[0]
    dnsbl_listings = 0
    if is_working:
        dnsbl_listings = check_dnsbl(ip)
    return is_working, dnsbl_listings

if __name__ == "__main__":
    process_scraped_proxies()
