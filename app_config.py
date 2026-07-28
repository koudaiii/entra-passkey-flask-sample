import os

AUTHORITY = os.getenv("AUTHORITY")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
SESSION_TYPE = "filesystem" # Tells the Flask-session extension to store sessions in the filesystem. Don't use in production apps.

