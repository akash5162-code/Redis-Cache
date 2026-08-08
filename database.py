import asyncio
import aiosqlite

# Path to the SQLite database file
DB_PATH = "products.db"


async def init_db():
    """
    Initialize the SQLite database.
    Creates the products table if it doesn't exist,
    and seeds it with sample data on first run.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Create table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                description TEXT,
                price       REAL    NOT NULL,
                stock       INTEGER NOT NULL
            )
        """)
        await db.commit()

        # Seed data only if table is empty
        cursor = await db.execute("SELECT COUNT(*) FROM products")
        (count,) = await cursor.fetchone()

        if count == 0:
            seed_data = [
                ("Laptop",      "High-performance laptop",           999.99, 50),
                ("Phone",       "Latest smartphone",                 699.99, 100),
                ("Headphones",  "Noise-cancelling headphones",       299.99, 200),
                ("Tablet",      "10-inch Android tablet",            499.99, 75),
                ("Smartwatch",  "Fitness-tracking smartwatch",       199.99, 150),
            ]
            await db.executemany(
                "INSERT INTO products (name, description, price, stock) VALUES (?, ?, ?, ?)",
                seed_data,
            )
            await db.commit()
            print("✅ Database seeded with sample products")

    print("✅ SQLite database initialized")


async def get_product_by_id(product_id: int) -> dict | None:
    """
    Fetch a single product by its ID from SQLite.
    
    ⚠️  Intentional 500ms delay to simulate a slow database query.
    This delay makes the Redis caching benefit CLEARLY visible —
    the first request is slow, subsequent cached requests are instant.
    """
    await asyncio.sleep(0.5)  # Simulate slow DB query

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_products() -> list[dict]:
    """Fetch all products from SQLite (no caching — always fresh)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM products ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def create_product(name: str, description: str, price: float, stock: int) -> int:
    """Insert a new product and return the new row's ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO products (name, description, price, stock) VALUES (?, ?, ?, ?)",
            (name, description, price, stock),
        )
        await db.commit()
        return cursor.lastrowid


async def update_product(product_id: int, name: str, description: str, price: float, stock: int):
    """Update an existing product by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE products SET name=?, description=?, price=?, stock=? WHERE id=?",
            (name, description, price, stock, product_id),
        )
        await db.commit()


async def delete_product(product_id: int):
    """Delete a product by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE id=?", (product_id,))
        await db.commit()
