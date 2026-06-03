"""Contract evidence for S2-002 bronze raw-payload lineage storage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from pydantic import ValidationError

from ta_model.contracts.market_data import (
    ApprovedUseStatus,
    HistoricalProvenance,
    LicenseReviewStatus,
    SourceApproval,
)
from ta_model.storage.bronze import (
    BronzePayloadAlreadyExistsError,
    BronzePayloadMetadata,
    FilesystemBronzePayloadStore,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SOURCE_ID = "FIXTURE_BRONZE_SOURCE"
VENUE_ID = "FIXTURE_SPOT"


def _approved_source(source_id: str = SOURCE_ID) -> SourceApproval:
    return SourceApproval(
        source_id=source_id,
        license_review_status=LicenseReviewStatus.APPROVED,
        approved_use_status=ApprovedUseStatus.BACKTEST_APPROVED,
        reviewed_at=NOW,
        evidence_uri="fixture://source-license-review/S2-002",
        source_register_version="S0-004-fixture-register-v1",
        retention_allowed=True,
        storage_allowed=True,
        raw_payload_storage_allowed=True,
        event_time_fields_documented=True,
        rate_limit_policy_ref="fixture://source-license-review/S2-002/rate-limits",
    )


def _metadata(source_id: str = SOURCE_ID) -> BronzePayloadMetadata:
    return BronzePayloadMetadata(
        source_id=source_id,
        venue_id=VENUE_ID,
        content_type="application/json",
        fetched_at=NOW,
        source_approval=_approved_source(source_id),
    )


def test_write_read_round_trip_checksum_and_historical_provenance(tmp_path: Path) -> None:
    store = FilesystemBronzePayloadStore(tmp_path)
    payload = b'{"fixture":"bronze","page":1}'

    reference = store.persist(payload, _metadata())

    assert store.read(reference) == payload
    verification = store.verify(reference)
    assert verification.verified is True
    assert verification.actual_hash == reference.content_hash
    assert reference.source_id == SOURCE_ID
    assert reference.uri.startswith("file://")
    decoded_uri = unquote(reference.uri)
    assert f"source={SOURCE_ID}" in decoded_uri
    assert f"venue={VENUE_ID}" in decoded_uri

    provenance = HistoricalProvenance(
        source_id=SOURCE_ID,
        connector_name="fixture-historical-connector",
        connector_version="0.0.0-test",
        fetched_at=NOW,
        raw_payload=reference,
    )
    assert provenance.raw_payload.raw_payload_id == reference.raw_payload_id


def test_same_payload_is_idempotent(tmp_path: Path) -> None:
    store = FilesystemBronzePayloadStore(tmp_path)
    payload = b'{"fixture":"bronze","page":1}'

    first = store.persist(payload, _metadata())
    second = store.persist(payload, _metadata())

    assert second == first


def test_mismatched_existing_payload_fails_closed(tmp_path: Path) -> None:
    store = FilesystemBronzePayloadStore(tmp_path)
    payload = b'{"fixture":"bronze","page":1}'
    reference = store.persist(payload, _metadata())
    object_path = Path(unquote(urlparse(reference.uri).path))
    object_path.write_bytes(b'{"fixture":"tampered"}')

    with pytest.raises(BronzePayloadAlreadyExistsError, match="bytes do not match"):
        store.persist(payload, _metadata())

    verification = store.verify(reference)
    assert verification.verified is False


def test_provenance_source_id_is_preserved_per_source(tmp_path: Path) -> None:
    store = FilesystemBronzePayloadStore(tmp_path)
    source_id = "FIXTURE_BRONZE_SOURCE_ALT"

    reference = store.persist(b'{"fixture":"bronze","page":2}', _metadata(source_id))

    assert reference.source_id == source_id
    assert f"source={source_id}" in unquote(reference.uri)


def test_unknown_and_invalid_metadata_fails_closed() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BronzePayloadMetadata.model_validate(
            {
                "source_id": SOURCE_ID,
                "venue_id": VENUE_ID,
                "content_type": "application/json",
                "fetched_at": NOW,
                "source_approval": _approved_source(),
                "unexpected": "field",
            }
        )

    blocked = SourceApproval(
        source_id=SOURCE_ID,
        license_review_status=LicenseReviewStatus.NOT_STARTED,
        approved_use_status=ApprovedUseStatus.BLOCKED_PENDING_REVIEW,
        reviewed_at=None,
        evidence_uri=None,
        source_register_version=None,
        retention_allowed=None,
        storage_allowed=None,
        raw_payload_storage_allowed=None,
        event_time_fields_documented=None,
        rate_limit_policy_ref=None,
    )
    with pytest.raises(ValidationError, match="not approved for bronze"):
        BronzePayloadMetadata(
            source_id=SOURCE_ID,
            venue_id=VENUE_ID,
            content_type="application/json",
            fetched_at=NOW,
            source_approval=blocked,
        )


def test_empty_payload_fails_closed(tmp_path: Path) -> None:
    store = FilesystemBronzePayloadStore(tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        store.persist(b"", _metadata())
