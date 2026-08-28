import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

def audit_dom(url):
    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )

    soup = BeautifulSoup(r.text, "html.parser")

    print("="*60)
    print(url)
    print("status :", r.status_code)
    print("html   :", len(r.text))

    body = soup.get_text(" ", strip=True)
    print("body   :", len(body))

    origin = urlparse(url).netloc

    for tagname in ["iframe","frame","object","embed"]:

        tags = soup.find_all(tagname)

        print(tagname, len(tags))

        for t in tags:

            src = t.get("src") or t.get("data")

            if not src:
                continue

            absurl = urljoin(url, src)

            same = urlparse(absurl).netloc == origin

            print(" ", tagname)
            print("    src :", absurl)
            print("    same-origin :", same)

    meta = soup.find("meta", attrs={
        "http-equiv":
        lambda x: x and x.lower()=="refresh"
    })

    if meta:
        print("META REFRESH :", meta.get("content"))

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.the355.com/index.php/workshop-manual"
    audit_dom(url)
