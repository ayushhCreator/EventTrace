from __future__ import annotations

from pydantic import BaseModel, Field

from ..services.validators import validate_yyyy_mm_dd

try:  # Pydantic v2
    from pydantic import field_validator, model_validator
    _PYDANTIC_V2 = True
except ImportError:  # pragma: no cover (Pydantic v1 fallback)
    from pydantic import root_validator as _root_validator
    from pydantic import validator as field_validator
    _PYDANTIC_V2 = False


class AlertRequest(BaseModel):
    room_no: str
    target_serial: int = Field(..., ge=1, le=9999)
    look_ahead: int = Field(5, ge=0, le=50)
    hearing_date: str | None = None  # YYYY-MM-DD IST; defaults to today
    display_name: str | None = None
    contact_type: str = "whatsapp"  # 'whatsapp' | 'telegram'
    phone: str | None = None

    @field_validator("hearing_date")
    @classmethod
    def _v_hearing_date(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_yyyy_mm_dd(v, field_name="hearing_date")

    @field_validator("contact_type")
    @classmethod
    def _v_contact_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in {"whatsapp", "telegram"}:
            raise ValueError("contact_type must be 'whatsapp' or 'telegram'")
        return v

    if _PYDANTIC_V2:
        @model_validator(mode="after")  # type: ignore[misc]
        def _v_contact_requirements(self) -> "AlertRequest":
            if self.contact_type == "whatsapp" and not (self.phone or "").strip():
                raise ValueError("phone is required for WhatsApp alerts")
            return self
    else:  # pragma: no cover (Pydantic v1 fallback)
        @_root_validator  # type: ignore[misc]
        def _v_contact_requirements_v1(cls, values: dict) -> dict:
            if (values.get("contact_type") == "whatsapp") and not (values.get("phone") or "").strip():
                raise ValueError("phone is required for WhatsApp alerts")
            return values

