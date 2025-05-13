import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_NAME = os.getenv("DB_NAME")

async def init_db():
    if not all([DB_HOST, DB_PORT, DB_USER, DB_NAME]):
        print("Error: DB connection details not found in .env")
        return
    conn = None
    try:
        conn = await asyncpg.connect(
            user=DB_USER,
            port=DB_PORT,
            host=DB_HOST,
            database=DB_NAME,
        )
        print(f"Connected to DB: {DB_HOST}:{DB_PORT}/{DB_NAME}")
        await conn.execute(open("scripts/schema.sql").read())
        print("Schema initialized successfully")
    except asyncpg.exceptions.PostgresError as e:
        print(f"Database error during initialization: {e}")
    except Exception as e:
        print(f"Unexpected error during initialization: {e}")
    finally:
        if conn:
            await conn.close();
            print("DB connection closed");

if __name__ == "__main__":
    print("Starting DB initialization...");
    asyncio.run(init_db());
            
        