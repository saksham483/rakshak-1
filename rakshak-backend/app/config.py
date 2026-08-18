import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rakshak.db")
TICK_SECONDS = float(os.getenv("TICK_SECONDS", "1.0"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

# A real LEO eclipse cycle takes ~90-100 real minutes - too slow to be watchable live in a
# demo. Reported satellite POSITION always uses true real time (that part stays fully real).
# Only the eclipse phase used to modulate the solar-power channel is optionally accelerated
# by this factor, and the API always discloses it via the "time_scale" field so it's never
# silently passed off as real-time. Set to 1.0 to disable and run fully real-time.
ORBIT_TIME_SCALE = float(os.getenv("ORBIT_TIME_SCALE", "1.0"))
