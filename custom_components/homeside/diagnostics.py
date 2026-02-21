"""Diagnostics data collection from Homeside device debug endpoints."""
from __future__ import annotations

import logging
import re
from typing import Any

from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)


async def get_debug_info(session: ClientSession, host: str) -> dict[str, Any]:
    """Get diagnostic information from device debug endpoints.
    
    Args:
        session: aiohttp ClientSession for making HTTP requests
        host: IP address or hostname of the Homeside device
        
    Returns:
        Dictionary with diagnostic data from /debug/* endpoints
    """
    result = {}
    
    # Get memory info from /debug/mem
    try:
        url = f"http://{host}/debug/mem"
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                html = await resp.text()
                _LOGGER.debug("Raw /debug/mem HTML: %s", html[:500])
                
                # Parse HEAP memory from table format:
                # <tr><td>HEAP</td><td>8192</td><td>164</td><td>8124</td><td>3744</td></tr>
                # Find HEAP row and extract the 4 values after it
                heap_match = re.search(r'<td>HEAP</td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>', html, re.IGNORECASE)
                if heap_match:
                    result["heap_available"] = int(heap_match.group(1))
                    result["heap_used"] = int(heap_match.group(2))
                    result["heap_max"] = int(heap_match.group(3))
                    result["heap_errors"] = int(heap_match.group(4))
                    
                _LOGGER.debug("Memory debug info parsed: avail=%s, used=%s, max=%s, errors=%s", 
                            result.get("heap_available"), 
                            result.get("heap_used"),
                            result.get("heap_max"),
                            result.get("heap_errors"))
    except Exception as e:
        _LOGGER.warning("Failed to get memory info from /debug/mem: %s", e)
    
    # Get OS info from /debug/os
    try:
        url = f"http://{host}/debug/os"
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                html = await resp.text()
                _LOGGER.debug("Raw /debug/os HTML: %s", html[:500])
                
                # Extract OS version - try multiple patterns
                version_match = re.search(r'version[^\d]*(\d+\.\d+(?:\.\d+)?(?:-\d+-\d+)?)', html, re.IGNORECASE)
                if version_match:
                    result["os_version"] = version_match.group(1)
                
                # Extract commit hash
                commit_match = re.search(r'Commit\s+([0-9a-f]{40})', html, re.IGNORECASE)
                if commit_match:
                    result["os_commit"] = commit_match.group(1)
                
                _LOGGER.debug("OS debug info: version=%s, commit=%s", 
                            result.get("os_version"),
                            result.get("os_commit"))
    except Exception as e:
        _LOGGER.warning("Failed to get OS info from /debug/os: %s", e)
    
    # Get network info from /debug/exoline
    try:
        url = f"http://{host}/debug/exoline"
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                html = await resp.text()
                
                # Extract network IP settings from table structure
                # <tr><td><b>Running IP settings</b></td><td>IP: </td><td>192.168.217.240</td></tr>
                ip_match = re.search(r'<td>IP:\s*</td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>', html)
                if ip_match:
                    result["network_ip"] = ip_match.group(1)
                
                nm_match = re.search(r'<td>NM:\s*</td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>', html)
                if nm_match:
                    result["network_netmask"] = nm_match.group(1)
                
                gw_match = re.search(r'<td>GW:\s*</td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>', html)
                if gw_match:
                    result["network_gateway"] = gw_match.group(1)
                
                # Extract DNS servers - look for DNS: label first, then subsequent <td> with IPs
                # <tr><td><b></b></td><td>DNS: </td><td>192.168.217.1</td></tr>
                # <tr><td><b></b></td><td></td><td>8.8.4.4</td></tr>
                dns_section = re.search(r'<td>DNS:\s*</td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>.*?<td></td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>', html, re.DOTALL)
                if dns_section:
                    result["network_dns1"] = dns_section.group(1)
                    result["network_dns2"] = dns_section.group(2)
                elif re.search(r'<td>DNS:\s*</td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>', html):
                    # Only one DNS server
                    dns_match = re.search(r'<td>DNS:\s*</td>\s*<td>(\d+\.\d+\.\d+\.\d+)</td>', html)
                    result["network_dns1"] = dns_match.group(1)
                
                # Extract EXOline sessions count
                match = re.search(r'EXOline TCP sessions[^\d]*(\d+)/(\d+)', html, re.IGNORECASE)
                if match:
                    result["exoline_sessions_active"] = int(match.group(1))
                    result["exoline_sessions_max"] = int(match.group(2))
                
                # Extract external IP if connected
                match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+\(reverse\)', html)
                if match:
                    result["external_connection"] = match.group(1)
                
                # Extract Modbus sessions
                match = re.search(r'Modbus TCP sessions[^\d]*(\d+)/(\d+)', html, re.IGNORECASE)
                if match:
                    result["modbus_sessions_active"] = int(match.group(1))
                    result["modbus_sessions_max"] = int(match.group(2))
                    
                _LOGGER.debug("Network debug info: IP=%s, NM=%s, GW=%s, DNS=%s/%s, EXOline=%s/%s, External=%s, Modbus=%s/%s",
                            result.get("network_ip"),
                            result.get("network_netmask"),
                            result.get("network_gateway"),
                            result.get("network_dns1"),
                            result.get("network_dns2"), 
                            result.get("exoline_sessions_active"),
                            result.get("exoline_sessions_max"),
                            result.get("external_connection"),
                            result.get("modbus_sessions_active"),
                            result.get("modbus_sessions_max"))
    except Exception as e:
        _LOGGER.warning("Failed to get network info from /debug/exoline: %s", e)
    
    # Get EXOcol tasks info from /debug/exocol_tasks
    try:
        url = f"http://{host}/debug/exocol_tasks"
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                html = await resp.text()
                
                # Count number of tasks (lines with .Cts files)
                tasks = re.findall(r'\.Cts</td>', html)
                if tasks:
                    result["exocol_tasks_count"] = len(tasks)
                
                # Extract total size
                totsize_match = re.search(r'<b>TotSize</b>.*?(\d+)', html, re.IGNORECASE)
                if totsize_match:
                    result["exocol_tasks_total_size"] = int(totsize_match.group(1))
                    
                _LOGGER.debug("EXOcol tasks info: count=%s, total_size=%s",
                            result.get("exocol_tasks_count"),
                            result.get("exocol_tasks_total_size"))
    except Exception as e:
        _LOGGER.warning("Failed to get EXOcol tasks info from /debug/exocol_tasks: %s", e)
    
    # Get EXOcol DPacs info from /debug/exocol_dpacs
    try:
        url = f"http://{host}/debug/exocol_dpacs"
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                html = await resp.text()
                
                # Extract total size
                tot_match = re.search(r'<b>Tot:</b>\s*(\d+)', html, re.IGNORECASE)
                if tot_match:
                    result["exocol_dpacs_total_size"] = int(tot_match.group(1))
                    
                _LOGGER.debug("EXOcol DPacs info: total_size=%s",
                            result.get("exocol_dpacs_total_size"))
    except Exception as e:
        _LOGGER.warning("Failed to get EXOcol DPacs info from /debug/exocol_dpacs: %s", e)
    
    # Get BACnet info from /debug/bacnet
    try:
        url = f"http://{host}/debug/bacnet"
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                html = await resp.text()
                
                # Extract version
                version_match = re.search(r'version[^\d]*(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)', html, re.IGNORECASE)
                if version_match:
                    result["bacnet_version"] = version_match.group(1)
                
                # Extract build number (can be negative)
                build_match = re.search(r'build[^\d-]*(-?\d+)', html, re.IGNORECASE)
                if build_match:
                    result["bacnet_build"] = int(build_match.group(1))
                
                # Extract device ID
                device_match = re.search(r'device\s+id[^\d]*(\d+)', html, re.IGNORECASE)
                if device_match:
                    result["bacnet_device_id"] = int(device_match.group(1))
                
                # Extract BACnet memory stats
                frame_match = re.search(r'frame[^\d]*(\d+)', html, re.IGNORECASE)
                if frame_match:
                    result["bacnet_mem_frame"] = int(frame_match.group(1))
                
                free_match = re.search(r'free[^\d]*(\d+)', html, re.IGNORECASE)
                if free_match:
                    result["bacnet_mem_free"] = int(free_match.group(1))
                
                # Extract allocation result status from table structure
                # <tr><td><b></b></td><td>Alloc. result</td><td>OK</td></tr>
                alloc_match = re.search(r'<td>Alloc\.?\s+result</td>\s*<td>([^<]+)</td>', html, re.IGNORECASE)
                if alloc_match:
                    result["bacnet_alloc_result"] = alloc_match.group(1).strip()
                    
                _LOGGER.debug("BACnet debug info: version=%s, build=%s, device_id=%s, mem_frame=%s, mem_free=%s, alloc=%s",
                            result.get("bacnet_version"),
                            result.get("bacnet_build"),
                            result.get("bacnet_device_id"),
                            result.get("bacnet_mem_frame"),
                            result.get("bacnet_mem_free"),
                            result.get("bacnet_alloc_result"))
    except Exception as e:
        _LOGGER.warning("Failed to get BACnet info from /debug/bacnet: %s", e)
    
    # Skip BACnet/IP - endpoint not available on this device
    
    _LOGGER.info("Complete debug info collected from all endpoints: %s", result)
    return result
