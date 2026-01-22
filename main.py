import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database import add_file, search_files, get_file_by_id
from web_server import web_server

# Initialize Bot
bot = Client(
    "MySuperBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# --- 1. Indexing files from Channel ---
@bot.on_message(filters.chat(Config.CHANNEL_ID) & (filters.document | filters.video))
async def auto_index(client, message):
    await add_file(message)
    # Optional: Send log to owner
    # await client.send_message(Config.OWNER_ID, f"Indexed: {message.document.file_name}")

# --- 2. Searching Files (User Command) ---
@bot.on_message(filters.command("search"))
async def search_handler(client, message):
    if len(message.command) < 2:
        return await message.reply("Give me a movie name! Ex: `/search Avengers`")
    
    query = " ".join(message.command[1:])
    results = await search_files(query)
    found = False
    
    async for file in results:
        found = True
        # Create Fast Download Link
        stream_link = f"{Config.BASE_URL}/watch/{file['msg_id']}"
        
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Fast Download / Watch", url=stream_link)],
            [InlineKeyboardButton("🗑 Delete (30s)", callback_data=f"del_{file['msg_id']}")]
        ])
        
        msg = await message.reply_text(
            f"**File:** `{file['file_name']}`\n**Size:** {file['file_size']}\n\n[Glass Button Added]",
            reply_markup=btn
        )
        
        # --- 3. Auto Delete Feature ---
        asyncio.create_task(auto_delete(msg, 30)) # Delete after 30 minutes (1800 sec)

    if not found:
        await message.reply("No files found in my database.")

# --- Helper: Auto Delete ---
async def auto_delete(message, delay_seconds):
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
        # Optionally notify user via a temp message or edit
    except:
        pass

# --- 4. Manual Link/File Handling & Renaming ---
@bot.on_message(filters.private & (filters.document | filters.video))
async def handle_user_file(client, message):
    # The user sent a file. We provide a direct link to it.
    # Note: For private files, you might need to forward them to the log channel first to make them accessible via URL.
    
    # Forward to Log Channel (Storage)
    log_msg = await message.forward(Config.CHANNEL_ID)
    await add_file(log_msg)
    
    stream_link = f"{Config.BASE_URL}/watch/{log_msg.id}"
    
    # Renaming Logic: The user can just append ?name=NewName to the URL
    await message.reply(
        f"**File Received!**\n\nOriginal: `{message.document.file_name}`\n\n"
        f"⬇️ **Fast Link:** {stream_link}\n\n"
        f"✏️ **To Rename:** Click the link below, it will download with new name:\n"
        f"`{stream_link}?name=Renamed_File.mkv`",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Fast Download", url=stream_link)]])
    )

# --- 5. Broadcast Feature ---
@bot.on_message(filters.command("broadcast") & filters.user(Config.OWNER_ID))
async def broadcast(client, message):
    # Logic to loop through users in DB and send message
    await message.reply("Broadcast functionality here (requires saving user IDs in DB).")

if __name__ == "__main__":
    print("Bot Starting...")
    bot.loop.run_until_complete(web_server(bot))
    bot.run()
