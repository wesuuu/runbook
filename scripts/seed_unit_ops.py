import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from app.models.science import UnitOpDefinition

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"

DEFAULT_OPS = [
    {
        "name": "Thaw",
        "category": "Upstream",
        "description": "Thaw cryopreserved cells from liquid nitrogen storage.",
        "param_schema": {
            "type": "object",
            "properties": {
                "vial_count": {"type": "integer", "title": "Vial Count", "default": 1},
                "thaw_temp_c": {"type": "number", "title": "Thaw Temperature (°C)", "default": 37.0},
                "duration_min": {"type": "number", "title": "Thaw Duration (min)", "default": 2.0}
            }
        }
    },
    {
        "name": "Seeding",
        "category": "Upstream",
        "description": "Inoculate bioreactor or flask with cell suspension.",
        "param_schema": {
            "type": "object",
            "properties": {
                "target_density": {"type": "number", "title": "Target Density (cells/mL)", "default": 300000},
                "volume_ml": {"type": "number", "title": "Working Volume (mL)", "default": 1000},
                "vessel_type": {"type": "string", "title": "Vessel Type", "enum": ["Shake Flask", "Bioreactor", "T-Flask"]}
            }
        }
    },
    {
        "name": "Feed",
        "category": "Upstream",
        "description": "Add nutrient feed to the culture.",
        "param_schema": {
            "type": "object",
            "properties": {
                "feed_type": {"type": "string", "title": "Feed Type", "enum": ["Glucose", "Glutamine", "Hypoxanthine", "Complete Feed"]},
                "volume_ml": {"type": "number", "title": "Feed Volume (mL)", "default": 50}
            }
        }
    },
    {
        "name": "Harvest",
        "category": "Downstream",
        "description": "Separate cells from culture media.",
        "param_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "title": "Harvest Method", "enum": ["Centrifugation", "Filtration"]},
                "speed_rpm": {"type": "integer", "title": "Centrifuge Speed (RPM)", "default": 3000},
                "duration_min": {"type": "number", "title": "Duration (min)", "default": 15}
            }
        }
    }
]

async def seed_unit_ops():
    engine = create_async_engine(DATABASE_URL)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        print("Seeding UnitOps...")
        for op_data in DEFAULT_OPS:
            result = await session.execute(select(UnitOpDefinition).where(UnitOpDefinition.name == op_data["name"]))
            existing = result.scalar_one_or_none()
            
            if not existing:
                print(f"Creating {op_data['name']}...")
                op = UnitOpDefinition(**op_data)
                session.add(op)
            else:
                print(f"Skipping {op_data['name']} (exists).")
        
        await session.commit()
        print("Done.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_unit_ops())
