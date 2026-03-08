import asyncio
from telegram import Bot

async def check():
    bot = Bot(token="8798815358:AAH6Y3HutPBtjb3p1-qDLxPzend2f_A1qu0")
    info = await bot.get_me()
    print(f"Bot: @{info.username} (id={info.id})")
    
    # Try getUpdates to check if polling is active
    try:
        updates = await bot.get_updates(timeout=2)
        print(f"Pending updates: {len(updates)}")
        for u in updates:
            txt = u.message.text if u.message and u.message.text else "(no text)"
            print(f"  Update {u.update_id}: {txt}")
    except Exception as e:
        print(f"getUpdates error (expected if polling active): {e}")

asyncio.run(check())
