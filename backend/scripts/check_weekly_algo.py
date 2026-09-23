"""Read-only check of last closed week's email algorithm counters; sends nothing."""
import asyncio
import json
from datetime import datetime, timezone

from db.database import AsyncSessionLocal
from services.email_campaigns import period, weekly_algorithm_numbers


async def main():
    start, end = period(datetime.now(timezone.utc))
    async with AsyncSessionLocal() as session:
        metrics = await weekly_algorithm_numbers(session, start, end)
    print(json.dumps({"period": start.date().isoformat(), **metrics}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
