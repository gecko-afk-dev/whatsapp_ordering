import argparse
import asyncio
import csv
import os
import secrets
import string
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load env before importing models to ensure DB URL is present
load_dotenv()

from app.models import BetaCard, BetaCardStatus
from app.core.config import settings

def generate_card_code() -> str:
    # GEQO-XXXXXX (6 uppercase alphanumeric)
    alphabet = string.ascii_uppercase + string.digits
    chars = ''.join(secrets.choice(alphabet) for _ in range(6))
    return f"GEQO-{chars}"

async def main():
    parser = argparse.ArgumentParser(description="Generate Beta Cards for GEQO Pilot")
    parser.add_argument("--count", type=int, default=50, help="Number of cards to generate (default 50)")
    args = parser.parse_args()

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    cards_generated = []

    async with AsyncSessionLocal() as session:
        for _ in range(args.count):
            code = generate_card_code()
            new_card = BetaCard(
                card_code=code,
                status=BetaCardStatus.AVAILABLE
            )
            session.add(new_card)
            cards_generated.append(code)
        
        await session.commit()
    
    await engine.dispose()

    # Generate CSV
    date_str = datetime.now().strftime("%Y%m%d")
    csv_filename = f"beta_cards_batch_{date_str}.csv"
    base_url = "https://mygeqo.com/claim?card="
    
    with open(csv_filename, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["card_code", "qr_url"])
        for code in cards_generated:
            writer.writerow([code, f"{base_url}{code}"])

    print(f"Successfully generated {args.count} cards and saved to {csv_filename}")

if __name__ == "__main__":
    asyncio.run(main())
