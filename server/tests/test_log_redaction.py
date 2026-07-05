from server.app.core.log_redaction import redact_log_payload


def test_log_redaction_masks_nested_secrets_and_authorization_headers():
    payload = {
        "apiKey": "lk_live_plaintext",
        "headers": {"Authorization": "Bearer secret-token", "x-request-id": "req-1"},
        "provider": {"encrypted_api_key": "ciphertext", "name": "demo"},
        "items": [{"secret": "sk-model"}, {"keyPrefix": "lk_live_abcd"}],
    }

    redacted = redact_log_payload(payload)

    assert redacted["apiKey"] == "***REDACTED***"
    assert redacted["headers"]["Authorization"] == "***REDACTED***"
    assert redacted["headers"]["x-request-id"] == "req-1"
    assert redacted["provider"]["encrypted_api_key"] == "***REDACTED***"
    assert redacted["provider"]["name"] == "demo"
    assert redacted["items"][0]["secret"] == "***REDACTED***"
    assert redacted["items"][1]["keyPrefix"] == "lk_live_abcd"


def test_value_level_redaction_masks_secrets_under_innocuous_keys():
    payload = {
        "message": "使用 lk_live_abcdef0123456789 访问",  # api key inside free text
        "note": "token eyJhbGciOi.aaaaaaaa.bbbbbbbb 已下发",  # JWT
        "requestId": "req_1234567890abcdef",  # must NOT be redacted
        "keyPrefix": "lk_live_abcdefgh",  # safe key -> not redacted
    }

    redacted = redact_log_payload(payload)

    assert "lk_live_abcdef0123456789" not in redacted["message"]
    assert "***REDACTED***" in redacted["message"]
    assert "eyJhbGciOi" not in redacted["note"]
    assert redacted["requestId"] == "req_1234567890abcdef"
    assert redacted["keyPrefix"] == "lk_live_abcdefgh"


