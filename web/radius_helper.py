import socket
import struct
import hashlib
import hmac
import os
import random

# Constants
CODE_DISCONNECT_REQUEST = 40
ATTR_USER_NAME = 1
ATTR_NAS_IP_ADDRESS = 4
ATTR_MESSAGE_AUTH = 80

def send_disconnect_packet(nas_ip, secret, username, coa_port=3799):
    """
    Sends a Disconnect-Request to the NAS (Mikrotik).
    RFC 3576 / 5176 compliant.
    """
    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        
        # Packet Header parts
        code = CODE_DISCONNECT_REQUEST
        pkt_id = random.randint(0, 255)
        
        # Build Attributes
        attr_bytes = b''
        
        # 1. User-Name
        val = username.encode('utf-8')
        attr_bytes += struct.pack('BB', ATTR_USER_NAME, len(val) + 2) + val
        
        # 2. Message-Authenticator Placeholder (16 bytes of 0x00)
        # Required if Mikrotik has require-message-auth=yes
        attr_bytes += struct.pack('BB', ATTR_MESSAGE_AUTH, 18) + (b'\x00' * 16)
        
        # Calculate Length
        length = 20 + len(attr_bytes)
        
        # Calculate Request Authenticator (RFC 3576)
        # MD5(Code + ID + Length + 16 Zero Octets + Attributes + Secret)
        zero_auth = b'\x00' * 16
        auth_input = struct.pack('!BBH', code, pkt_id, length) + zero_auth + attr_bytes + secret
        req_auth = hashlib.md5(auth_input).digest()
        
        # Re-construct packet with Calculated Request Authenticator for HMAC calculation
        # Note: Message-Authenticator calculation uses the packet with the calculated Request Authenticator
        # HMAC-MD5(Secret, Code + ID + Length + ReqAuth + Attributes)
        pkt_for_hmac = struct.pack('!BBH', code, pkt_id, length) + req_auth + attr_bytes
        msg_auth = hmac.new(secret, pkt_for_hmac, hashlib.md5).digest()
        
        # Replace Message-Authenticator placeholder in attributes
        # Find position of Message-Authenticator (it's at the end)
        # The last 18 bytes are: Type(1) + Len(1) + Value(16)
        # We need to replace the last 16 bytes
        final_attrs = attr_bytes[:-16] + msg_auth
        
        # Final Packet
        final_pkt = struct.pack('!BBH', code, pkt_id, length) + req_auth + final_attrs
        
        # Send
        print(f"Sending Disconnect-Request to {nas_ip}:{coa_port} for user {username}")
        sock.sendto(final_pkt, (nas_ip, coa_port))
        
        # Wait for Disconnect-ACK (Code 41) or Disconnect-NAK (Code 42)
        data, addr = sock.recvfrom(1024)
        resp_code = data[0]
        
        if resp_code == 41:
            print("Received Disconnect-ACK (Success)")
            return True, "Disconnected successfully"
        elif resp_code == 42:
            print("Received Disconnect-NAK (Failed)")
            return False, "Router refused disconnect (User might be offline)"
        else:
            print(f"Received unknown code {resp_code}")
            return False, f"Unknown response code {resp_code}"
            
    except Exception as e:
        print(f"Disconnect error: {e}")
        return False, str(e)
    finally:
        sock.close()
