import re
from unittest.mock import patch

import pytest

import graph_passkeys

USER_ID = "00000000-1111-2222-3333-444444444444"
BASE = f"https://graph.microsoft.com/beta/users/{USER_ID}/authentication/fido2Methods"


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


@pytest.fixture
def graph_request():
    """Patch the outgoing HTTP call and the app token, so no network is touched."""
    with (
        patch.object(graph_passkeys, "app_token", return_value="fake-app-token"),
        patch.object(graph_passkeys.requests, "request") as request,
    ):
        request.return_value = FakeResponse(json_body={})
        yield request


def test_app_token_returns_the_access_token_from_msal():
    with patch.object(graph_passkeys, "_msal_app") as msal_app:
        msal_app.return_value.acquire_token_for_client.return_value = {
            "access_token": "token-from-msal"
        }

        assert graph_passkeys.app_token() == "token-from-msal"


def test_app_token_raises_when_msal_returns_no_token():
    with patch.object(graph_passkeys, "_msal_app") as msal_app:
        msal_app.return_value.acquire_token_for_client.return_value = {
            "error": "unauthorized_client",
            "error_description": "no admin consent",
        }

        with pytest.raises(graph_passkeys.GraphError) as excinfo:
            graph_passkeys.app_token()

    assert "unauthorized_client" in str(excinfo.value)


def test_list_passkeys_gets_the_users_fido2_methods(graph_request):
    graph_request.return_value = FakeResponse(json_body={"value": [{"id": "abc"}]})

    result = graph_passkeys.list_passkeys(USER_ID)

    assert graph_request.call_args.args == ("GET", BASE)
    assert result == {"value": [{"id": "abc"}]}


def test_requests_carry_the_app_token_as_a_bearer_header(graph_request):
    graph_passkeys.list_passkeys(USER_ID)

    headers = graph_request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer fake-app-token"


def test_get_creation_options_unwraps_the_public_key(graph_request):
    graph_request.return_value = FakeResponse(json_body={"publicKey": {"challenge": "abc"}})

    result = graph_passkeys.get_creation_options(USER_ID)

    assert graph_request.call_args.args == (
        "GET",
        f"{BASE}/creationOptions(challengeTimeoutInMinutes=60)",
    )
    assert result == {"challenge": "abc"}


def test_create_passkey_posts_the_credential_to_fido2_methods(graph_request):
    payload = {
        "publicKeyCredential": {"id": "cred-id", "response": {}},
        "displayName": "my-key",
    }

    graph_passkeys.create_passkey(USER_ID, payload)

    assert graph_request.call_args.args == ("POST", BASE)
    assert graph_request.call_args.kwargs["json"] == payload


def test_create_passkey_generates_a_display_name_when_omitted(graph_request):
    payload = {"publicKeyCredential": {"id": "cred-id", "response": {}}}

    graph_passkeys.create_passkey(USER_ID, payload)

    sent = graph_request.call_args.kwargs["json"]
    assert re.fullmatch(r"passkey_\d+_[0-9a-z]{6}", sent["displayName"])


def test_create_passkey_keeps_a_blank_display_name_out_of_the_request(graph_request):
    payload = {"publicKeyCredential": {"id": "cred-id", "response": {}}, "displayName": "   "}

    graph_passkeys.create_passkey(USER_ID, payload)

    sent = graph_request.call_args.kwargs["json"]
    assert re.fullmatch(r"passkey_\d+_[0-9a-z]{6}", sent["displayName"])


def test_create_passkey_does_not_mutate_the_callers_payload(graph_request):
    payload = {"publicKeyCredential": {"id": "cred-id", "response": {}}}

    graph_passkeys.create_passkey(USER_ID, payload)

    assert "displayName" not in payload


def test_graph_error_carries_the_graph_status_code(graph_request):
    graph_request.return_value = FakeResponse(
        status_code=403,
        json_body={"error": {"code": "forbidden", "message": "Insufficient privileges"}},
    )

    with pytest.raises(graph_passkeys.GraphError) as excinfo:
        graph_passkeys.list_passkeys(USER_ID)

    assert excinfo.value.status_code == 403
    assert excinfo.value.message == "forbidden: Insufficient privileges"


def test_graph_error_unwraps_the_nested_odata_message(graph_request):
    graph_request.return_value = FakeResponse(
        status_code=400,
        json_body={
            "error": {
                "code": "badRequest",
                "message": '{"odata.error":{"message":{"value":"Attestation failed"}}}',
            }
        },
    )

    with pytest.raises(graph_passkeys.GraphError) as excinfo:
        graph_passkeys.list_passkeys(USER_ID)

    assert excinfo.value.message == "badRequest: Attestation failed"


def test_graph_error_falls_back_to_the_body_when_it_is_not_json(graph_request):
    graph_request.return_value = FakeResponse(status_code=502, text="Bad Gateway")

    with pytest.raises(graph_passkeys.GraphError) as excinfo:
        graph_passkeys.list_passkeys(USER_ID)

    assert excinfo.value.message == "HTTP 502: Bad Gateway"


def test_graph_error_falls_back_when_the_json_has_no_error_object(graph_request):
    graph_request.return_value = FakeResponse(
        status_code=500, json_body={"unexpected": "shape"}, text='{"unexpected": "shape"}'
    )

    with pytest.raises(graph_passkeys.GraphError) as excinfo:
        graph_passkeys.list_passkeys(USER_ID)

    assert excinfo.value.message == 'HTTP 500: {"unexpected": "shape"}'


def test_summarize_passkeys_keeps_only_the_fields_the_page_needs():
    graph_response = {
        "value": [
            {
                "id": "method-1",
                "displayName": "my-yubikey",
                "createdDateTime": "2026-07-30T01:23:45Z",
                "lastUsedDateTime": None,
                "model": "YubiKey 5",
                "aaGuid": "aa-guid",
                "attestationLevel": "notAttested",
                "passkeyType": "deviceBound",
                "publicKeyCredential": {"should": "not appear"},
                "@odata.type": "#microsoft.graph.fido2AuthenticationMethod",
            }
        ]
    }

    assert graph_passkeys.summarize_passkeys(graph_response) == [
        {
            "id": "method-1",
            "displayName": "my-yubikey",
            "createdDateTime": "2026-07-30T01:23:45Z",
            "lastUsedDateTime": None,
            "model": "YubiKey 5",
            "aaGuid": "aa-guid",
            "attestationLevel": "notAttested",
            "passkeyType": "deviceBound",
        }
    ]


def test_summarize_passkeys_returns_empty_for_a_response_without_value():
    assert graph_passkeys.summarize_passkeys({}) == []


def test_summarize_passkeys_fills_missing_fields_with_none():
    summary = graph_passkeys.summarize_passkeys({"value": [{"id": "method-1"}]})

    assert summary == [
        {
            "id": "method-1",
            "displayName": None,
            "createdDateTime": None,
            "lastUsedDateTime": None,
            "model": None,
            "aaGuid": None,
            "attestationLevel": None,
            "passkeyType": None,
        }
    ]


def test_generated_passkey_names_are_unique():
    names = {graph_passkeys.generate_passkey_name() for _ in range(50)}

    assert len(names) == 50


def test_delete_passkey_deletes_the_single_method(graph_request):
    graph_passkeys.delete_passkey(USER_ID, "method-id")

    assert graph_request.call_args.args == ("DELETE", f"{BASE}/method-id")
