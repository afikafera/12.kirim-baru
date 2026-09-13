"""
PATCH 3 -- real BTC trace replay through the ACTUAL production
FactChecker.extract_facts_batch(), end to end.

RAW_INPUT and RAW_OUTPUT below are copied byte-for-byte (same JSON
escaping) from trace 01f3a9ee80d71aafc971ec5b6543daa8's fact-extraction
observation -- the exact evidence text the real extractor saw, and the
exact 41-field JSON the real LLM produced that day (2026-09-08,
TradingView + CoinDesk, the BTC evidence-loss/PATCH1-locale case).

This script:
  1. Parses RAW_INPUT to recover the two SOURCE evidence blocks
     (TradingView, CoinDesk) exactly as extract_facts_batch's own
     prompt-builder would have received them as `all_evidence`.
  2. Parses RAW_OUTPUT to get the real 41-fact JSON.
  3. Builds a FakeLLM whose .analyze() returns exactly that JSON,
     mirroring the LLMAnalyzer.analyze() return contract
     ({"content": ...}).
  4. Instantiates the REAL production FactChecker(FakeLLM()) and calls
     its REAL extract_facts_batch(all_evidence, checklist) -- not a
     reimplementation, the actual method, now patched with PATCH 3.
  5. Reports which of the original 41 facts survived vs got rejected,
     and specifically asserts current_price_usd and price_usd_coindesk
     (previously dropped, the whole reason for this investigation) are
     now present.

Run:
    cd ~/research-assistant
    python3 btc_trace_replay.py
"""
import json
import sys

sys.path.insert(0, ".")

from hermes_agent.fact_checker import FactChecker

RAW_INPUT = "[{\"role\": \"system\", \"content\": \"You are a universal fact extractor. Extract substantive facts only. Normalize keys to short snake_case names.\"}, {\"role\": \"user\", \"content\": \"Extract substantive facts from the evidence below.\\n\\nRULES:\\n1. Extract substantive facts only: specifications, values, numbers, commands,\\n   code, steps, symptoms, causes, solutions, tools, endpoints, configuration,\\n   and other relevant technical information.\\n2. Ignore menus, navigation, footers, copyright notices, breadcrumbs,\\n   page titles, section names, link lists, and UI text that does not contain\\n   substantive facts.\\n3. Do not turn page titles or navigation labels into domain facts.\\n4. A URL may be extracted only when the URL itself is a relevant fact,\\n   such as an API endpoint, documentation URL, download URL, or target URL.\\n5. Normalize keys to short snake_case names.\\n6. Include both the source URL and source_type.\\n7. NEVER invent, infer, or fabricate values that are not explicitly present\\n   in the evidence.\\n8. If the evidence contains only metadata or navigation and no substantive\\n   facts, return no facts rather than creating facts to fill the output.\\n9. Preserve exact numeric values, units, URLs, commands, and technical terms\\n   from the evidence.\\n\\nEVIDENCE:\\n### SUMBER 1: https://id.tradingview.com/symbols/BTCUSD/ (tipe: datasheet)\\n## Specifications\\nHarga\\n\\nBitcoin\\n\\n(\\n\\nBTC\\n\\n) saat ini adalah: 78.347\\nUSD: . Temukan lebih banyak wawasan pada\\nvolume trading\\n\\nBitcoin\\n\\n(\\n\\nBTC: ) dalam 24 jam adalah\\nHarga\\n\\nBitcoin\\n\\ntelah naik sebesar: 0,25\\nBitcoin\\n\\nmengalami penurunan sebesar: -29,54\\nBitcoin\\n\\n(\\n\\nBTC: ) mencapai harga terendahnya sebesar\\nUSD\\n\\npada\\n\\n20 Okt 2011: . Lihat lebih banyak dinamika\\nBitcoin: pada [chart harga](https://id.tradingview.com/chart/?symbol=BITSTAMP:BTCUSD). \\nKapitalisasi pasar: 1,57 T\\nUSD\\n\\nCap Pasar Terdilusi Sepenuhnya: 1,64 T\\nUSD\\n\\nSuplai sirkulasi: 20,08 M\\nSuplai maksimum: 21,00 M\\nTotal suplai: 20,08 M\\nMinat terbuka: Harga\\nLikuidasi (24h): 21,88 M USD\\nFunding Rate: 0,0058%\\nPembelian\\n\\nPenjualan\\n\\nHarga: [![Image 12: CRYPTO:BTCUSD](https://s3-symbol-logo.tradingview.com/crypto/XTVCBTC.svg)](https://id.tradingview.com/symbols/BTCUSD/ \\\"OKX:BTCUSD\\\")Pembelian\\nOsilator\\n\\nNetral\\n\\nPenjualan Pembelian: Penjualan Kuat Pembelian kuat\\nRangkuman\\n\\nNetral\\n\\nPenjualan Pembelian: Penjualan Kuat Pembelian kuat\\nRata-Rata Pergerakan\\n\\nNetral: Penjualan Pembelian\\nPenjualan Kuat Pembelian kuat: Penjualan Kuat Penjualan Netral Pembelian Pembelian kuat\\nKategori\\n\\nMata Uang Crypto\\n\\nWebsite: Kode sumber\\nPenjelajah\\n\\nWhitepaper\\n\\nKomunitas: Bitcoin adalah mata uang crypto yang paling banyak diperdagangkan di dunia, dan merupakan bagian terbesar dari kue pasar crypto. Ia adalah koin digital pertama dan dengan demikian, tetap menjadi mata uang crypto yang paling terkenal dan diadopsi secara luas di dunia. Ia merupakan kelompok asli yang jejaknya diikuti oleh semua koin lainnya. Kelahiran Bitcoin merupakan awal dari kelas aset yang sama sekali baru, dan langkah besar untuk menjauh dari uang tradisional yang dikendalikan secara terpusat. Saat ini, banyak pendukungnya percaya bahwa Bitcoin akan memfasilitasi tahap selanjutnya untuk sistem keuangan global, meskipun hal ini - tentu saja - masih harus dilihat perkembangannya.\\n\\n## Pertanyaan yang sering diajukan\\nHarga\\n\\nBitcoin\\n\\n(\\n\\nBTC\\n\\n) saat ini adalah\\n\\n78.347\\n\\nUSD\\n\\n- telah turun sebesar\\n\\n-0,94\\n\\n% dalam 24 jam terakhir. Coba masukkan info ini ke dalam konteksnya dengan memeriksa koin mana yang juga mengalami [kenaikan](https://id.tradingview.com/markets/cryptocurrencies/prices-gainers/) dan [penuruan](https://id.tradingview.com/markets/cryptocurrencies/prices-losers/) untuk saat ini dan lihat\\n\\n[chart harga BTC](https://id.tradingview.com/chart/?symbol=BITSTAMP:BTCUSD)\\n.\\n\\nvolume trading\\n\\nBitcoin\\n\\n(\\n\\nBTC\\n\\n) dalam 24 jam adalah\\n\\n23,40 B\\n\\nUSD\\n\\n. Lihat seberapa sering koin lain diperdagangkan pada [daftar ini](https://id.tradingview.com/markets/cryptocurrencies/prices-most-traded/).\\n\\nHarga\\n\\nBitcoin\\n\\ntelah naik sebesar\\n\\n0,25\\n\\n% selama seminggu terakhir, kinerja bulannya menunjukkan peningkatan sebesar\\n\\n21,36\\n\\n%, dan pada tahun lalu,\\n\\nBitcoin\\n\\nmengalami penurunan sebesar\\n\\n-29,54\\n\\n%. Lihat dinamika selengkapnya pada\\n\\n[chart harga BTC](https://id.tradingview.com/chart/?symbol=BITSTAMP:BTCUSD)\\n. \\n\\nPa\\n\\n## Statistik kunci\\nKapitalisasi pasar\\n\\n1,57 T\\n\\nUSD\\n\\nCap Pasar Terdilusi Sepenuhnya\\n\\n1,64 T\\n\\nUSD\\n\\nSuplai sirkulasi\\n\\n20,08 M\\n\\nSuplai maksimum\\n\\n21,00 M\\n\\nTotal suplai\\n\\n20,08 M\\n\\nMinat terbuka\\n\\n26,41 B USD 0,93%\\n\\nLikuidasi (24h)\\n\\n21,88 M USD\\n\\nFunding Rate\\n\\n0,0058%\\n\\n## Bandingkan dengan Bitcoin\\n![Image 1: CRYPTO:BTCUSD](https://s3-symbol-logo.tradingview.com/crypto/XTVCBTC.svg)\\n\\n78.3 75,75 USD-0,92%\\n\\n![Image 2](https://s3-symbol-logo.tradingview.com/crypto/XTVCXRP.svg)\\n\\n1,3850 USD-0,83%\\n\\n![Image 3](https://s3-symbol-logo.tradingview.com/crypto/XTVCZEC.svg)\\n\\n1.126,61 USD-1,14%\\n\\n![Image 4](https://s3-symbol-logo.tradingview.com/crypto/XTVCDOGE.svg)\\n\\n0,0890 79 USD-1,58%\\n\\n![Image 5](https://s3-symbol-logo.tradingview.com/crypto/XTVCXMR.svg)\\n\\n521,04 USD+0,29%\\n\\n![Image 6](https://s3-symbol-logo.tradingview.com/crypto/XTVCLINK.svg)\\n\\n12,637 USD-0,87%\\n\\n![Image 7](https://s3-symbol-logo.tradingview.com/crypto/XTVCXLM.svg)\\n\\n0,18909 USD-2,35%\\n\\n![Image 8](https://s3-symbol-logo.tradingview.com/crypto/XTVCBCH.svg)\\n\\n255,47 USD-1,37%\\n\\n![Image 9](https://s3-symbol-logo.tradingview.com/crypto/XTVCLTC.svg)\\n\\n55,067 USD-0,27%\\n\\n![Image 10](https://s3-symbol-logo.tradingview.com/crypto/XTVCCCCA.svg)\\n\\n0,10465 USD-0,82%\\n\\n![Image 11](https://s3-symbol-logo.tradingview.com/crypto/XTVCSHIB.svg)\\n\\n0,53839\\n\\n## Likuidasi\\nPembelian\\n\\nPenjualan\\n\\nHarga\\n\\n[![Image 12: CRYPTO:BTCUSD](https://s3-symbol-logo.tradingview.com/crypto/XTVCBTC.svg)](https://id.tradingview.com/symbols/BTCUSD/ \\\"OKX:BTCUSD\\\")Pembelian\\n\\n[![Image 13: CRYPTO:BTCUSD](https://s3-symbol-logo.tradingview.com/crypto/XTVCBTC.svg)](https://id.tradingview.com/symbols/BTCUSD/ \\\"BITSTAMP:BTCUSD\\\")Penjualan\\n\\n[![Image 14: CRYPTO:BTCUSD](https://s3-symbol-logo.tradingview.com/crypto/XTVCBTC.svg)](https://id.tradingview.com/symbols/BTCUSD/ \\\"BITSTAMP:BTCUSD\\\")Pembelian\\n\\n### SUMBER 2: https://www.coindesk.com/id/price/bitcoin (tipe: datasheet)\\n## Specifications\\nDasar\\nLanjutan\\n1H\\n24H\\n7D\\n1M\\nYTD\\n1Y\\nAll\\nO: -\\nBinance: - Start your crypto journey with Binance and earn up to a $300 welcome bonus.\\nBTC-USDT\\nBTCUSDT\\n\\t\\nBinance\\n\\t\\nAA\\n: 78.389,16\\nUSDT: -1,31%\\nBTC-USDT\\nBTCUSDT\\n\\t\\nBybit\\n\\t\\nA\\n: 78.391,60\\nBTC-USDT\\nBTC_USDT\\n\\t\\nGateio\\n\\t\\nA\\n: 78.396,80\\nBTC-USDT\\nBTC-USDT\\n\\t\\nOkex\\n\\t\\nA\\n: 78.388,80\\nBTC-USDC\\nBTCUSDC\\n\\t\\nBullish\\n\\t\\nAA\\n: 78.360,07\\nUSDC: -1,36%\\n\\n## \\nBerita\\nVideo\\nHarga\\nLainnya\\nBersponsor\\nMasuk\\nDaftar\\nCrypto\\nCD20\\n$2.240,92\\nCD20 down 0.75 percent\\n0.75%\\nBTC\\n$78.392,79\\nBTC down 1,33 percent\\n1,33%\\nETH\\n$2.472,93\\nETH down 0.76 percent\\n0.76%\\nXRP\\n$1,39\\nXRP down 1,34 percent\\n1,34%\\nSOL\\n$102,71\\nSOL down 1,93 percent\\n1,93%\\nLewati ke bagan\\nHarga>Bitcoin\\nBitcoin\\nBTC\\n#1\\n$78.378,18\\nTurun 1,35 persen\\n1,35%\\n($1.069,38)\\nCoinDesk AI Insights\\nTrading\\nDapatkan\\nStatistik Utama\\nKapitalisasi Pasar\\n$1.57T\\nTurun 1,35 persen\\n1,35%\\nVolume (24j)\\n$11.08B\\nNilai Terdilusi Penuh\\n$1.65T\\nVol/Kap. Pasar (24j)\\n0,70%\\nTotal Pasokan\\n20.08M BTC\\nPasokan Maksimum\\n21.00M BTC\\nPasokan Beredar\\n20.08M BTC\\nTanggal Peluncuran\\n2009-01-03\\nNomor Blok\\n966,030\\nHadiah Blok\\n3,13\\nUkuran Blok Terakhir\\n1,507,904\\nJaringan H/s\\n868884085.20T\\nBitcoin Informasi\\nSitus Web\\nbitcoin.org\\nWhitepaper\\nPenjelajah Blok\\nblockchain.info\\nRepositori\\ngithub.com/bitcoin/bitcoin\\nAlgoritma Hashing\\nSHA-256\\nStandar yang Didukung\\nBRC-20\\nIndustri\\nPayment\\nKomunitas\\nbitcointalk.org\\nBitcoin Konverter Harga\\nBTC\\nUSD\\nGrafik\\nBerita\\nPasar\\nSerupa\\nFAQ\\nDasar\\nLanjutan\\n1H\\n24H\\n7D\\n1M\\nYTD\\n1Y\\nAll\\nO: -\\nH: -\\nL: -\\nV: -\\n\\nBinance\\n\\n- Start your crypto journey with Binance and earn up to a $300 welcome bonus.\\n\\n1 jam\\nTurun 0.12 persen\\n0.12%\\n24 jam\\nTurun 1.35 persen\\n1.35%\\n7 hari\\nNaik 1.26 persen\\n1.26%\\n1 bulan\\nNaik 20.85 persen\\n20.85%\\n1 tahun\\nTurun 30.06 persen\\n30.06%\\nYTD\\nTurun 10.46 persen\\n10.46%\\nSepanjang waktu\\nNaik 158.31M persen\\n158.31M%\\nTerbaru Bitcoin Berita\\nLihat semua\\n2 jam lalu\\nPositif\\nBitcoin's golden cross is here\\n3 jam lalu\\nPositif\\nLiquid Network gets back 3,400 bitcoin from whitehat hackers; talks underway for the rest\\n3 jam lalu\\nNegatif\\nBitcoin slips under $79,000, Zcash leads losses as Fed hike odds hold near 60%\\n21 jam lalu\\nNetral\\nBitcoin blinks less than gold when Treasury yields move\\nBitcoin Pasar\\nLihat semua\\nInstrumen\\tBursa\\tData Tolok Ukur\\tHarga\\tPerubahan 24j\\n\\nBTC-USDT\\nBTCUSDT\\n\\t\\nBinance\\n\\t\\nAA\\n\\t\\n78.389,16\\nUSDT\\n\\t-1,32%\\n\\nBTC-USDT\\nBTCUSDT\\n\\t\\nBybit\\n\\t\\nA\\n\\t\\n78.391,60\\nUSDT\\n\\t-1,31%\\n\\nBTC-USDT\\nBTC_USDT\\n\\t\\nGateio\\n\\t\\nA\\n\\t\\n78.\\n\\nReturn JSON:\\n{\\\"field_id\\\": {\\\"value\\\": \\\"value\\\", \\\"source\\\": \\\"URL\\\", \\\"source_type\\\": \\\"type\\\"}}\"}]"

RAW_OUTPUT = "{\"role\": \"assistant\", \"content\": \"{\\n  \\\"current_price_usd\\\": {\\n    \\\"value\\\": \\\"78347\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_24h_percent\\\": {\\n    \\\"value\\\": \\\"-0.94\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_7d_percent\\\": {\\n    \\\"value\\\": \\\"0.25\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_1y_percent\\\": {\\n    \\\"value\\\": \\\"-29.54\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"market_cap_usd\\\": {\\n    \\\"value\\\": \\\"1.57T\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"fully_diluted_market_cap_usd\\\": {\\n    \\\"value\\\": \\\"1.64T\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"circulating_supply\\\": {\\n    \\\"value\\\": \\\"20.08M\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"max_supply\\\": {\\n    \\\"value\\\": \\\"21.00M\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"total_supply\\\": {\\n    \\\"value\\\": \\\"20.08M\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"open_interest_usd\\\": {\\n    \\\"value\\\": \\\"26.41B\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"liquidations_24h_usd\\\": {\\n    \\\"value\\\": \\\"21.88M\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"funding_rate_percent\\\": {\\n    \\\"value\\\": \\\"0.0058\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"trading_volume_24h_usd\\\": {\\n    \\\"value\\\": \\\"23.40B\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_1m_percent\\\": {\\n    \\\"value\\\": \\\"21.36\\\",\\n    \\\"source\\\": \\\"https://id.tradingview.com/symbols/BTCUSD/\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_usd_coindesk\\\": {\\n    \\\"value\\\": \\\"78378.18\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_24h_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"-1.35\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_7d_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"1.26\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_1m_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"20.85\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_1y_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"-30.06\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_ytd_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"-10.46\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"price_change_all_time_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"158.31M\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"market_cap_usd_coindesk\\\": {\\n    \\\"value\\\": \\\"1.57T\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"volume_24h_usd_coindesk\\\": {\\n    \\\"value\\\": \\\"11.08B\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"fully_diluted_valuation_usd_coindesk\\\": {\\n    \\\"value\\\": \\\"1.65T\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"volume_to_market_cap_ratio_24h_percent_coindesk\\\": {\\n    \\\"value\\\": \\\"0.70\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"total_supply_coindesk\\\": {\\n    \\\"value\\\": \\\"20.08M BTC\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"max_supply_coindesk\\\": {\\n    \\\"value\\\": \\\"21.00M BTC\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"circulating_supply_coindesk\\\": {\\n    \\\"value\\\": \\\"20.08M BTC\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"launch_date\\\": {\\n    \\\"value\\\": \\\"2009-01-03\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"block_number\\\": {\\n    \\\"value\\\": \\\"966030\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"block_reward\\\": {\\n    \\\"value\\\": \\\"3.13\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"last_block_size\\\": {\\n    \\\"value\\\": \\\"1507904\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"network_hashrate_hs\\\": {\\n    \\\"value\\\": \\\"868884085.20T\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"website\\\": {\\n    \\\"value\\\": \\\"bitcoin.org\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"block_explorer\\\": {\\n    \\\"value\\\": \\\"blockchain.info\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"repository\\\": {\\n    \\\"value\\\": \\\"github.com/bitcoin/bitcoin\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"hashing_algorithm\\\": {\\n    \\\"value\\\": \\\"SHA-256\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"supported_standards\\\": {\\n    \\\"value\\\": \\\"BRC-20\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"industry\\\": {\\n    \\\"value\\\": \\\"Payment\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"community\\\": {\\n    \\\"value\\\": \\\"bitcointalk.org\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  },\\n  \\\"exchange_prices\\\": {\\n    \\\"value\\\": \\\"Binance: 78389.16 USDT (-1.31%), Bybit: 78391.60 USDT (-1.31%), Gateio: 78396.80 USDT, Okex: 78388.80 USDT, Bullish: 78360.07 USDC (-1.36%)\\\",\\n    \\\"source\\\": \\\"https://www.coindesk.com/id/price/bitcoin\\\",\\n    \\\"source_type\\\": \\\"datasheet\\\"\\n  }\\n}\"}"


class FakeLLM:
    """Stub matching LLMAnalyzer.analyze()'s return contract, returning
    the EXACT content the real LLM produced in the trace being replayed."""

    def analyze(self, system_prompt, user_query, temperature=0.1, model=None):
        output_msg = json.loads(RAW_OUTPUT)
        return {
            "content": output_msg["content"],
            "model": "deepseek-v4-flash",
            "requested_model": "deepseek-v4-flash",
            "tokens_input": 0,
            "tokens_output": 0,
            "api_cost": 0,
        }


def build_evidence():
    messages = json.loads(RAW_INPUT)
    user_content = messages[1]["content"]
    evidence_text = user_content.split("EVIDENCE:\n", 1)[1]
    evidence_text = evidence_text.split("\n\nReturn JSON:", 1)[0]

    blocks = evidence_text.split("### SUMBER ")[1:]  # drop empty prefix
    all_evidence = []
    for block in blocks:
        header, _, body = block.partition("\n")
        # header looks like: "1: https://...  (tipe: datasheet)"
        url_part = header.split(": ", 1)[1]
        url, _, type_part = url_part.partition(" (tipe: ")
        source_type = type_part.rstrip(")")
        all_evidence.append({
            "url": url.strip(),
            "content": body.strip(),
            "evidence_type": source_type.strip(),
            "doc_type": source_type.strip(),
        })
    return all_evidence


def main():
    all_evidence = build_evidence()
    print(f"Reconstructed {len(all_evidence)} evidence documents:")
    for e in all_evidence:
        print(f"  - {e['url']} ({e['evidence_type']}, {len(e['content'])} chars)")
    print()

    original_facts = json.loads(json.loads(RAW_OUTPUT)["content"])
    print(f"Original (real, pre-patch trace) extraction produced {len(original_facts)} facts.")
    print()

    fc = FactChecker(FakeLLM())
    checklist = [{"field_id": "facts", "label": "All facts"}]
    validated_facts, usage = fc.extract_facts_batch(all_evidence, checklist)

    print("=" * 100)
    print(f"VALIDATED (post-PATCH-3, through the REAL extract_facts_batch): {len(validated_facts)} / {len(original_facts)} facts survived")
    print("=" * 100)

    survived = set(validated_facts.keys())
    dropped = set(original_facts.keys()) - survived

    print("\nSURVIVED:")
    for k in sorted(survived):
        print(f"  {k} = {validated_facts[k].get('value')!r}")

    print("\nDROPPED (rejected by provenance/PATCH2/Step2/Step3 -- check server log for [FACT REJECT] lines):")
    for k in sorted(dropped):
        print(f"  {k} = {original_facts[k].get('value')!r}")

    print()
    print("=" * 100)
    print("CRITICAL CHECK -- the whole reason for this investigation:")
    for critical in ("current_price_usd", "price_usd_coindesk"):
        status = "PRESENT" if critical in validated_facts else "MISSING"
        print(f"  {critical}: {status}"
              + (f" = {validated_facts[critical].get('value')!r}" if critical in validated_facts else ""))
    print("=" * 100)


if __name__ == "__main__":
    main()
