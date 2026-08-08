from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    """Schema for creating or updating a product."""
    name: str = Field(..., example="Laptop")
    description: str = Field(..., example="High-performance laptop")
    price: float = Field(..., gt=0, example=999.99)
    stock: int = Field(..., ge=0, example=50)


class Product(ProductCreate):
    """Schema for a product returned from DB or cache."""
    id: int

    class Config:
        from_attributes = True
