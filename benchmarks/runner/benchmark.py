import sys
sys.path.insert(0, "/home/arman/research-assistant")
import json
import os
import requests

BENCHMARK_DIR = "/home/arman/research-assistant/benchmarks"
API = "http://localhost:8000/research"

FIELD_ALIASES = {
    # Audio
    "nominal_power_handling": ["nominal_power_handling", "nominal_power", "power_rms", "rms_power", "power_output_nominal_rms", "power_output_nominal"],
    "program_power": ["program_power", "peak_power", "max_power", "power_output_program_max", "power_output_program"],
    "frequency_response": ["frequency_response", "freq_response", "frequency_range"],
    "impedance": ["impedance", "nominal_impedance", "impedance_ohm"],
    "sensitivity": ["sensitivity", "spl", "sound_pressure_level"],
    "fs": ["fs", "resonant_frequency", "resonance"],
    "qts": ["qts", "total_q"],
    "qes": ["qes", "electrical_q"],
    "qms": ["qms", "mechanical_q"],
    "vas": ["vas", "equivalent_volume"],
    "xmax": ["xmax", "max_excursion", "linear_excursion"],
    "bl_product": ["bl_product", "bl", "force_factor"],
    "sd": ["sd", "cone_area", "effective_cone_area"],
    "magnet_weight": ["magnet_weight", "magnet_mass"],
    "voice_coil_diameter": ["voice_coil_diameter", "coil_diameter", "vc_diameter"],
    "speaker_diameter": ["speaker_diameter", "driver_size", "speaker_size", "diameter"],
    "speaker_weight": ["speaker_weight", "net_weight", "driver_weight"],
    # IoT
    "cpu": ["cpu", "cpu_cores", "cpu_core_count", "processor", "cpu_model", "chipset"],
    "cpu_frequency": ["cpu_frequency", "clock_speed", "cpu_clock", "frequency"],
    "flash_memory": ["flash_memory", "flash", "spi_flash", "external_flash"],
    "sram": ["sram", "static_ram", "psram"],
    "rom": ["rom", "read_only_memory"],
    "wifi_standard": ["wifi_standard", "wifi", "wifi_version", "802.11"],
    "bluetooth_version": ["bluetooth_version", "bluetooth", "bt_version", "ble"],
    "gpio_pins": ["gpio_pins", "gpio", "gpio_count", "digital_pins"],
    "adc": ["adc", "analog_input", "adc_channels", "analog_pins"],
    "dac": ["dac", "analog_output", "dac_channels"],
    "operating_voltage": ["operating_voltage", "supply_voltage", "vdd", "voltage"],
    "operating_temperature": ["operating_temperature", "temperature_range", "temp_range"],
    "peripherals": ["peripherals", "interfaces", "connectivity"],
    # Network
    "architecture": ["architecture", "cpu_architecture", "arch"],
    "ram": ["ram", "memory", "system_memory", "dram"],
    "storage": ["storage", "flash", "flash_memory", "nand"],
    "ethernet_ports": ["ethernet_ports", "ethernet", "eth_ports", "rj45", "gigabit_ports", "ethernet_2_5g_ports", "ethernet_ports_1g", "ethernet_ports_2_5g"],
    "sfp_plus": ["sfp_plus", "sfp", "sfp_port", "10g_port", "sfp_plus_port"],
    "poe": ["poe", "power_over_ethernet", "poe_in", "poe_out", "poe_support"],
    "license_level": ["license_level", "license", "routeros_license"],
    "max_power_consumption": ["max_power_consumption", "power_consumption", "power_draw", "max_power", "power_input", "power_supply"],
    "weight": ["weight", "net_weight", "gross_weight", "speaker_weight"],
    "dimensions": ["dimensions", "size", "width", "height", "depth"],
}

def resolve_field(field: str) -> set:
    return set(FIELD_ALIASES.get(field, [field]))

def run_benchmark():
    results = []
    total_expected = 0
    total_found = 0
    
    for domain in sorted(os.listdir(BENCHMARK_DIR)):
        domain_path = os.path.join(BENCHMARK_DIR, domain)
        if not os.path.isdir(domain_path) or domain == "runner":
            continue
        
        query_file = os.path.join(domain_path, "query.txt")
        expected_file = os.path.join(domain_path, "expected_fields.json")
        
        if not os.path.exists(query_file) or not os.path.exists(expected_file):
            continue
        
        with open(query_file) as f:
            query = f.read().strip()
        with open(expected_file) as f:
            expected = json.load(f)
        
        print(f"Running: {domain}...")
        resp = requests.post(API, json={"query": query}, timeout=180)
        data = resp.json()
        
        extracted = set(data.get("filled_fields", []))
        
        found = []
        missing = []
        
        for field in expected:
            aliases = resolve_field(field)
            if extracted & aliases:
                found.append(field)
            else:
                missing.append(field)
        
        coverage = len(found) / len(expected) * 100 if expected else 0
        
        results.append({
            "domain": domain,
            "coverage": round(coverage, 1),
            "found": len(found),
            "expected": len(expected),
            "found_fields": found,
            "missing_fields": missing,
            "extracted_all": sorted(extracted),
            "break_reason": data.get("break_reason"),
            "api_cost": data.get("api_cost"),
        })
        
        total_expected += len(expected)
        total_found += len(found)
    
    print()
    print("=" * 60)
    print("BENCHMARK RESULTS v4")
    print("=" * 60)
    
    for r in results:
        status = "✅" if r["coverage"] >= 80 else "⚠️" if r["coverage"] >= 60 else "❌"
        print(f"{status} {r['domain']}: {r['found']}/{r['expected']} ({r['coverage']}%) | {r['break_reason']} | \${r['api_cost']:.4f}")
        if r["missing_fields"]:
            print(f"   Missing: {', '.join(r['missing_fields'][:5])}")
    
    overall = total_found / total_expected * 100 if total_expected else 0
    print(f"\nOVERALL: {total_found}/{total_expected} ({overall:.1f}%)")
    
    with open(os.path.join(BENCHMARK_DIR, "results.json"), "w") as f:
        json.dump({"results": results, "overall_coverage": round(overall, 1)}, f, indent=2)

if __name__ == "__main__":
    run_benchmark()
