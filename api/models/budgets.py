from decimal import Decimal

from sqlalchemy import Column, Numeric
from sqlmodel import SQLModel, Field


class BudgetBase(SQLModel):
    category: str = Field(primary_key=True)
    limit: Decimal = Field(
        gt=0,
        sa_column=Column(Numeric(10, 2), nullable=False)
    )


class Budget(BudgetBase, table=True):
    pass