import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import sys
import time

def audit_iframe(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        origin = urlparse(url).netloc
        iframes = soup.find_all("iframe")
        same_origin_iframes = []
        for iframe in iframes:
            src = iframe.get("src")
            if src:
                absurl = urljoin(url, src)
                if urlparse(absurl).netloc == origin:
                    same_origin_iframes.append(absurl)
        body_len = len(soup.get_text(" ", strip=True))
        html_len = len(r.text)
        print(f"{url}")
        print(f"  status: {r.status_code}")
        print(f"  body_len: {body_len}")
        print(f"  html_len: {html_len}")
        print(f"  same-origin iframes: {len(same_origin_iframes)}")
        if same_origin_iframes:
            for f in same_origin_iframes:
                print(f"    {f}")
                # Coba fetch iframe untuk perbandingan
                try:
                    r2 = requests.get(f, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    body2 = len(r2.text)
                    print(f"    iframe html_len: {body2}")
                    print(f"    ratio: {body2/html_len:.2f}" if html_len else "    ratio: N/A")
                except:
                    print("    (gagal fetch iframe)")
        print()
    except Exception as e:
        print(f"ERROR: {url} - {e}")
        print()

if __name__ == "__main__":
    sites = [
        # Potential false positives
        "https://www.joomla.org/",
        "https://www.phpmyadmin.net/",
        "https://www.phpmyadmin.net/",  # mungkin tidak ada iframe
        "https://www.zabbix.com/",
        "https://www.home-assistant.io/",
        "https://www.jenkins.io/",
        "https://www.openproject.org/",
        "https://grafana.com/",
        "https://www.elastic.co/kibana",
        # Router web UI (tidak publik, skip)
        # MediaWiki lama (coba cari yang masih pakai)
        "https://en.wikipedia.org/wiki/Main_Page",  # control
        "https://www.w3schools.com/html/html_iframe.asp",  # contoh iframe
    ]
    for site in sites:
        audit_iframe(site)
        time.sleep(1)
