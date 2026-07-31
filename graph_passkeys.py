"""Microsoft Graph (beta) の FIDO2 プロビジョニング API を叩く薄いクライアント。

Flask に依存しないので、requests をモックすればブラウザなしでテストできる。
https://learn.microsoft.com/en-us/graph/api/resources/fido2authenticationmethod?view=graph-rest-beta
"""

import contextlib
import json
import os
import secrets
import string
import time
from functools import cache

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/beta"
_GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
_TIMEOUT = 30
_NAME_ALPHABET = string.ascii_lowercase + string.digits
_SUMMARY_FIELDS = (
    "id",
    "displayName",
    "createdDateTime",
    # lastUsedDateTime は Graph beta の既知の制限により、パスキーでサインインしても
    # 更新されないことがある(Entra External ID/CIAM に限らず一般の Entra ID テナントでも報告あり)。
    # 実際のサインイン履歴を確認したい場合は Entra ID のサインインログを参照すること。
    # https://www.michev.info/blog/post/7039/last-used-data-for-authentication-methods-is-now-available-on-the-graph
    "lastUsedDateTime",
    "model",
    "aaGuid",
    "attestationLevel",
    "passkeyType",
)


class GraphError(Exception):
    """Graph が返したエラー。status_code はそのまま呼び出し元に返せる。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@cache
def _msal_app() -> msal.ConfidentialClientApplication:
    # client credentials フローは ciamlogin.com の authority では使えないため、
    # アプリトークンだけは login.microsoftonline.com/<tenant-id> から取得する。
    return msal.ConfidentialClientApplication(
        os.environ["CLIENT_ID"],
        client_credential=os.environ["CLIENT_SECRET"],
        authority=f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}",
    )


def app_token() -> str:
    """アプリ専用トークンを返す。キャッシュは MSAL が内部で持つ。"""
    result = _msal_app().acquire_token_for_client(_GRAPH_SCOPE)
    if "access_token" not in result:
        raise GraphError(
            500,
            f"{result.get('error', 'unknown_error')}: "
            f"{result.get('error_description', 'アプリトークンを取得できませんでした')}",
        )
    return result["access_token"]


def _methods_url(user_id: str) -> str:
    return f"{GRAPH_BASE}/users/{user_id}/authentication/fido2Methods"


def _call(method: str, url: str, json: dict | None = None) -> dict:
    response = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {app_token()}",
            "Content-Type": "application/json",
        },
        json=json,
        timeout=_TIMEOUT,
    )
    if not response.ok:
        raise GraphError(response.status_code, _error_message(response))
    try:
        return response.json()
    except ValueError:
        return {}


def _error_message(response) -> str:
    """Graph のエラー本文を 1 行に正規化する。"""
    try:
        error = response.json()["error"]
        code = error["code"]
        message = error.get("message", "")
    except ValueError, KeyError, TypeError:
        return f"HTTP {response.status_code}: {response.text}"
    # Graph は message の中に odata エラーを JSON 文字列で入れてくることがある。
    with contextlib.suppress(ValueError, KeyError, TypeError):
        message = json.loads(message)["odata.error"]["message"]["value"]
    return f"{code}: {message}"


def list_passkeys(user_id: str) -> dict:
    return _call("GET", _methods_url(user_id))


def summarize_passkeys(graph_response: dict) -> list[dict]:
    """一覧表示に必要な項目だけを抜き出す。日付の整形はブラウザ側で行う。"""
    return [
        {field: method.get(field) for field in _SUMMARY_FIELDS}
        for method in graph_response.get("value", [])
    ]


def get_creation_options(user_id: str) -> dict:
    body = _call(
        "GET",
        f"{_methods_url(user_id)}/creationOptions(challengeTimeoutInMinutes=60)",
    )
    return body.get("publicKey", {})


def generate_passkey_name() -> str:
    """displayName が指定されなかったときの名前。サンプルの命名に合わせている。"""
    suffix = "".join(secrets.choice(_NAME_ALPHABET) for _ in range(6))
    return f"passkey_{int(time.time())}_{suffix}"


def create_passkey(user_id: str, payload: dict) -> dict:
    body = dict(payload)
    if not body.get("displayName", "").strip():
        body["displayName"] = generate_passkey_name()
    return _call("POST", _methods_url(user_id), json=body)


def delete_passkey(user_id: str, passkey_id: str) -> None:
    _call("DELETE", f"{_methods_url(user_id)}/{passkey_id}")
