import asyncio
import asyncpg

async def create_test_db():
    try:
        # Connect to 'postgres' database to create new DB
        conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/postgres')
        
        # Check if exists
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname='runbook_test'")
        
        if not exists:
            print("Creating database runbook_test...")
            await conn.execute('CREATE DATABASE runbook_test')
            print("Database created.")
        else:
            print("Database runbook_test already exists.")
            
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(create_test_db())
