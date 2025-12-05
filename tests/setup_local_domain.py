"""
Helper script to add custom domain to Windows hosts file for local testing
Run this script as Administrator!
"""
import os
import sys
import platform

def add_to_hosts(domain="loopfeedback.dev", ip="127.0.0.1"):
    """Add domain to hosts file"""
    
    # Determine hosts file location based on OS
    if platform.system() == "Windows":
        hosts_path = r"C:\Windows\System32\drivers\etc\hosts"
    elif platform.system() == "Linux" or platform.system() == "Darwin":  # macOS
        hosts_path = "/etc/hosts"
    else:
        print(f"❌ Unsupported OS: {platform.system()}")
        return False
    
    # Check if running as admin (Windows)
    if platform.system() == "Windows":
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            if not is_admin:
                print("❌ This script must be run as Administrator!")
                print("Right-click and select 'Run as administrator'")
                return False
        except:
            pass
    
    try:
        # Read current hosts file
        with open(hosts_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if domain already exists
        if domain in content:
            print(f"✅ Domain {domain} already exists in hosts file")
            return True
        
        # Add domain to hosts file
        entry = f"\n{ip}\t{domain}\n"
        
        with open(hosts_path, 'a', encoding='utf-8') as f:
            f.write(entry)
        
        print(f"✅ Successfully added {domain} -> {ip} to hosts file")
        print(f"   Location: {hosts_path}")
        print(f"\nYou can now use http://{domain} for local testing!")
        return True
        
    except PermissionError:
        print("❌ Permission denied! Please run as Administrator (Windows) or with sudo (Linux/Mac)")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def remove_from_hosts(domain="loopfeedback.dev"):
    """Remove domain from hosts file"""
    if platform.system() == "Windows":
        hosts_path = r"C:\Windows\System32\drivers\etc\hosts"
    elif platform.system() == "Linux" or platform.system() == "Darwin":
        hosts_path = "/etc/hosts"
    else:
        print(f"❌ Unsupported OS: {platform.system()}")
        return False
    
    try:
        with open(hosts_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Filter out lines containing the domain
        new_lines = [line for line in lines if domain not in line]
        
        with open(hosts_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        print(f"✅ Removed {domain} from hosts file")
        return True
        
    except PermissionError:
        print("❌ Permission denied! Please run as Administrator")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage custom domain in hosts file")
    parser.add_argument("--domain", default="loopfeedback.dev", help="Domain name")
    parser.add_argument("--ip", default="127.0.0.1", help="IP address")
    parser.add_argument("--remove", action="store_true", help="Remove domain from hosts file")
    
    args = parser.parse_args()
    
    if args.remove:
        remove_from_hosts(args.domain)
    else:
        add_to_hosts(args.domain, args.ip)

