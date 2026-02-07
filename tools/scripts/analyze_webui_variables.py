#!/usr/bin/env python3
"""
Analyze CWAV files to discover all variables used in HomeSide web UI
Compares with variables.json to find missing variables
"""
import json
import re
from pathlib import Path
from collections import defaultdict

# Parse CWAV files
artifacts_dir = Path("tools/artifacts/unpacked")
cwav_files = list(artifacts_dir.glob("*.cwav.json"))

print(f"Found {len(cwav_files)} CWAV files")
print()

# Extract all EXOsocket variables
ui_variables = set()
variable_usage = defaultdict(list)

for cwav_file in cwav_files:
    content = cwav_file.read_text()
    
    # Find all EXOsocketSinglePokeAddr
    matches = re.findall(r'"EXOsocketSinglePokeAddr"\s*:\s*"(0:\d+)"', content)
    for match in matches:
        ui_variables.add(match)
        variable_usage[match].append(cwav_file.name)
    
    # Also find in advises arrays
    matches = re.findall(r'"advises"\s*:\s*\[(.*?)\]', content, re.DOTALL)
    for match in matches:
        vars_in_advise = re.findall(r'"(0:\d+)"', match)
        ui_variables.update(vars_in_advise)
        for v in vars_in_advise:
            variable_usage[v].append(f"{cwav_file.name} (advise)")
    
    # Find in variables arrays  
    matches = re.findall(r'"variables"\s*:\s*\[(.*?)\]', content, re.DOTALL)
    for match in matches:
        vars_in_array = re.findall(r'"(0:\d+)"', match)
        ui_variables.update(vars_in_array)
        for v in vars_in_array:
            variable_usage[v].append(f"{cwav_file.name} (variable)")

print(f"Found {len(ui_variables)} unique variables in web UI")
print()

# Load our variables.json
variables_json_path = Path("custom_components/homeside/variables.json")
if variables_json_path.exists():
    with open(variables_json_path) as f:
        known_variables = set(json.load(f).keys())
    
    print(f"Our variables.json has {len(known_variables)} variables")
    print()
    
    # Find missing variables
    missing = sorted(ui_variables - known_variables, key=lambda x: int(x.split(':')[1]))
    
    if missing:
        print(f"🔍 Found {len(missing)} variables in UI that are NOT in variables.json:")
        print()
        for var in missing[:30]:  # Show first 30
            files = variable_usage[var][:3]  # First 3 files
            print(f"  {var} - used in: {', '.join(files)}")
        
        if len(missing) > 30:
            print(f"  ... and {len(missing) - 30} more")
    else:
        print("✓ All UI variables are in variables.json!")
    
    print()
    
    # Find interesting patterns
    print("📊 Variable usage statistics:")
    sorted_usage = sorted(variable_usage.items(), key=lambda x: len(x[1]), reverse=True)
    print()
    print("Most frequently used variables:")
    for var, files in sorted_usage[:10]:
        print(f"  {var}: used {len(files)} times")
        if var in known_variables:
            # Try to load variable info
            pass
else:
    print("⚠️  variables.json not found")

# Analyze editable variables
print()
print("🔧 Analyzing editable variables in UI...")
editable_vars = set()
for cwav_file in cwav_files:
    content = cwav_file.read_text()
    
    # Find Numeric/Text with DialogBox or Editable
    pattern = r'"type"\s*:\s*"(Numeric|Text)".*?"EXOsocketSinglePokeAddr"\s*:\s*"(0:\d+)".*?"ManeuverStyle"\s*:\s*"(DialogBox|Editable)"'
    matches = re.findall(pattern, content, re.DOTALL)
    for match in matches:
        editable_vars.add(match[1])

print(f"Found {len(editable_vars)} editable variables in UI")
print()

# Show some examples
if editable_vars:
    print("Examples of editable variables:")
    for var in sorted(editable_vars)[:15]:
        print(f"  {var}")
