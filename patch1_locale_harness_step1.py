"""
PATCH1 numeric-fidelity gate -- Step 1: isolated reproduction harness.

Imports the REAL, currently-deployed _value_supported_by_source() from
hermes_agent/fact_checker.py (not a reimplementation) and runs it against
every fact that was silently rejected in live trace
01f3a9ee80d71aafc971ec5b6543daa8 (BTC price research, 2026-09-08), to
formally and deterministically prove the locale-mismatch false-reject --
plus two sanity controls (already-surviving CoinDesk facts) and one
negative control (a fabricated value, mirroring PATCH1's original bug
case) to prove we are not about to break the gate's original purpose.

This script does NOT propose or apply any fix. It only reproduces and
quantifies the current (OLD) behavior.

Run from the exact same cwd the uvicorn process uses:
    cd ~/research-assistant
    python3 patch1_locale_harness_step1.py
"""
import sys

sys.path.insert(0, ".")

from hermes_agent.fact_checker import _value_supported_by_source as OLD


# Each case: (field_id, extracted_value, raw_source_snippet, expected_accept)
# expected_accept=True  -> a human reading the source would agree this
#                           value genuinely IS present/correct there, so
#                           OLD *should* accept it (True). If OLD instead
#                           returns False, that is a proven false-reject.
# expected_accept=False -> the value is fabricated / not really in the
#                           source; OLD *should* reject it (False). This
#                           is PATCH1's original bug case, used here as a
#                           negative control.
CASES = [
    # --- TradingView (id.tradingview.com/symbols/BTCUSD) -- Indonesian
    #     locale formatting throughout the raw page ---
    ("current_price_usd", "78347",
     "Harga Bitcoin (BTC) saat ini adalah: 78.347 USD", True),
    ("price_change_24h_percent", "-0.94",
     "telah turun sebesar -0,94% dalam 24 jam terakhir", True),
    ("price_change_7d_percent", "0.25",
     "Harga Bitcoin telah naik sebesar: 0,25", True),
    ("price_change_1y_percent", "-29.54",
     "Bitcoin mengalami penurunan sebesar: -29,54", True),
    ("market_cap_usd", "1.57T",
     "Kapitalisasi pasar: 1,57 T USD", True),
    ("fully_diluted_market_cap_usd", "1.64T",
     "Cap Pasar Terdilusi Sepenuhnya: 1,64 T USD", True),
    ("circulating_supply", "20.08M",
     "Suplai sirkulasi: 20,08 M", True),
    ("max_supply", "21.00M",
     "Suplai maksimum: 21,00 M", True),
    ("total_supply", "20.08M",
     "Total suplai: 20,08 M", True),
    ("open_interest_usd", "26.41B",
     "Minat terbuka 26,41 B USD 0,93%", True),
    ("liquidations_24h_usd", "21.88M",
     "Likuidasi (24h) 21,88 M USD", True),
    ("funding_rate_percent", "0.0058",
     "Funding Rate: 0,0058%", True),
    ("trading_volume_24h_usd", "23.40B",
     "volume trading Bitcoin (BTC) dalam 24 jam adalah 23,40 B USD", True),
    ("price_change_1m_percent", "21.36",
     "kinerja bulannya menunjukkan peningkatan sebesar 21,36 %", True),

    # --- CoinDesk price-ticker block (coindesk.com/id/price/bitcoin) --
    #     also Indonesian locale in this block ---
    ("price_usd_coindesk", "78378.18",
     "Bitcoin BTC #1 $78.378,18 Turun 1,35 persen", True),
    ("block_number", "966030",
     "Nomor Blok 966,030", True),
    ("block_reward", "3.13",
     "Hadiah Blok 3,13", True),
    ("last_block_size", "1507904",
     "Ukuran Blok Terakhir 1,507,904", True),
    ("volume_to_market_cap_ratio_24h_percent_coindesk", "0.70",
     "Vol/Kap. Pasar (24j) 0,70%", True),
    ("exchange_prices", "78389.16",
     "BTC-USDT BTCUSDT Binance AA : 78.389,16 USDT: -1,31%", True),

    # --- Sanity controls: CoinDesk stat-box block, already English-style
    #     formatted in the raw page -- OLD is already known to accept
    #     these live. If the harness disagrees, the harness itself (not
    #     the gate) has a bug and must be fixed before trusting it. ---
    ("market_cap_usd_coindesk", "1.57T",
     "Kapitalisasi Pasar $1.57T Turun 1,35 persen", True),
    ("total_supply_coindesk", "20.08M BTC",
     "Total Pasokan 20.08M BTC", True),

    # --- Negative control: fabricated value not present in source at all,
    #     mirroring PATCH1's original bug case (ACR 12500 Black
    #     port_width/port_height fabricated from a page that never
    #     mentioned those dimensions). Must stay REJECTED. ---
    ("fabricated_port_width", "12-inch",
     "This enclosure ships in three trim colors and a padded travel case.", False),
]


def main():
    n_ok = 0
    n_bug = 0
    print(f"{'field_id':50s} {'extracted':12s} {'OLD':6s} {'expected':9s} status")
    print("-" * 100)
    for field_id, value, source, expected_accept in CASES:
        old_result = OLD(value, source)
        ok = (old_result == expected_accept)
        n_ok += ok
        n_bug += (not ok)
        if ok:
            tag = "ok"
        elif expected_accept:
            tag = "FALSE-REJECT (bug reproduced)"
        else:
            tag = "UNEXPECTED-ACCEPT (would break PATCH1's original intent)"
        print(f"{field_id:50s} {value:12s} {str(old_result):6s} {str(expected_accept):9s} {tag}")

    print("-" * 100)
    print(f"Matches expectation: {n_ok}/{len(CASES)}")
    print(f"Mismatches: {n_bug}/{len(CASES)}")


if __name__ == "__main__":
    main()
