"""Validated admin filters and filter-bound cursors (FR-040)."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from asset_store_core.errors import ValidationError
from asset_store_core.models import Asset, AssetState
from asset_store_core.paths import normalize_partition_id, normalize_relative_alias, normalize_space


class AssetQuery(BaseModel):
    space: str | None = None
    partition_id: str | None = None
    state: AssetState | None = None
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None
    prefix: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def validate_filters(self) -> AssetQuery:
        if self.space:
            self.space = normalize_space(self.space)
        if self.partition_id:
            if not self.space:
                raise ValueError("partition_id requires space")
            self.partition_id = normalize_partition_id(self.partition_id)
        if self.prefix:
            self.prefix = normalize_relative_alias(self.prefix)
            normalize_space(self.prefix.split("/")[0])
        if self.created_from and self.created_to and self.created_from > self.created_to:
            raise ValueError("created_from must not exceed created_to")
        return self

    def fingerprint(self) -> str:
        data = self.model_dump(mode="json", exclude={"cursor", "limit"})
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def after(self) -> tuple[datetime, str] | None:
        if not self.cursor:
            return None
        try:
            data = json.loads(base64.b64decode(self.cursor, altchars=b"-_", validate=True))
            when = datetime.fromisoformat(data[1])
            if data[0] != self.fingerprint() or when.tzinfo is None or not isinstance(data[2], str):
                raise ValueError
            return when, data[2]
        except (ValueError, TypeError, IndexError, KeyError) as exc:
            raise ValidationError("invalid cursor or changed filters") from exc

    def cursor_for(self, asset: Asset) -> str:
        data = [self.fingerprint(), asset.created_at.isoformat(), asset.asset_id]
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

    def matches(self, asset: Asset) -> bool:
        return (
            (self.space is None or asset.space == self.space)
            and (self.partition_id is None or asset.partition_id == self.partition_id)
            and (self.state is None or asset.state == self.state)
            and (self.created_from is None or asset.created_at >= self.created_from)
            and (self.created_to is None or asset.created_at <= self.created_to)
            and (self.prefix is None or any(prefix_matches(a, self.prefix) for a in asset.aliases))
        )


def prefix_matches(alias: str, prefix: str) -> bool:
    return alias == prefix or alias.startswith(prefix + "/")
