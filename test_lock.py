import asyncio
try:
    lock = asyncio.Lock()
    print("Success")
except Exception as e:
    print(f"Error: {e}")
