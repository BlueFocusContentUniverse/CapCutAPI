"""
WSGI entry point for production deployment
"""

# Import the Flask application
# Configure logging for production
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv

from capcut_server import app

load_dotenv()
# Add the project directory to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

if not app.debug:
    # Create logs directory if it doesn't exist
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Set up file handler
    file_handler = RotatingFileHandler(
        logs_dir / "capcut_api.log",
        maxBytes=10240000,  # 10MB
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)

    app.logger.setLevel(logging.INFO)
    app.logger.info("CapCut API startup")

# This is what Gunicorn will import
application = app

if __name__ == "__main__":
    # For development only
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 9000)), debug=False)
