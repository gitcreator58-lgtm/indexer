import os
import time
import math
import asyncio
import aiohttp
import requests
from pyrogram import Client, filters, errors
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database import add_file, search_files, add_user, get_all_users, db
from web_server import web_server

# --- Setup Directories ---
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# --- Initialize Bot ---
bot = Client(
    "SpeedBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# --- Helper: Auto-Delete (30 Minutes) ---
async def auto_delete(message, delay=1800):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass

# --- Helper: Progress Bar ---
async def progress_bar(current, total, status_msg, start_time):
    now = time.time()
    diff = now - start_time
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        time_to_completion = round((total - current) / speed) * 1000
        progress_str = "[{0}{1}] {2}%".format(
            ''.join(["⬢" for i in range(math.floor(percentage / 10))]),
            ''.join(["⬡" for i in range(10 - math.floor(percentage / 10))]),
            round(percentage, 2))
        tmp = progress_str + "\n**Speed:** {:.2f} MB/s".format(speed / 1024 / 1024)
        try:
            await status_msg.edit(f"**Processing...**\n{tmp}")
        except:
            pass

# ==============================================================================
# 1. CHANNEL INDEXING (OLD & NEW FILES)
# ==============================================================================

# A. Listener for NEW files (Real-time)
@bot.on_message(filters.chat(Config.CHANNEL_ID) & (filters.document | filters.video | filters.audio))
async def new_file_listener(client, message):
    try:
        await add_file(message)
        print(f"Indexed New File: {message.document.file_name if message.document else 'Video'}")
    except Exception as e:
        print(f"Index Error: {e}")

# B. Command to Index OLD files (History Scan)
@bot.on_message(filters.command("index_channel") & filters.user(Config.OWNER_ID))
async def index_channel_handler(client, message):
    status = await message.reply("🧐 **Scanning Channel History...**\nThis may take a while.")
    count = 0
    try:
        # Iterate through history
        async for msg in client.get_chat_history(Config.CHANNEL_ID):
            if msg.document or msg.video or msg.audio:
                await add_file(msg)
                count += 1
                if count % 20 == 0:
                    await status.edit(f"♻️ **Indexing...**\nFound: {count} files")
        
        await status.edit(f"✅ **Index Complete!**\n\nTotal Files Added: {count}")
    except Exception as e:
        await status.edit(f"❌ **Error:** {e}\n\nMake sure I am Admin in the channel!")

# ==============================================================================
# 2. SEARCH & FILE DELIVERY
# ==============================================================================
@bot.on_message(filters.command("search"))
async def search_handler(client, message):
    if len(message.command) < 2:
        return await message.reply("Give me a file name! Ex: `/search Avengers`")
    
    query = " ".join(message.command[1:])
    results = await search_files(query)
    
    found = False
    async for file in results:
        found = True
        stream_link = f"{Config.BASE_URL}/watch/{file['msg_id']}"
        
        # Glass Buttons
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Fast Download / Stream", url=stream_link)],
            [InlineKeyboardButton("✏️ Rename File", callback_data=f"rename_{file['msg_id']}")]
        ])
        
        caption = file.get('caption', 'No Caption')
        # Truncate caption if too long
        if len(caption) > 100: caption = caption[:100] + "..."

        msg = await message.reply_text(
            f"🎬 **File Found:** `{file['file_name']}`\n"
            f"💾 **Size:** {file['file_size']}\n"
            f"📝 **Caption:** {caption}\n\n"
            f"🔗 [Direct Fast Link]({stream_link})",
            reply_markup=btn
        )
        asyncio.create_task(auto_delete(msg)) # Auto delete after 30 mins

    if not found:
        await message.reply("❌ No files found. Try `/index_channel` if you haven't yet.")

# ==============================================================================
# 3. RENAME LOGIC
# ==============================================================================
@bot.on_callback_query(filters.regex(r"^rename_"))
async def rename_callback(client, callback):
    msg_id = callback.data.split("_")[1]
    # Instruct user how to rename
    await callback.message.reply(
        f"**To Rename this file:**\n"
        f"Copy the command below and replace `NewName`:\n\n"
        f"`/genlink {msg_id} My_New_Movie_Name.mkv`",
        quote=True
    )

@bot.on_message(filters.command("genlink"))
async def generate_renamed_link(client, message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3: return await message.reply("Usage: `/genlink ID NewName`")
        
        msg_id, new_name = parts[1], parts[2]
        stream_link = f"{Config.BASE_URL}/watch/{msg_id}?name={new_name}"
        
        await message.reply(
            f"✅ **Renamed Link Generated:**\n\n{stream_link}\n\n_Clicking this will download the file as '{new_name}'_",
            disable_web_page_preview=True
        )
    except:
        pass

# ==============================================================================
# 4. TERABOX & PRIVATE FILES (Fast Link Generator)
# ==============================================================================
def get_terabox_direct_link(url):
    headers = {"User-Agent": "Mozilla/5.0", "Cookie": "browserid=1; lang=en;"}
    try: return requests.get(url, headers=headers).url 
    except: return None

@bot.on_message(filters.regex(r"terabox\.com|1024tera\.com"))
async def terabox_handler(client, message):
    url = message.text.strip()
    status_msg = await message.reply("🔎 **Processing TeraBox...**")

    try:
        direct_link = get_terabox_direct_link(url)
        if not direct_link: return await status_msg.edit("❌ Failed to get Link.")

        file_path = f"downloads/terabox_{int(time.time())}.mp4"
        await status_msg.edit("⬇️ **Downloading...**")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(direct_link) as resp:
                if resp.status != 200: return await status_msg.edit("❌ Error.")
                with open(file_path, 'wb') as f:
                    while True:
                        chunk = await resp.content.read(1024*1024)
                        if not chunk: break
                        f.write(chunk)
        
        # Check for Custom Thumbnail in DB
        user_db = await db.users.find_one({'user_id': message.from_user.id})
        thumb_path = None
        if user_db and 'thumb_id' in user_db:
            thumb_path = await client.download_media(user_db['thumb_id'], file_name=f"thumbs/{message.from_user.id}.jpg")

        await status_msg.edit("⬆️ **Uploading...**")
        start_time = time.time()
        
        log_msg = await client.send_document(
            Config.CHANNEL_ID,
            document=file_path,
            thumb=thumb_path,
            caption=f"Source: {url}",
            progress=progress_bar,
            progress_args=(status_msg, start_time)
        )
        
        await add_file(log_msg)
        os.remove(file_path)
        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
        
        stream_link = f"{Config.BASE_URL}/watch/{log_msg.id}"
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Fast Download", url=stream_link)]])
        
        reply = await status_msg.edit(f"✅ **Done!**\nFile: `{log_msg.document.file_name}`", reply_markup=btn)
        asyncio.create_task(auto_delete(reply))

    except Exception as e:
        await status_msg.edit(f"Error: {e}")
        if os.path.exists(file_path): os.remove(file_path)

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def direct_convert_handler(client, message):
    # Convert any file sent to bot into Fast Link
    log_msg = await message.copy(Config.CHANNEL_ID)
    await add_file(log_msg)
    stream_link = f"{Config.BASE_URL}/watch/{log_msg.id}"
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Fast Download", url=stream_link)],
        [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_{log_msg.id}")]
    ])
    msg = await message.reply(f"✅ **Fast Link Ready:**\n{stream_link}", reply_markup=btn)
    asyncio.create_task(auto_delete(msg))

# ==============================================================================
# 5. THUMBNAIL MANAGEMENT (Persistent)
# ==============================================================================
@bot.on_message(filters.command("set_thumb") & filters.reply)
async def set_thumb_handler(client, message):
    if not message.reply_to_message.photo: return await message.reply("Reply to a photo.")
    # Save the File ID of the photo to the DB
    photo_id = message.reply_to_message.photo.file_id
    await db.users.update_one({'user_id': message.from_user.id}, {'$set': {'thumb_id': photo_id}}, upsert=True)
    await message.reply("✅ **Thumbnail Saved!** It will be used for TeraBox uploads.")

@bot.on_message(filters.command("del_thumb"))
async def del_thumb_handler(client, message):
    await db.users.update_one({'user_id': message.from_user.id}, {'$unset': {'thumb_id': 1}})
    await message.reply("🗑 **Thumbnail Deleted.**")

# ==============================================================================
# 6. START & SYSTEM
# ==============================================================================
@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    try: await add_user(message.from_user.id)
    except: pass
    
    LIVE_IMG = "https://files.catbox.moe/maft7d.jpg"
    txt = (f"👋 **Hello {message.from_user.mention}!**\n\n"
           f"**Admin Command:** `/index_channel` (RUN THIS ONCE!)\n\n"
           f"**User Features:**\n"
           f"• `/search Name` - Find movies\n"
           f"• Send File - Get Fast Link\n"
           f"• Send TeraBox Link - Download it\n"
           f"• `/set_thumb` (Reply to photo) - Set Custom Thumb")
    
    try: await client.send_photo(message.chat.id, LIVE_IMG, caption=txt)
    except: await client.send_message(message.chat.id, txt)

if __name__ == "__main__":
    print("Bot Starting...")
    Config.PORT = 8080 
    bot.loop.run_until_complete(web_server(bot))
    bot.run()
