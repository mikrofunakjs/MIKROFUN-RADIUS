#!/usr/bin/env python3
import sys
import getpass
from mikrotik_api import MikrotikApi

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_api_login.py <ROUTER_IP>")
        sys.exit(1)

    host = sys.argv[1]
    user = input(f"API User for {host}: ")
    password = getpass.getpass("API Password: ")
    port = input("API Port [8728]: ")
    port = int(port) if port else 8728

    print(f"\n[*] Connecting to {host}:{port}...")
    api = MikrotikApi(host, port)
    
    if not api.connect():
        print("[!] Connection Failed. Check IP/Port and Firewall.")
        return

    print("[*] Port Open. Attempting Login...")
    if api.login(user, password):
        print("\n[+] LOGIN SUCCESS!")
        print("    Credentials are correct and API library works.")
        
        # Try to read identity
        print("[*] Reading Router Identity...")
        api.send_command(['/system/identity/print'])
        res = api.read_response()
        print(f"    Response: {res}")
        
        input("\nPress Enter to kick test (Try to find active users)...")
        api.send_command(['/ppp/active/print'])
        rows = api.read_response() # This only reads one chunk, simplistic test
        print(f"    Active Users Raw Data: {rows}")
        
    else:
        print("\n[-] LOGIN FAILED.")
        print("    Check username/password.")
        print("    Check Mikrotik Log for 'login failure' details.")

    api.close()

if __name__ == "__main__":
    main()
