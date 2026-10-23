"""The JSON shapes the model must return. Pydantic rejects anything else, and the
studio retries with the validation error so the model can correct itself."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GeneratedRequirement(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    kind: Literal["Functional", "Non-functional", "Business rule", "Data", "Integration"] = "Functional"

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value):
        options = ["Functional", "Non-functional", "Business rule", "Data", "Integration"]
        for option in options:
            if str(value).strip().lower() == option.lower():
                return option
        return "Functional"


class RequirementsOutput(BaseModel):
    requirements: list[GeneratedRequirement] = Field(min_length=1, max_length=15)


class GeneratedCriterion(BaseModel):
    given: str = ""
    when: str = ""
    then: str = Field(min_length=3)


class UACOutput(BaseModel):
    criteria: list[GeneratedCriterion] = Field(min_length=1, max_length=15)


class GeneratedTestCase(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    preconditions: str = ""
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=3)
    priority: Literal["Low", "Medium", "High", "Critical"] = "Medium"

    @field_validator("steps", mode="before")
    @classmethod
    def _steps(cls, value):
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _priority(cls, value):
        value = str(value).strip().capitalize()
        return value if value in ("Low", "Medium", "High", "Critical") else "Medium"


class TestCasesOutput(BaseModel):
    __test__ = False
    test_cases: list[GeneratedTestCase] = Field(min_length=1, max_length=15)


FEATURES: dict[str, tuple[str, type[BaseModel]]] = {
    "requirements": ("Requirements", RequirementsOutput),
    "uac": ("Acceptance criteria (UAC)", UACOutput),
    "test_cases": ("Test cases", TestCasesOutput),
}
