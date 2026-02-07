#!/usr/bin/env python3
"""Test write functionality with a safe variable (0:273 - Parallelförskjutning)."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
parent_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(parent_dir))

from aiohttp import ClientSession

# Import from the package
from client import HomesideClient


async def test_write():
    """Test write functionality."""
    host = "192.168.217.240"
    
    async with ClientSession() as session:
        client = HomesideClient(host, session)
        
        try:
            print("Connecting to device...")
            await client.connect()
            print(f"✅ Connected to {client.identity.controller_name}")
            print(f"   Serial: {client.identity.serial}")
            print()
            
            # Test variable: 0:273 - Parallelförskjutning (safe to test with)
            test_var = "0:273"
            
            # Read current value
            print(f"Reading current value of {test_var}...")
            values = await client.read_points([test_var])
            current_value = values.get(test_var)
            print(f"Current value: {current_value}")
            print()
            
            if current_value is None:
                print("❌ Cannot read current value - aborting test")
                return
            
            # Calculate test value (small offset from current)
            test_value = float(current_value) + 0.5
            
            # Ensure we stay within safe bounds (-5 to +5)
            if test_value > 5.0:
                test_value = -5.0
            
            print(f"Writing test value: {test_value}")
            print("⚠️  WARNING: This will modify the heating system!")
            print("Press Ctrl+C within 5 seconds to abort...")
            
            try:
                await asyncio.sleep(5)
            except KeyboardInterrupt:
                print("\n❌ Test aborted by user")
                return
            
            # Perform write
            print(f"\nWriting {test_var} = {test_value}...")
            success = await client.write_point(test_var, test_value)
            
            if success:
                print("✅ Write successful!")
                
                # Verify by reading back
                print("Verifying by reading back...")
                await asyncio.sleep(1)  # Wait a bit for value to settle
                values = await client.read_points([test_var])
                new_value = values.get(test_var)
                print(f"New value: {new_value}")
                
                if new_value is not None and abs(float(new_value) - test_value) < 0.01:
                    print("✅ Verification successful - value matches!")
                else:
                    print(f"⚠️  Value mismatch: expected {test_value}, got {new_value}")
                
                # Restore original value
                print(f"\nRestoring original value: {current_value}...")
                success = await client.write_point(test_var, float(current_value))
                
                if success:
                    print("✅ Original value restored!")
                    
                    # Final verification
                    await asyncio.sleep(1)
                    values = await client.read_points([test_var])
                    final_value = values.get(test_var)
                    print(f"Final value: {final_value}")
                else:
                    print("❌ Failed to restore original value!")
            else:
                print("❌ Write failed!")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await client.close()
            print("\nDisconnected from device")


if __name__ == "__main__":
    asyncio.run(test_write())
