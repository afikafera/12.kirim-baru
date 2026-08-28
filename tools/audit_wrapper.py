import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import sys

def audit_wrapper(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")

    print(f"WRAPPER URL: {url}")
    print(f"Status: {r.status_code}")
    print(f"HTML length: {len(r.text)}")
    body = soup.get_text(" ", strip=True)
    print(f"Body text length: {len(body)}")

    # Cari iframe same-origin
    origin = url.split("/")[2]  # simple netloc
    iframes = soup.find_all("iframe")
    for iframe in iframes:
        src = iframe.get("src")
        if not src:
            continue
        absurl = urljoin(url, src)
        if origin in absurl:
            print(f"\nFound same-origin iframe: {absurl}")
            try:
                r2 = requests.get(absurl, headers=headers, timeout=20)
                soup2 = BeautifulSoup(r2.text, "html.parser")
                body2 = soup2.get_text(" ", strip=True)
                print(f"IFRAME URL: {absurl}")
                print(f"Status: {r2.status_code}")
                print(f"HTML length: {len(r2.text)}")
                print(f"Body text length: {len(body2)}")
                print(f"Content-Type: {r2.headers.get('content-type', 'unknown')}")
                print(f"Ratio HTML (iframe/wrapper): {len(r2.text)/len(r.text):.2f}")
                print(f"Ratio Body (iframe/wrapper): {len(body2)/len(body):.2f}")
            except Exception as e:
                print(f"Failed to fetch iframe: {e}")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.the355.com/index.php/workshop-manual"
    audit_wrapper(url)
