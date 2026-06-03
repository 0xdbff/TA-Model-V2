"""Bronze raw-payload persistence semantics.

Traceability:
- FR-001: raw historical payloads are stored with lineage for later silver records.
- NFR-005: deterministic hashes, object paths, and checksum verification support replay.

Scope:
- S2-002 defines the store interface plus a local filesystem fixture/dev adapter.
- Production MinIO/S3 wiring, real exchange/API pulls, silver normalization, gap reports,
  streaming health, features, datasets, Docker Compose, and live/paper execution are deferred.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol, Self
from urllib.parse import unquote, urlparse

from pydantic import AwareDatetime, PositiveInt, model_validator

from ta_model.contracts.instrument_master import CanonicalId, ContractModel, NonEmptyString
from ta_model.contracts.market_data import HashHex, RawPayloadReference, SourceApproval, SourceId


class BronzePayloadAlreadyExistsError(RuntimeError):
    """Raised when an existing immutable bronze object does not match its hash."""


class BronzePayloadMetadata(ContractModel):
    """Source/register provenance required before raw payload bytes can be retained."""

    source_id: SourceId
    venue_id: CanonicalId
    content_type: NonEmptyString
    fetched_at: AwareDatetime
    source_approval: SourceApproval

    @model_validator(mode="after")
    def source_must_be_storage_approved(self) -> Self:
        if self.source_approval.source_id != self.source_id:
            raise ValueError("source_approval.source_id must match metadata source_id")
        if not self.source_approval.is_historical_ingestion_approved():
            raise ValueError("source is not approved for bronze raw-payload storage")
        return self


class BronzePayloadVerification(ContractModel):
    """Checksum verification result for a stored raw payload reference."""

    raw_payload: RawPayloadReference
    verified: bool
    actual_hash: HashHex
    byte_count: PositiveInt

    @model_validator(mode="after")
    def verification_must_match_reference(self) -> Self:
        if self.verified:
            if self.actual_hash != self.raw_payload.content_hash:
                raise ValueError("verified payload hash must match reference content_hash")
            if self.byte_count != self.raw_payload.byte_count:
                raise ValueError("verified byte_count must match reference byte_count")
        return self


class BronzePayloadStore(Protocol):
    """Interface for immutable bronze raw-payload storage adapters."""

    def persist(self, payload: bytes, metadata: BronzePayloadMetadata) -> RawPayloadReference:
        """Persist bytes immutably and return their canonical raw-payload reference."""

    def read(self, reference: RawPayloadReference) -> bytes:
        """Read stored bytes for a reference, verifying the checksum before returning."""

    def verify(self, reference: RawPayloadReference) -> BronzePayloadVerification:
        """Verify the referenced object's current checksum and byte count."""


class FilesystemBronzePayloadStore:
    """Local fixture/dev store with MinIO-like deterministic bronze object semantics."""

    _SIDECAR_SUFFIX = ".metadata.json"

    def __init__(self, root: Path) -> None:
        self._root = root

    def persist(self, payload: bytes, metadata: BronzePayloadMetadata) -> RawPayloadReference:
        if not payload:
            raise ValueError("bronze raw payload must not be empty")

        content_hash = self._hash_bytes(payload)
        object_path = self._object_path(metadata, content_hash)
        reference = RawPayloadReference(
            raw_payload_id=self.build_raw_payload_id(content_hash),
            source_id=metadata.source_id,
            content_hash=content_hash,
            uri=object_path.resolve().as_uri(),
            content_type=metadata.content_type,
            fetched_at=metadata.fetched_at,
            byte_count=len(payload),
        )

        object_path.parent.mkdir(parents=True, exist_ok=True)
        if object_path.exists():
            existing = object_path.read_bytes()
            if existing != payload:
                raise BronzePayloadAlreadyExistsError(
                    "existing bronze object bytes do not match deterministic content hash"
                )
            existing_reference = self._read_sidecar(object_path)
            if existing_reference != reference:
                raise BronzePayloadAlreadyExistsError(
                    "existing bronze object metadata does not match requested reference"
                )
            return reference

        object_path.write_bytes(payload)
        self._write_sidecar(object_path, reference)
        return reference

    def read(self, reference: RawPayloadReference) -> bytes:
        object_path = self._path_from_reference(reference)
        payload = object_path.read_bytes()
        verification = self.verify(reference)
        if not verification.verified:
            raise BronzePayloadAlreadyExistsError("bronze payload checksum verification failed")
        return payload

    def verify(self, reference: RawPayloadReference) -> BronzePayloadVerification:
        object_path = self._path_from_reference(reference)
        payload = object_path.read_bytes()
        actual_hash = self._hash_bytes(payload)
        byte_count = len(payload)
        if byte_count <= 0:
            raise ValueError("stored bronze payload must not be empty")
        return BronzePayloadVerification(
            raw_payload=reference,
            verified=actual_hash == reference.content_hash and byte_count == reference.byte_count,
            actual_hash=actual_hash,
            byte_count=byte_count,
        )

    @classmethod
    def build_raw_payload_id(cls, content_hash: str) -> str:
        """Build a deterministic canonical raw payload ID from a SHA-256 hash."""

        return f"RAW:{content_hash.upper()}"

    def _object_path(self, metadata: BronzePayloadMetadata, content_hash: str) -> Path:
        date = metadata.fetched_at.date().isoformat()
        suffix = "json" if metadata.content_type == "application/json" else "bin"
        return (
            self._root
            / f"source={metadata.source_id}"
            / f"venue={metadata.venue_id}"
            / f"date={date}"
            / f"{content_hash}.{suffix}"
        )

    def _path_from_reference(self, reference: RawPayloadReference) -> Path:
        parsed = urlparse(reference.uri)
        if parsed.scheme != "file":
            raise ValueError("filesystem bronze store only accepts file:// references")
        path = Path(unquote(parsed.path))
        root = self._root.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("raw payload reference is outside this bronze store root")
        return resolved

    def _write_sidecar(self, object_path: Path, reference: RawPayloadReference) -> None:
        sidecar = object_path.with_suffix(object_path.suffix + self._SIDECAR_SUFFIX)
        sidecar.write_text(
            json.dumps(reference.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def _read_sidecar(self, object_path: Path) -> RawPayloadReference:
        sidecar = object_path.with_suffix(object_path.suffix + self._SIDECAR_SUFFIX)
        return RawPayloadReference.model_validate_json(sidecar.read_text(encoding="utf-8"))

    @staticmethod
    def _hash_bytes(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()
