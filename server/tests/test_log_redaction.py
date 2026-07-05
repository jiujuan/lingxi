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

