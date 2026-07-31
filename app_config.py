import os

AUTHORITY = os.getenv("AUTHORITY")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
# アプリ専用トークン (client credentials) は ciamlogin.com の authority では取得できないため、
# login.microsoftonline.com/<TENANT_ID> を使う。graph_passkeys.py が参照する。
TENANT_ID = os.getenv("TENANT_ID")
# Tells the Flask-session extension to store sessions in the filesystem.
# Don't use in production apps.
SESSION_TYPE = "filesystem"
