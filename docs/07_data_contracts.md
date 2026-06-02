# Data Contracts, Quality Gates, and Lineage Plan

## 1. Canonical identifiers

| Entity | Key | Required fields |
|---|---|---|
| Asset | `asset_id` | symbol, name, asset_type, fiat/stable/crypto/equity flag, issuer/category if known. |
| Instrument | `instrument_id` | base_asset_id, quote_asset_id, venue_id, symbol, status, tick_size, lot_size, min_notional, effective_from/to. |
| Venue | `venue_id` | venue_type, timezone, API endpoint group, status, rate limits, supported order types. |
| Account | `account_id` | venue_id, trading permissions, fee tier, risk limits, key scope. |

## 2. OHLCTV bar schema

| Field | Type | Required | Notes |
|---|---|---:|---|
| `instrument_id` | string | Yes | Canonical instrument. |
| `venue_id` | string | Yes | Source venue. |
| `timeframe` | string | Yes | e.g., `1m`, `5m`, `1h`, `1d`. |
| `open_ts` | timestamp | Yes | Bar start in UTC. |
| `close_ts` | timestamp | Yes | Bar close in UTC. |
| `open` | decimal | Yes | Non-negative. |
| `high` | decimal | Yes | Must be >= open, low, close. |
| `low` | decimal | Yes | Must be <= open, high, close. |
| `close` | decimal | Yes | Non-negative. |
| `base_volume` | decimal | Yes | >= 0. |
| `quote_volume` | decimal | Optional | >= 0 if provided. |
| `trade_count` | integer | Optional | OHLCTV uses T as trade count. |
| `vwap` | decimal | Optional | Must be between low/high when provided. |
| `source_ts` | timestamp | Yes | Source-published timestamp if available. |
| `ingest_ts` | timestamp | Yes | System ingestion timestamp. |
| `quality_flags` | array | Yes | Missing, late, estimated, duplicate, outlier, repaired. |
| `raw_payload_id` | string | Yes | Link to immutable raw payload. |

## 3. Trade schema

| Field | Type | Required | Notes |
|---|---|---:|---|
| `trade_id` | string | Yes | Source trade ID or deterministic hash. |
| `instrument_id` | string | Yes | Canonical instrument. |
| `event_ts` | timestamp | Yes | Trade event time. |
| `price` | decimal | Yes | > 0. |
| `quantity` | decimal | Yes | > 0. |
| `side` | enum | Optional | buyer/seller aggressor if available. |
| `sequence` | integer | Optional | Source sequence. |
| `source_ts` | timestamp | Optional | Source timestamp. |
| `ingest_ts` | timestamp | Yes | Ingestion timestamp. |
| `raw_payload_id` | string | Yes | Lineage. |

## 4. Quote/order-book schema

| Field | Type | Required | Notes |
|---|---|---:|---|
| `book_event_id` | string | Yes | Deterministic ID. |
| `instrument_id` | string | Yes | Canonical instrument. |
| `event_ts` | timestamp | Yes | Source event time. |
| `sequence` | integer | Required when source provides it | Used for gap detection. |
| `is_snapshot` | boolean | Yes | Snapshot vs delta. |
| `bids` / `asks` | array | Yes | Price/size levels. |
| `best_bid`, `best_ask` | decimal | Required for quote record | Crossed/locked checks. |
| `quality_flags` | array | Yes | Gap, stale, crossed, repaired. |
| `raw_payload_id` | string | Yes | Lineage. |

## 5. Feature schema

| Field | Type | Required | Notes |
|---|---|---:|---|
| `feature_vector_id` | string | Yes | Hash of keys/version/timestamp. |
| `instrument_id` | string | Yes | Canonical instrument. |
| `feature_ts` | timestamp | Yes | Time at which all values are available. |
| `feature_version` | string | Yes | Semantic version. |
| `lookback_window` | string | Yes | Max lookback used. |
| `values` | map | Yes | Feature name → value. |
| `input_snapshot_id` | string | Yes | Lineage to clean data. |
| `quality_flags` | array | Yes | Missing, imputed, outlier, stale. |

## 6. Quality gates

| Gate | Priority | Default action |
|---|---:|---|
| Schema validation failure | P0 | Reject record to quarantine; alert if stream. |
| Timestamp outside tolerance | P0 | Flag; block live trading if required feed. |
| Sequence gap | P0 | Request repair; block book-dependent strategies until fixed. |
| Missing bars above threshold | P0 | Fail dataset build. |
| Duplicate rate above threshold | P0 | Fail ingestion job or quarantine source. |
| OHLC invariant violation | P0 | Quarantine record. |
| Crossed/locked book beyond tolerance | P0 | Flag and block affected book features. |
| Corporate action missing for equities | P0 | Block adjusted backtest for affected instrument. |
| Fee schedule missing | P0 | Use conservative default only if approved; otherwise block strategy. |

## 7. Lineage and retention

Every feature, label, prediction, decision, and order must link to source data, feature code version, model version, strategy version, and runtime config. Raw data is immutable. Corrected data creates a new version with correction reason. Retention periods must be configured by data license, venue, jurisdiction, and audit need.
