#!/bin/bash
# Audit berbagai URL untuk analisis struktur halaman

# Definisikan URL per kategori
declare -A urls=(
    ["Wiki Wikipedia"]="https://en.wikipedia.org/wiki/Ferrari"
    ["Wiki MediaWiki"]="https://www.mediawiki.org/wiki/MediaWiki"
    ["Dokumentasi MikroTik Docs"]="https://help.mikrotik.com/docs/display/ROS/RouterOS"
    ["Dokumentasi ReadTheDocs"]="https://requests.readthedocs.io/en/latest/"
    ["Dokumentasi GitHub Docs"]="https://docs.github.com/en/get-started"
    ["Manual the355"]="https://www.the355.com/index.php/workshop-manual"
    ["Manual OEM"]="https://www.ferrari.com/en-EN/auto/manuals"
    ["Forum Discourse"]="https://community.home-assistant.io/"
    ["Forum phpBB"]="https://www.phpbb.com/community/"
    ["Forum XenForo"]="https://xenforo.com/community/"
    ["Forum vBulletin"]="https://www.vbulletin.com/forum/"
    ["Online Shop Tokopedia"]="https://www.tokopedia.com/"
    ["Online Shop Shopee"]="https://shopee.co.id/"
    ["Online Shop Bukalapak"]="https://www.bukalapak.com/"
    ["Online Shop ACR"]="https://www.acr.co.id/"
    ["Company MikroTik"]="https://mikrotik.com/"
    ["Company ACR"]="https://www.acr.co.id/"
    ["Company Cisco"]="https://www.cisco.com/"
    ["Video YouTube"]="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ["Short Video TikTok"]="https://www.tiktok.com/@tiktok"
    ["Social Media Instagram"]="https://www.instagram.com/"
    ["Social Media Facebook"]="https://www.facebook.com/"
    ["Social Media X"]="https://twitter.com/"
    ["Source Code GitHub"]="https://github.com/torvalds/linux"
    ["News Guardian"]="https://www.theguardian.com/world"
    ["News CNN"]="https://edition.cnn.com/"
    ["News Kompas"]="https://www.kompas.com/"
    ["Blog WordPress"]="https://wordpress.org/news/"
    ["Blog Blogger"]="https://blogger.googleblog.com/"
    ["PDF contoh datasheet"]="https://www.ti.com/lit/ds/symlink/ne555.pdf"
    ["Catalog Mouser"]="https://www.mouser.com/c/passive-components/resistors/"
    ["Catalog DigiKey"]="https://www.digikey.com/en/products/filter/resistors/52"
)

echo "Audit URL dimulai..."
echo "Hasil akan ditulis ke audit_results.txt"
echo "=================================================="

for label in "${!urls[@]}"; do
    url="${urls[$label]}"
    echo "--- $label ---" >> audit_results.txt
    echo "URL: $url" >> audit_results.txt
    python3 tools/audit_dom.py "$url" >> audit_results.txt 2>&1
    echo "" >> audit_results.txt
    echo "==================================================" >> audit_results.txt
done

echo "Selesai. Lihat audit_results.txt"
