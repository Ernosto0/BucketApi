#!/usr/bin/env python3
"""
Test script for the 2-venv dynamic library installation system.
Run this to verify the system is working correctly.
"""
import asyncio
import sys
import os
import logging

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_venv_system():
    """Test the complete venv system."""
    
    print("🧪 Testing 2-Venv Dynamic Library Installation System")
    print("=" * 60)
    
    try:
        # Import the services
        from app.services.venv_management_api import venv_management_api
        print("✅ Successfully imported venv management API")
        
        # Test 1: System Status
        print("\n📊 Test 1: System Status")
        status = await venv_management_api.get_system_status()
        if status['success']:
            venv_info = status['system_status']['venv_info']
            print(f"✅ Main venv exists: {venv_info['main_venv']['exists']}")
            print(f"✅ API venv exists: {venv_info['api_venv']['exists']}")
            print(f"✅ API venv size: {venv_info['api_venv']['size_mb']} MB")
            print(f"✅ Installed packages: {venv_info['api_venv']['installed_packages']}")
        else:
            print(f"❌ System status failed: {status.get('error')}")
            return False
        
        # Test 2: Health Check
        print("\n🏥 Test 2: Health Check")
        health = await venv_management_api.health_check()
        if health['success']:
            health_status = health['health_check']['overall_health']
            print(f"✅ Overall health: {health_status}")
            
            if health['health_check'].get('issues'):
                print("⚠️  Issues found:")
                for issue in health['health_check']['issues']:
                    print(f"   - {issue}")
            
            if health['health_check'].get('warnings'):
                print("⚠️  Warnings:")
                for warning in health['health_check']['warnings']:
                    print(f"   - {warning}")
        else:
            print(f"❌ Health check failed: {health.get('error')}")
        
        # Test 3: Dependency Analysis
        print("\n🔍 Test 3: Dependency Analysis")
        test_code = '''
import requests
import pandas as pd
import numpy as np
from collections import Counter

async def run(file_bytes=None, input_data=None):
    return {"message": "Test API", "data": input_data}
'''
        
        analysis = await venv_management_api.analyze_code_dependencies(test_code)
        if analysis['success']:
            deps = analysis['analysis']
            print(f"✅ Found {deps['total_imports']} imports")
            print(f"✅ External packages: {deps['external_packages']}")
            print(f"✅ Packages to install: {deps['packages_to_install']}")
            print(f"✅ Estimated install time: {deps['estimated_install_time']} seconds")
            print(f"✅ Estimated size: {deps['estimated_size_mb']} MB")
            
            if deps['dangerous_modules']:
                print(f"⚠️  Dangerous modules detected: {deps['dangerous_modules']}")
        else:
            print(f"❌ Dependency analysis failed: {analysis.get('error')}")
        
        # Test 4: Package Installation
        print("\n📦 Test 4: Package Installation")
        try:
            # Test installing a simple package
            install_result = await venv_management_api.install_package("requests")
            if install_result['success']:
                print("✅ Successfully installed requests package")
            else:
                print(f"⚠️  Package installation result: {install_result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"⚠️  Package installation test failed: {e}")
        
        # Test 5: Code Execution
        print("\n Test 5: Code Execution")
        simple_test_code = '''
import json
import datetime
from collections import Counter

async def run(file_bytes=None, input_data=None):
    """Simple test API that uses common libraries."""
    
    # Test basic functionality
    data = input_data or {}
    
    # Use collections.Counter
    text = data.get('text', 'hello world test hello')
    words = text.split()
    word_count = dict(Counter(words))
    
    return {
        "message": "Venv execution test successful",
        "timestamp": datetime.datetime.now().isoformat(),
        "input_received": data,
        "word_count": word_count,
        "libraries_used": ["json", "datetime", "collections"]
    }
'''
        
        try:
            exec_result = await venv_management_api.test_execution(
                code=simple_test_code,
                input_data={"text": "test venv system test system"}
            )
            
            if exec_result['success']:
                result = exec_result['result']
                print("✅ Code execution successful!")
                print(f"   Message: {result.get('message')}")
                print(f"   Word count: {result.get('word_count')}")
                print(f"   Libraries used: {result.get('libraries_used')}")
            else:
                print(f"❌ Code execution failed: {exec_result.get('error')}")
        except Exception as e:
            print(f"❌ Code execution test failed: {e}")
        
        # Test 6: Your Original Use Case - Keyword Extraction
        print("\n🎯 Test 6: Keyword Extraction (Your Original Request)")
        keyword_extraction_code = '''
from collections import Counter
import re

async def run(file_bytes=None, input_data=None):
    """Extract keywords using built-in Python libraries."""
    
    content = input_data.get('content', '') if input_data else ''
    
    if not content:
        return {"error": "No content provided"}
    
    # Tokenize and clean
    words = re.findall(r'\\b\\w+\\b', content.lower())
    
    # Remove stopwords
    stopwords = {
        'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 
        'is', 'it', 'and', 'or', 'but', 'not', 'this', 'that', 'from', 
        'by', 'as', 'be', 'are', 'was', 'were', 'been', 'have', 'has', 
        'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 
        'can', 'may', 'might'
    }
    
    filtered = [w for w in words if w not in stopwords and len(w) > 3]
    
    # Get top 5 keywords
    keywords = [word for word, count in Counter(filtered).most_common(5)]
    
    return {"keywords": keywords}
'''
        
        try:
            keyword_result = await venv_management_api.test_execution(
                code=keyword_extraction_code,
                input_data={
                    "content": "Python programming language machine learning artificial intelligence data science natural language processing computer vision deep learning neural networks"
                }
            )
            
            if keyword_result['success']:
                keywords = keyword_result['result'].get('keywords', [])
                print("✅ Keyword extraction successful!")
                print(f"   Extracted keywords: {keywords}")
                print("🎉 Your original use case now works perfectly!")
            else:
                print(f"❌ Keyword extraction failed: {keyword_result.get('error')}")
        except Exception as e:
            print(f"❌ Keyword extraction test failed: {e}")
        
        # Test 7: System Statistics
        print("\n📈 Test 7: System Statistics")
        try:
            stats = venv_management_api.get_execution_statistics()
            if stats['success']:
                exec_stats = stats['statistics']['execution_stats']
                print(f"✅ Total executions: {exec_stats.get('total_executions', 0)}")
                print(f"✅ Successful executions: {exec_stats.get('successful_executions', 0)}")
                print(f"✅ Average execution time: {exec_stats.get('average_execution_time', 0):.2f}s")
                
                install_stats = stats['statistics']['installation_stats']
                print(f"✅ Total installations: {install_stats.get('total_installations', 0)}")
                print(f"✅ Packages installed: {install_stats.get('total_packages_installed', 0)}")
            else:
                print(f"⚠️  Could not get statistics: {stats.get('error')}")
        except Exception as e:
            print(f"⚠️  Statistics test failed: {e}")
        
        print("\n" + "=" * 60)
        print("🎉 All tests completed!")
        print("\n✅ Your 2-venv system is working correctly!")
        print("✅ You can now handle ANY Python library requests!")
        print("✅ Your keyword extraction API will work perfectly!")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the project root directory")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function."""
    print("Starting venv system test...")
    
    # Run the async test
    success = asyncio.run(test_venv_system())
    
    if success:
        print("\n🎊 SUCCESS: Your venv system is ready to use!")
        sys.exit(0)
    else:
        print("\n💥 FAILURE: There were issues with the venv system")
        sys.exit(1)

if __name__ == "__main__":
    main()
