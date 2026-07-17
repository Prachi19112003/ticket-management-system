import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.customer import Customer

class CustomerRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, customer_id: uuid.UUID) -> Customer | None:
        """Fetch a customer profile by its primary key UUID."""
        result = await self.db.execute(select(Customer).filter(Customer.id == customer_id))
        return result.scalars().first()

    async def get_by_email(self, email: str) -> Customer | None:
        """Fetch a customer profile by their email address."""
        result = await self.db.execute(select(Customer).filter(Customer.email == email))
        return result.scalars().first()

    async def create(self, customer: Customer) -> Customer:
        """Persist a new customer profile to the database."""
        self.db.add(customer)
        await self.db.commit()
        await self.db.refresh(customer)
        return customer
