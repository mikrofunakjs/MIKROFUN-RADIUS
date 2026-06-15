#!/usr/bin/env python3
import sys
import argparse
from radius_helper import send_disconnect_packet

def main():
    parser = argparse.ArgumentParser(description='Test RADIUS Disconnect-Request')
    parser.add_argument('router_ip', help='IP address of the Mikrotik router (VPN IP)')
    parser.add_argument('username', help='Username to disconnect')
    parser.add_argument('--secret', default='testing123', help='RADIUS shared secret (default: testing123)')
    parser.add_argument('--port', type=int, default=3799, help='CoA port (default: 3799)')
    
    args = parser.parse_args()
    
    print(f"[*] Sending Disconnect-Request to {args.router_ip}:{args.port}")
    print(f"[*] Target User: {args.username}")
    print(f"[*] Secret: {args.secret}")
    
    secret_bytes = args.secret.encode('utf-8')
    
    success, message = send_disconnect_packet(
        args.router_ip,
        secret_bytes,
        args.username,
        co_port=args.port
    )
    
    if success:
        print(f"\n[+] SUCCESS: {message}")
        print("    The user should be disconnected now.")
    else:
        print(f"\n[-] FAILED: {message}")
        print("\nTroubleshooting Tips:")
        print("1. Check if Mikrotik has incoming RADIUS enabled:")
        print("   /radius incoming set accept=yes port=3799")
        print("2. Check if firewall allows port 3799/udp")
        print("3. Check if Router IP matches the one Mikrotik is using")
        print("4. Check if RADIUS secret matches")

if __name__ == '__main__':
    main()
