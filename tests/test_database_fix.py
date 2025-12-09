"""
Test script to verify database connection fix for API execution.
This script tests that the DATABASE_URL environment variable is properly passed to subprocess.
"""
import asyncio
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

async def test_database_url_passing():
    """Test that database URL is properly passed to subprocess."""
    from app.services.venv_execution_service import venv_execution_service
    
    # Test code that checks for DATABASE_URL environment variable
    test_code = '''
import os
import json

async def run(file_bytes=None, input_data=None):
    """Test function that checks if DATABASE_URL is set."""
    database_url = os.getenv('DATABASE_URL')
    
    return {
        "database_url_present": database_url is not None,
        "database_url_value": database_url if database_url else "NOT SET",
        "message": "success"
    }
'''
    
    # Test with database URL
    test_database_url = "postgresql://testuser:testpass@localhost:5432/testdb"
    
    print("Testing database URL passing to subprocess...")
    print(f"Test database URL: {test_database_url}")
    print()
    
    try:
        result = await venv_execution_service.execute_api_in_venv(
            code=test_code,
            input_data={},
            file_bytes=None,
            timeout_seconds=10,
            auto_install_dependencies=False,
            skip_dependency_check=True,
            database_url=test_database_url
        )
        
        print("✓ Execution successful!")
        print(f"Result: {result}")
        print()
        
        if result.get("database_url_present"):
            print("✓ DATABASE_URL environment variable was properly set!")
            print(f"  Value received: {result.get('database_url_value')}")
            
            if result.get('database_url_value') == test_database_url:
                print("✓ DATABASE_URL value matches expected value!")
                print()
                print("=" * 60)
                print("SUCCESS: Database URL is properly passed to subprocess!")
                print("=" * 60)
                return True
            else:
                print("✗ DATABASE_URL value doesn't match!")
                print(f"  Expected: {test_database_url}")
                print(f"  Got: {result.get('database_url_value')}")
                return False
        else:
            print("✗ DATABASE_URL environment variable was NOT set!")
            return False
            
    except Exception as e:
        print(f"✗ Execution failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_without_database_url():
    """Test that execution works without database URL (backwards compatibility)."""
    from app.services.venv_execution_service import venv_execution_service
    
    test_code = '''
import os

async def run(file_bytes=None, input_data=None):
    """Test function without database."""
    return {
        "message": "success",
        "database_url_present": os.getenv('DATABASE_URL') is not None
    }
'''
    
    print("\nTesting execution WITHOUT database URL (backwards compatibility)...")
    
    try:
        result = await venv_execution_service.execute_api_in_venv(
            code=test_code,
            input_data={},
            file_bytes=None,
            timeout_seconds=10,
            auto_install_dependencies=False,
            skip_dependency_check=True,
            database_url=None  # No database URL
        )
        
        print("✓ Execution successful without database URL!")
        print(f"Result: {result}")
        
        if not result.get("database_url_present"):
            print("✓ DATABASE_URL correctly not set when not provided!")
            return True
        else:
            print("⚠ DATABASE_URL was set even though none was provided")
            return True  # Still OK, might be from parent environment
            
    except Exception as e:
        print(f"✗ Execution failed: {e}")
        return False

async def main():
    """Run all tests."""
    print("=" * 60)
    print("Database Connection Fix Verification Tests")
    print("=" * 60)
    print()
    
    # Test 1: With database URL
    test1_passed = await test_database_url_passing()
    
    # Test 2: Without database URL (backwards compatibility)
    test2_passed = await test_without_database_url()
    
    print()
    print("=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    print(f"Test 1 (With Database URL): {'PASSED' if test1_passed else 'FAILED'}")
    print(f"Test 2 (Without Database URL): {'PASSED' if test2_passed else 'FAILED'}")
    print()
    
    if test1_passed and test2_passed:
        print("✓ All tests passed! Database connection fix is working correctly.")
        return 0
    else:
        print("✗ Some tests failed. Please review the output above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
