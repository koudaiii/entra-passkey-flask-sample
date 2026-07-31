"""Auth インスタンス。

Blueprint 側から `from auth import auth` で参照するため、app とは別モジュールに置く
(ms-identity-python の Application Factory パターン)。
"""

from identity.flask import Auth

import app_config

auth = Auth(
    None,  # init_app(app) は app.py で呼ぶ
    authority=app_config.AUTHORITY,
    client_id=app_config.CLIENT_ID,
    client_credential=app_config.CLIENT_SECRET,
    redirect_uri=app_config.REDIRECT_URI,
)
