import asyncio
from app.main import app
import logging

# Set logging to capture issues
logging.basicConfig(level=logging.INFO)

async def main():
    try:
        # Start lifespan
        print("Starting app...")
        async with app.router.lifespan_context(app):
            print("Startup successful")
            await asyncio.sleep(2)
            print("Shutdown starting")
        print("Shutdown successful")
        
    except Exception as e:
        print(f"Startup failed: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
