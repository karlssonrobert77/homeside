#!/usr/bin/env python3
"""Test all Home Assistant platforms."""
import asyncio
import sys
from pathlib import Path

# Add root directory to path
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

import aiohttp
from client import HomesideClient
import json


async def test_platforms(host: str):
    """Test all platform entity creation."""
    print("🧪 Testing HomeSide Home Assistant Integration\n")
    
    # Load variables
    variables_file = ROOT_DIR / "variables.json"
    with open(variables_file) as f:
        variables_data = json.load(f)
    
    mapping = variables_data.get("mapping", {})
    
    # Connect to device
    async with aiohttp.ClientSession() as session:
        client = HomesideClient(host, session)
        await client.connect()
        
        print("✅ Connected to device\n")
        
        # Test reading all enabled variables
        enabled_addresses = [
            addr for addr, config in mapping.items()
            if config.get("enabled", False)
        ]
        
        print(f"📊 Testing {len(enabled_addresses)} enabled variables...\n")
        
        values, errors = await client.read_points_with_errors(enabled_addresses)
        
        # Group by type
        sensors = []
        binary_sensors = []
        numbers = []
        switches = []
        selects = []
        
        for addr in enabled_addresses:
            config = mapping[addr]
            var_type = config.get("type", "sensor")
            access = config.get("access", "read")
            name = config.get("name", addr)
            value = values.get(addr)
            error = errors.get(addr)
            
            entity_info = {
                "address": addr,
                "name": name,
                "value": value,
                "error": error,
                "access": access
            }
            
            if var_type == "sensor":
                if access == "read_write" and isinstance(value, (int, float)) and value in [0, 1, 2]:
                    # Mode selector (select platform)
                    selects.append(entity_info)
                else:
                    sensors.append(entity_info)
            elif var_type == "binary_sensor":
                if access == "read_write":
                    switches.append(entity_info)
                else:
                    binary_sensors.append(entity_info)
            elif var_type == "number":
                numbers.append(entity_info)
        
        # Print results by platform
        print("=" * 60)
        print("SENSOR PLATFORM")
        print("=" * 60)
        print(f"Total: {len(sensors)} sensors\n")
        for s in sensors[:10]:
            status = "✅" if s['value'] is not None and not s['error'] else "❌"
            val_str = f"{s['value']}" if s['value'] is not None else "None"
            if s['error']:
                val_str = f"Error {s['error'].get('code')}: {s['error'].get('text', 'Unknown')}"
            print(f"{status} {s['address']}: {s['name']}")
            print(f"   Value: {val_str}\n")
        
        if len(sensors) > 10:
            print(f"... and {len(sensors) - 10} more sensors\n")
        
        print("=" * 60)
        print("BINARY_SENSOR PLATFORM")
        print("=" * 60)
        print(f"Total: {len(binary_sensors)} binary sensors\n")
        for s in binary_sensors[:10]:
            status = "✅" if s['value'] is not None and not s['error'] else "❌"
            val_str = "ON" if s['value'] else "OFF"
            if s['error']:
                val_str = f"Error {s['error'].get('code')}"
            print(f"{status} {s['address']}: {s['name']}")
            print(f"   State: {val_str}\n")
        
        if len(binary_sensors) > 10:
            print(f"... and {len(binary_sensors) - 10} more binary sensors\n")
        
        print("=" * 60)
        print("SWITCH PLATFORM")
        print("=" * 60)
        print(f"Total: {len(switches)} switches\n")
        for s in switches[:10]:
            status = "✅" if s['value'] is not None and not s['error'] else "❌"
            val_str = "ON" if s['value'] else "OFF"
            if s['error']:
                val_str = f"Error {s['error'].get('code')}"
            print(f"{status} {s['address']}: {s['name']}")
            print(f"   State: {val_str}\n")
        
        if len(switches) > 10:
            print(f"... and {len(switches) - 10} more switches\n")
        
        print("=" * 60)
        print("SELECT PLATFORM")
        print("=" * 60)
        print(f"Total: {len(selects)} select entities\n")
        mode_names = {0: "Off/0%", 1: "Manual/On", 2: "Auto"}
        for s in selects:
            status = "✅" if s['value'] is not None and not s['error'] else "❌"
            val_str = mode_names.get(s['value'], f"Unknown ({s['value']})")
            if s['error']:
                val_str = f"Error {s['error'].get('code')}"
            print(f"{status} {s['address']}: {s['name']}")
            print(f"   Mode: {val_str}\n")
        
        print("=" * 60)
        print("NUMBER PLATFORM")
        print("=" * 60)
        print(f"Total: {len(numbers)} number entities\n")
        for s in numbers[:5]:
            status = "✅" if s['value'] is not None and not s['error'] else "❌"
            val_str = f"{s['value']}" if s['value'] is not None else "None"
            if s['error']:
                val_str = f"Error {s['error'].get('code')}: {s['error'].get('text', 'Unknown')}"
            print(f"{status} {s['address']}: {s['name']}")
            print(f"   Value: {val_str}\n")
        
        if len(numbers) > 5:
            print(f"... and {len(numbers) - 5} more number entities\n")
        
        # Summary
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"✅ Sensors: {len(sensors)}")
        print(f"✅ Binary Sensors: {len(binary_sensors)}")
        print(f"✅ Switches: {len(switches)}")
        print(f"✅ Selects: {len(selects)}")
        print(f"✅ Numbers: {len(numbers)}")
        print(f"━" * 60)
        print(f"📊 Total Entities: {len(sensors) + len(binary_sensors) + len(switches) + len(selects) + len(numbers)}")
        print(f"✅ Readable: {len(values)}/{len(enabled_addresses)}")
        print(f"❌ Errors: {len(errors)}")
        
        if errors:
            print(f"\n⚠️  Blocked variables (need auth):")
            for addr, err in errors.items():
                name = mapping[addr].get("name", addr)
                print(f"   {addr}: {name} - Error {err.get('code')}: {err.get('text', 'Unknown')}")
        
        await client.close()
        
        print("\n✅ All platform tests completed!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test HA platforms")
    parser.add_argument("--host", required=True, help="HomeSide device IP")
    args = parser.parse_args()
    
    asyncio.run(test_platforms(args.host))
