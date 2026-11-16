from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
DescriptionStr = Annotated[str, StringConstraints(max_length=5000)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorOut(BaseModel):
    detail: str
