import os
import sys
from werkzeug.security import generate_password_hash

# Add current dir to path to import web components
sys.path.append(os.getcwd())

try:
    from web.database import execute_query
except ImportError:
    print("Error: Could not find web.database. Make sure you are in the project root directory.")
    sys.exit(1)

def list_users():
    users = execute_query("SELECT id, username, role FROM users", fetch=True)
    if not users:
        print("\n[!] No users found in database.")
        return []
    
    print("\n--- Current Users ---")
    for u in users:
        print(f"ID: {u['id']} | Username: {u['username']} | Role: {u['role']}")
    print("---------------------\n")
    return users

def main():
    print("========================================")
    print("   MikroFun Admin Account Recovery      ")
    print("========================================")
    
    users = list_users()
    
    target_user = input("Enter username to reset (or leave blank to cancel): ").strip()
    if not target_user:
        print("Cancelled.")
        return

    # Check if user exists
    user = execute_query("SELECT * FROM users WHERE username=%s", (target_user,), fetch_one=True)
    if not user:
        print(f"Error: User '{target_user}' not found.")
        
        create_new = input(f"Would you like to CREATE a new admin user '{target_user}'? (y/n): ").lower()
        if create_new == 'y':
            new_pass = input(f"Enter new password for '{target_user}': ")
            if len(new_pass) < 4:
                print("Error: Password too short!")
                return
            
            hashed_pw = generate_password_hash(new_pass)
            execute_query("INSERT INTO users (username, password, role) VALUES (%s, %s, 'admin')", (target_user, hashed_pw))
            print(f"SUCCESS: Admin user '{target_user}' created with new password.")
        return

    new_pass = input(f"Enter new password for '{target_user}': ")
    if len(new_pass) < 4:
        print("Error: Password too short!")
        return

    hashed_pw = generate_password_hash(new_pass)
    
    # Update password and ensure role is admin
    try:
        execute_query(
            "UPDATE users SET password=%s, role='admin' WHERE username=%s",
            (hashed_pw, target_user)
        )
        print(f"\n[OK] Password for user '{target_user}' has been updated.")
        print(f"[OK] Role for user '{target_user}' has been promoted to 'admin'.")
        print("\nYou can now login to the web panel.")
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    main()
