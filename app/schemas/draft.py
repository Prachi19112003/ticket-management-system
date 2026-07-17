from pydantic import BaseModel, Field, field_validator

class DraftResponseSchema(BaseModel):
    draft_reply: str = Field(..., description="The generated email response draft.")
    category_confirmation: str = Field(..., description="Confirmed category classification (Sales, Procurement, or General).")
    cc_list: list[str] = Field(default_factory=list, description="Suggested additional CC emails.")
    confidence_score: float = Field(..., description="Draft confidence score between 0.0 and 1.0.")

    @field_validator("confidence_score")
    @classmethod
    def validate_confidence_range(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("confidence_score must reside within bounds [0.0, 1.0]")
        return value

    @field_validator("category_confirmation")
    @classmethod
    def validate_category_value(cls, value: str) -> str:
        allowed = {"Sales", "Procurement", "General"}
        if value not in allowed:
            raise ValueError(f"category_confirmation must be one of {allowed}")
        return value
