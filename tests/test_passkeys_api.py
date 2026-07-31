"""パスキー API の結線をテストする。

Graph 呼び出しだけをモックし、Flask のルーティングと login_required は本物を通す。
"""

from unittest.mock import patch

import pytest

import graph_passkeys

USER_ID = "00000000-1111-2222-3333-444444444444"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("TENANT_ID", "fake-tenant-id")
    monkeypatch.setenv("AUTHORITY", "https://example.ciamlogin.com/fake-tenant-id")
    monkeypatch.setenv("REDIRECT_URI", "https://auth.example.ciamlogin.com:3000/getAToken")

    import app as app_module

    app_module.app.config.update(TESTING=True)
    # login_required は _auth.get_user() の戻り値でサインイン済みかを判断する。
    with patch.object(
        app_module.auth._auth,
        "get_user",
        return_value={"oid": USER_ID, "name": "Test User"},
    ):
        yield app_module.app.test_client()


def test_list_returns_the_summarized_passkeys(client):
    graph_response = {"value": [{"id": "method-1", "displayName": "my-key"}]}
    with patch.object(graph_passkeys, "list_passkeys", return_value=graph_response) as called:
        response = client.get("/api/passkeys")

    assert response.status_code == 200
    assert response.get_json()["passkeys"][0]["displayName"] == "my-key"
    assert called.call_args.args == (USER_ID,)


def test_creation_options_are_passed_through(client):
    with patch.object(graph_passkeys, "get_creation_options", return_value={"challenge": "abc"}):
        response = client.get("/api/passkeys/creation-options")

    assert response.status_code == 200
    assert response.get_json() == {"challenge": "abc"}


def test_create_forwards_the_credential_and_returns_201(client):
    payload = {"publicKeyCredential": {"id": "cred-id", "response": {}}}
    with patch.object(graph_passkeys, "create_passkey", return_value={"id": "method-1"}) as called:
        response = client.post("/api/passkeys", json=payload)

    assert response.status_code == 201
    assert called.call_args.args == (USER_ID, payload)


def test_create_rejects_a_body_without_a_credential(client):
    response = client.post("/api/passkeys", json={"displayName": "only-a-name"})

    assert response.status_code == 400
    assert "publicKeyCredential" in response.get_json()["error"]


def test_delete_returns_204(client):
    with patch.object(graph_passkeys, "delete_passkey") as called:
        response = client.delete("/api/passkeys/method-1")

    assert response.status_code == 204
    assert called.call_args.args == (USER_ID, "method-1")


def test_graph_errors_become_json_with_the_graph_status_code(client):
    error = graph_passkeys.GraphError(403, "forbidden: Insufficient privileges")
    with patch.object(graph_passkeys, "list_passkeys", side_effect=error):
        response = client.get("/api/passkeys")

    assert response.status_code == 403
    assert response.get_json() == {"error": "forbidden: Insufficient privileges"}


def test_the_user_id_comes_from_the_token_not_the_request(client):
    """クエリでユーザーを差し替えられないこと。"""
    with patch.object(graph_passkeys, "list_passkeys", return_value={"value": []}) as called:
        client.get("/api/passkeys?user_id=someone-else")

    assert called.call_args.args == (USER_ID,)
