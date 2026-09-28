from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateGroupRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


class Member(BaseModel):
    id: UUID
    name: str


class AddMemberRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


class ExpensePayer(StrictModel):
    memberId: UUID
    amount: Decimal = Field(gt=0)


class ExpenseInput(StrictModel):
    description: str = Field(min_length=1, max_length=240)
    amount: Decimal = Field(gt=0)
    category: Literal["Food", "Transport", "Accommodation", "Utilities", "Other"]
    date: date
    payers: list[ExpensePayer] = Field(min_length=1)
    participants: list[UUID] = Field(min_length=1)
    splitType: Literal["equal", "exact", "percentage"]
    shares: dict[UUID, Decimal] | None = None

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description cannot be blank")
        return value.strip()


class RecurringExpenseInput(StrictModel):
    description: str = Field(min_length=1, max_length=240)
    amount: Decimal = Field(gt=0)
    category: Literal["Food", "Transport", "Accommodation", "Utilities", "Other"]
    interval: Literal["weekly", "monthly", "yearly"]

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description cannot be blank")
        return value.strip()


class ReportSettlementRequest(StrictModel):
    fromMemberId: UUID
    toMemberId: UUID
    amount: Decimal = Field(gt=0)


class GroupSettingsPatch(StrictModel):
    simplifyDebts: bool | None = None


class ErrorBody(BaseModel):
    code: str
    message: str


def decimal_json(value: Decimal) -> float:
    return float(value)


def serialize_expense(input_data: ExpenseInput, expense_id: UUID, created_at: str, updated_at: str) -> dict:
    data = input_data.model_dump(mode="json", exclude_none=True)
    data["amount"] = decimal_json(input_data.amount)
    for payer, parsed in zip(data["payers"], input_data.payers, strict=True):
        payer["amount"] = decimal_json(parsed.amount)
    if input_data.shares is not None:
        data["shares"] = {str(member_id): decimal_json(value) for member_id, value in input_data.shares.items()}
    data.update({"id": str(expense_id), "createdAt": created_at, "updatedAt": updated_at})
    return data


def serialize_recurring(input_data: RecurringExpenseInput, schedule_id: UUID, created_at: str) -> dict:
    data = input_data.model_dump(mode="json")
    data["amount"] = decimal_json(input_data.amount)
    data.update({"id": str(schedule_id), "createdAt": created_at})
    return data
