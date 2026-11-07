from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Item(BaseModel):
    name: str
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = None


class TransactionExtraction(BaseModel):
    intent: Literal[
        "add_credit",
        "add_payment",
        "check_balance",
        "daily_summary",
        "undo_last",
        "unknown",
    ]
    customer_name: str | None = None
    amount: int | None = Field(default=None, gt=0)
    items: list[Item] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    amount_ambiguous: bool = False
    description: str | None = None


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class TransactionCreate(BaseModel):
    customer_id: int = Field(gt=0)
    transaction_type: Literal["credit", "payment"]
    amount: int = Field(gt=0)
    description: str | None = None


class CustomerMatch(BaseModel):
    customer_id: int = Field(gt=0)
    customer_name: str
    score: float


class CustomerResolution(BaseModel):
    status: Literal["matched", "multiple_matches", "not_found"]
    matches: list[CustomerMatch] = Field(default_factory=list)
