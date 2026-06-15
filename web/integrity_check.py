import os
import hashlib
import sys

def get_file_hash(filepath):
    """Calculate SHA-256 hash of a file."""
    if not os.path.exists(filepath):
        return None
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def verify_integrity():
    """Verify hashes of critical system files."""
    # Manifest file is usually generated during build
    manifest_path = os.path.join(os.path.dirname(__file__), 'manifest.bin')
    
    # --- DEVELOPER BYPASS ---
    # If MIKROFUN_DEV environment variable is set, skip integrity check.
    # This allows developers to edit the source code without breaking the manifest.
    if os.environ.get('MIKROFUN_DEV') == '1':
        print("DEBUG: Integrity check bypassed (Developer Mode)")
        return True

    # If we are in source-code mode and no manifest exists, we can skip.
    if not os.path.exists(manifest_path):
        if getattr(sys, 'frozen', False):
            # If manifest is missing in production/frozen mode, something is wrong
            print("CRITICAL: Integrity manifest missing in production!")
            return False
        return True

    try:
        import json
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        base_dir = os.path.dirname(os.path.dirname(__file__)) # Parent of 'web'
        
        for rel_path, expected_hash in manifest.items():
            # Normalize path for current OS: replace / or \ with correct os.sep
            norm_rel_path = rel_path.replace('\\', os.sep).replace('/', os.sep)
            abs_path = os.path.join(base_dir, norm_rel_path)
            actual_hash = get_file_hash(abs_path)
            
            if actual_hash != expected_hash:
                print(f"SECURITY ALERT: Tampering detected in {norm_rel_path}!")
                return False
                
        return True
    except Exception as e:
        print(f"Integrity check error: {e}")
        return False

if __name__ == "__main__":
    if verify_integrity():
        print("Integrity OK")
    else:
        print("Integrity FAILED")
        sys.exit(1)
