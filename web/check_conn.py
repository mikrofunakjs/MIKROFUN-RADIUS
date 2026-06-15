#!/usr/bin/env python3
import socket
import sys
import subprocess
import time

def ping_test(ip):
    """Checks if IP is reachable via ping."""
    print(f"[*] Checking PING to {ip}...")
    try:
        # -c 1 (count), -W 2 (timeout seconds)
        output = subprocess.check_output(['ping', '-c', '1', '-W', '2', ip], stderr=subprocess.STDOUT)
        print("    [OK] Router is reachable via PING.")
        return True
    except subprocess.CalledProcessError:
        print("    [FAIL] Router is NOT reachable via PING.")
        print("    -> Check VPN connection.")
        print("    -> Check if VPS can reach the Router's IP.")
        return False

def udp_port_check(ip, port, timeout=3):
    """Checks if UDP port is 'open' (hard to verify with UDP, but we can try to send)."""
    print(f"[*] Checking UDP Port {port} to {ip}...")
    # UDP is connectionless, so 'connect' just sets the default destination.
    # We can't easily know if it's open without application layer response.
    # But we can check if we get an immediate 'Connection Refused' (ICMP).
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(b'', (ip, port))
        # If we don't get an ICMP error immediately, it *might* be open or dropped.
        print("    [?] UDP packet sent. Waited for error...")
        time.sleep(1)
        print("    [INFO] No immediate rejection. This assumes firewall permits it.")
        print("           (Note: If Mikrotik drops it silently, we won't know here without a valid packet)")
        return True
    except ConnectionRefusedError:
        print(f"    [FAIL] UDP Port {port} refused connection (ICMP Port Unreachable).")
        print("    -> Check '/radius incoming set accept=yes'")
        return False
    except socket.timeout:
        print("    [OK?] Socket timed out (Normal for UDP if silent drop).")
        return True
    except OSError as e:
        print(f"    [FAIL] Network unreachable or route missing: {e}")
        return False
    finally:
        sock.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 check_conn.py <ROUTER_IP>")
        sys.exit(1)
        
    target_ip = sys.argv[1]
    
    print("--- DIAGNOSTIC START ---")
    if ping_test(target_ip):
        print("\n[*] Connectivity seems OK.")
        udp_port_check(target_ip, 3799)
        print("\nSUGGESTION:")
        print("If PING works but Disconnect times out, the issue is likely:")
        print("1. RADIUS Secret Mismatch (Mikrotik drops packet silently)")
        print("2. CoA NOT enabled on Mikrotik (/radius incoming set accept=yes)")
        print("3. Firewall blocking UDP 3799")
    else:
        print("\n[!] CRITICAL: Router is unreachable.")
        print("The 'timed out' error is because the VPS cannot find the Router.")
