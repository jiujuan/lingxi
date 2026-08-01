from server.app.core.log_redaction import redact_log_payload


def test_retrieval_snapshot_sanitization_retains_evidence_metadata_not_content():
    from server.app.core.log_redaction import sanitize_retrieval_snapshot

    snapshot = {
        "question": "private-customer-question",
        "queryEmbedding": [0.1, 0.2],
        "channels": ["qa_vector", "chunk_text"],
        "configHash": "chunk-config-1",
        "rrfParameters": {"k": 60, "weights": {"qa_vector": 1.0}},
        "stages": {
            "qaVector": [
                {
                    "qaPairId": "qa-1",
                    "documentId": "document-1",
                    "question": "private-qa-question",
                    "answer": "private-qa-answer",
                    "quote": "private-qa-quote",
                    "embedding": [0.3, 0.4],
                    "rank": 1,
                    "score": 0.9,
                },
                {
                    "qaPairId": "qa-2",
                    "documentId": "document-2",
                    "question": "private-qa-question-2",
                    "rank": 2,
                    "score": 0.8,
                },
            ],
            "rrf": [
                {
                    "evidenceId": "chunk-1",
                    "chunkId": "chunk-1",
                    "qaPairId": "qa-1",
                    "documentId": "document-1",
                    "fusedScore": 0.031,
                    "question": "private-fused-question",
                    "content": "private-fused-content",
                }
            ],
        },
    }

    sanitized = sanitize_retrieval_snapshot(snapshot, max_items_per_stage=1)

    assert sanitized["channels"] == ["qa_vector", "chunk_text"]
    assert sanitized["configHash"] == "chunk-config-1"
    assert sanitized["rrfParameters"] == {"k": 60, "weights": {"qa_vector": 1.0}}
    assert sanitized["stages"]["qaVector"] == [
        {
            "qaPairId": "qa-1",
            "documentId": "document-1",
            "rank": 1,
            "score": 0.9,
        }
    ]
    assert sanitized["stages"]["rrf"] == [
        {
            "evidenceId": "chunk-1",
            "chunkId": "chunk-1",
            "qaPairId": "qa-1",
            "documentId": "document-1",
            "fusedScore": 0.031,
        }
    ]
    assert "private-" not in str(sanitized)
    assert "Embedding" not in str(sanitized)


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

