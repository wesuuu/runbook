import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from app.models.science import UnitOpDefinition
import app.models.iam  # needed for relationship resolution

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/runbook"

DEFAULT_OPS = [
    # --- Media Prep ---
    # --- Media Prep ---
    {
        "name": "Buffer Mix",
        "category": "Media Prep",
        "description": "Prepare buffers or media by mixing components to target specs.",
        "param_schema": {
            "type": "object",
            "properties": {
                "volume_ml": {"type": "number", "title": "Volume (mL)", "default": 500},
                "mix_time_min": {"type": "number", "title": "Mix Time (min)", "default": 45}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "actual_volume_ml": {"type": "number", "title": "Actual Volume", "unit": "mL"}
            },
            "required": ["actual_volume_ml"]
        }
    },
    {
        "name": "Filtration",
        "category": "Media Prep",
        "description": "Filter media or buffer through a membrane.",
        "param_schema": {
            "type": "object",
            "properties": {
                "filter_type": {"type": "string", "title": "Filter Type", "enum": ["Depth Filter", "Sterile Filter", "TFF"]},
                "pore_size_um": {"type": "number", "title": "Pore Size (µm)", "default": 0.22}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "filtrate_volume_ml": {"type": "number", "title": "Filtrate Volume", "unit": "mL"}
            },
            "required": ["filtrate_volume_ml"]
        }
    },
    # --- Cell Culture ---
    {
        "name": "Thaw",
        "category": "Cell Culture",
        "description": "Thaw cryopreserved cells from liquid nitrogen storage.",
        "param_schema": {
            "type": "object",
            "properties": {
                "vial_count": {"type": "integer", "title": "Vial Count", "default": 1},
                "thaw_temp_c": {"type": "number", "title": "Thaw Temperature (°C)", "default": 37.0},
                "duration_min": {"type": "number", "title": "Thaw Duration (min)", "default": 2.0},
                "media_source": {"type": "string", "title": "Media Source", "x-ref-type": "media_prep"}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "actual_duration_min": {"type": "number", "title": "Actual Duration", "unit": "min"}
            },
            "required": ["actual_duration_min"]
        }
    },
    {
        "name": "Seeding",
        "category": "Cell Culture",
        "description": "Inoculate bioreactor or flask with cell suspension.",
        "param_schema": {
            "type": "object",
            "properties": {
                "target_density": {"type": "number", "title": "Target Density (cells/mL)", "default": 300000},
                "volume_ml": {"type": "number", "title": "Working Volume (mL)", "default": 1000},
                "vessel_type": {"type": "string", "title": "Vessel Type", "enum": ["Shake Flask", "Bioreactor", "T-Flask"]},
                "media_source": {"type": "string", "title": "Media Source", "x-ref-type": "media_prep"}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "actual_density": {"type": "number", "title": "Actual Density", "unit": "cells/mL"}
            },
            "required": ["actual_density"]
        }
    },
    # --- Reaction ---
    {
        "name": "Bioreactor",
        "category": "Reaction",
        "description": "Run bioreactor at controlled conditions.",
        "param_schema": {
            "type": "object",
            "properties": {
                "target_ph": {"type": "number", "title": "Target pH", "default": 7.2},
                "temperature_c": {"type": "number", "title": "Temperature (°C)", "default": 37.0},
                "agitation_rpm": {"type": "integer", "title": "Agitation (RPM)", "default": 150}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "measured_ph": {"type": "number", "title": "Measured pH"}
            },
            "required": ["measured_ph"]
        }
    },
    {
        "name": "pH Adjustment",
        "category": "Reaction",
        "description": "Adjust pH of solution to target value.",
        "param_schema": {
            "type": "object",
            "properties": {
                "target_ph": {"type": "number", "title": "Target pH", "default": 7.4},
                "tolerance": {"type": "number", "title": "Tolerance (±)", "default": 0.1},
                "acid_base_type": {"type": "string", "title": "Acid / Base Type", "enum": ["NaOH / HCl", "KOH / H2SO4", "Tris / Citric Acid"]}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "measured_ph": {"type": "number", "title": "Measured pH"}
            },
            "required": ["measured_ph"]
        }
    },
    {
        "name": "Feed",
        "category": "Reaction",
        "description": "Add nutrient feed to the culture.",
        "param_schema": {
            "type": "object",
            "properties": {
                "feed_type": {"type": "string", "title": "Feed Type", "enum": ["Glucose", "Glutamine", "Hypoxanthine", "Complete Feed"]},
                "volume_ml": {"type": "number", "title": "Feed Volume (mL)", "default": 50},
                "media_source": {"type": "string", "title": "Media Source", "x-ref-type": "media_prep"}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "actual_volume_ml": {"type": "number", "title": "Actual Volume", "unit": "mL"}
            },
            "required": ["actual_volume_ml"]
        }
    },
    # --- Incubate ---
    {
        "name": "Incubate",
        "category": "Incubate",
        "description": "Hold culture at controlled temperature, CO₂, and humidity.",
        "param_schema": {
            "type": "object",
            "properties": {
                "temperature_c": {"type": "number", "title": "Temperature (°C)", "default": 37.0},
                "duration_hr": {"type": "number", "title": "Duration (hr)", "default": 24},
                "co2_percent": {"type": "number", "title": "CO₂ (%)", "default": 5.0},
                "humidity_percent": {"type": "number", "title": "Humidity (%)", "default": 95.0}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "actual_duration_hr": {"type": "number", "title": "Actual Duration", "unit": "hr"}
            }
        }
    },
    {
        "name": "Temp Control",
        "category": "Incubate",
        "description": "Maintain a target temperature for a specified hold time.",
        "param_schema": {
            "type": "object",
            "properties": {
                "target_temp_c": {"type": "number", "title": "Target Temp (°C)", "default": 37.0},
                "hold_time_min": {"type": "number", "title": "Hold Time (min)", "default": 60}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "actual_temp_c": {"type": "number", "title": "Actual Temperature", "unit": "°C"}
            },
            "required": ["actual_temp_c"]
        }
    },
    # --- Harvest ---
    {
        "name": "Harvest",
        "category": "Harvest",
        "description": "Separate cells from culture media.",
        "param_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "title": "Harvest Method", "enum": ["Centrifugation", "Filtration", "Depth Filtration"]},
                "speed_rpm": {"type": "integer", "title": "Centrifuge Speed (RPM)", "default": 3000},
                "duration_min": {"type": "number", "title": "Duration (min)", "default": 15}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "yield_g": {"type": "number", "title": "Yield", "unit": "g"}
            },
            "required": ["yield_g"]
        }
    },
    # --- Purification ---
    {
        "name": "Chromatography",
        "category": "Purification",
        "description": "Purify product using column chromatography.",
        "param_schema": {
            "type": "object",
            "properties": {
                "column_type": {"type": "string", "title": "Column Type", "enum": ["Protein A", "Ion Exchange", "Size Exclusion", "Affinity"]},
                "flow_rate_ml_min": {"type": "number", "title": "Flow Rate (mL/min)", "default": 5.0},
                "load_volume_ml": {"type": "number", "title": "Load Volume (mL)", "default": 100}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "recovery_percent": {"type": "number", "title": "Recovery", "unit": "%"}
            },
            "required": ["recovery_percent"]
        }
    },
    # --- Quality Check ---
    {
        "name": "Cell Count",
        "category": "Quality Check",
        "description": "Count cells and measure viability.",
        "param_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "title": "Method", "enum": ["Trypan Blue", "Vi-CELL", "Hemocytometer"]},
                "sample_volume_ul": {"type": "number", "title": "Sample Volume (µL)", "default": 500}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "viable_cell_density": {"type": "number", "title": "Viable Cell Density", "unit": "cells/mL"},
                "viability": {"type": "number", "title": "Viability", "unit": "%"}
            },
            "required": ["viable_cell_density"]
        }
    },
    {
        "name": "Viability Assay",
        "category": "Quality Check",
        "description": "Measure cell viability percentage.",
        "param_schema": {
            "type": "object",
            "properties": {
                "assay_type": {"type": "string", "title": "Assay Type", "enum": ["Trypan Blue Exclusion", "Alamar Blue", "MTT"]},
                "threshold_percent": {"type": "number", "title": "Viability Threshold (%)", "default": 90.0}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "viability_percent": {"type": "number", "title": "Viability", "unit": "%"}
            },
            "required": ["viability_percent"]
        }
    },
    # --- Analytics ---
    {
        "name": "HPLC Analysis",
        "category": "Analytics",
        "description": "Analyze sample composition via HPLC.",
        "param_schema": {
            "type": "object",
            "properties": {
                "column": {"type": "string", "title": "Column", "enum": ["C18", "C8", "HILIC", "SEC"]},
                "injection_volume_ul": {"type": "number", "title": "Injection Volume (µL)", "default": 10},
                "run_time_min": {"type": "number", "title": "Run Time (min)", "default": 30}
            }
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "peak_area": {"type": "number", "title": "Peak Area"}
            },
            "required": ["peak_area"]
        }
    },
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
                print(f"  + Creating {op_data['name']} [{op_data['category']}]")
                op = UnitOpDefinition(**op_data)
                session.add(op)
            else:
                # Update existing ops with new category/schema
                print(f"  ~ Updating {op_data['name']} [{op_data['category']}]")
                existing.category = op_data["category"]
                existing.description = op_data["description"]
                existing.param_schema = op_data["param_schema"]
                existing.result_schema = op_data.get("result_schema", {})
        
        await session.commit()
        print(f"Done. {len(DEFAULT_OPS)} unit ops seeded.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_unit_ops())
