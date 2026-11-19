"""Customer requirements - the structured input to the layout engine."""
from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Requirements(BaseModel):
    building_width: float = Field(40, ge=24, le=80, description="Building width / depth in feet (the gable span)")
    building_length: float = Field(60, ge=30, le=200, description="Building length in feet")
    bedrooms: int = Field(3, ge=1, le=6, description="Total bedrooms including the primary")
    full_baths: int = Field(2, ge=1, le=5, description="Full baths including the primary bath")
    half_baths: int = Field(0, ge=0, le=2)
    office: bool = False
    laundry: bool = True          # laundry and mudroom are always one combined room (company rule 6)
    pantry: bool = False
    mudroom: bool = False
    walk_in_closet: bool = True
    shop_length: float = Field(0, ge=0, le=150, description="Length of building used as shop (full width). 0 = no shop")
    shop_side: Literal["left", "right"] = "right"
    overhead_doors: int = Field(1, ge=0, le=4)
    main_entrance: Literal["single", "double"] = "single"
    eave_height: float = Field(12, ge=8, le=24, description="Eave height in feet (company standard 12)")
    roof_pitch: float = Field(4, ge=1, le=12, description="Roof slope, rise per 12 (company standard 4:12)")
    front_porch_depth: float = Field(0, ge=0, le=16)
    back_porch_depth: float = Field(0, ge=0, le=16)
    budget: Optional[float] = Field(None, ge=0)
    notes: str = ""
    customer_name: str = ""

    @field_validator("shop_length")
    @classmethod
    def _round_shop(cls, v: float) -> float:
        return round(v * 2) / 2

    @property
    def living_length(self) -> float:
        return self.building_length - self.shop_length

    def fingerprint(self) -> str:
        data = self.model_dump(exclude={"notes", "customer_name", "budget"})
        return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:10]
