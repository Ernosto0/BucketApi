#!/usr/bin/env python3
"""
AI-Powered API Generator
Main entry point for the application
"""

from app.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)