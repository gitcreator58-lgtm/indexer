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

# Setup
if not os.path.exists("downloads"): os.makedirs("downloads")

bot = Client("SpeedBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN)

# --- 1. Auto-Delete (30 Minutes) ---
async def auto_delete(message, delay=1800):
    await asyncio.sleep(delay)
    try:
        await message.delete()
        # Optional: Send a tiny "File Expired" toast if needed
    except: pass

# --- 2. Progress Bar ---
async def progress_bar(current, total, status_msg, start_time):
    now = time.time()
    diff = now - start_time
    if round(diff % 5.00) == 0 or current == total:
        speed = current / (diff or 1)
        await status_msg.edit(f"⬇️ **Downloading...**\nSpeed: {speed/1024/1024:.2f} MB/s")

# ==============================================================================
# 3. START MESSAGE (Instant Pop-up)
# ==============================================================================
@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    try: await add_user(message.from_user.id)
    except: pass
    
    # Custom Image
    LIVE_IMG = "https://files.catbox.moe/maft7d.jpg"
    
    txt = (f"👋 **Hello {message.from_user.mention}!**\n\n"
           f"🟢 **Bot Online & Ready**\n\n"
           f"🔹 **Search Files:** `/search Name`\n"
           f"🔹 **Rename:** Click 'Rename' on any file\n"
           f"🔹 **TeraBox:** Send link to download\n"
           f"🔹 **Index Channel:** `/index_channel` (Admin Only)")
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Updates Channel", url="https://t.me/YourChannelLink")],
        [InlineKeyboardButton("🔎 Search Mode", switch_inline_query_current_chat="")]
    ])

    try: await client.send_photo(message.chat.id, LIVE_IMG, caption=txt, reply_markup=btn)
    except: await client.send_message(message.chat.id, txt, reply_markup=btn)

# ==============================================================================
# 4. INDEX CHANNEL (Fixes Missing Files)
# ==============================================================================
@bot.on_message(filters.command("index_channel") & filters.user(Config.OWNER_ID))
async def index_channel(client, message):
    status = await message.reply("🧐 **Scanning Channel...**")
    count = 0
    async for msg in client.get_chat_history(Config.CHANNEL_ID):
        if msg.document or msg.video or msg.audio:
            await add_file(msg)
            count += 1
            if count % 50 == 0: await status.edit(f"♻️ Indexed: {count} files...")
    await status.edit(f"✅ **Done!** Indexed {count} files.")

# Listener for NEW Channel Files
@bot.on_message(filters.chat(Config.CHANNEL_ID) & (filters.document | filters.video))
async def auto_index(client, message):
    await add_file(message)

# ==============================================================================
# 5. SEARCH & GLASS BUTTONS (File Delivery)
# ==============================================================================
@bot.on_message(filters.command("search"))
async def search_handler(client, message):
    if len(message.command) < 2: return await message.reply("Usage: `/search Avengers`")
    
    query = " ".join(message.command[1:])
    results = await search_files(query)
    found = False
    
    async for file in results:
        found = True
        link = f"{Config.BASE_URL}/watch/{file['msg_id']}"
        
        # GLASS BUTTONS
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Fast Download / Stream", url=link)],
            [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_{file['msg_id']}")]
        ])
        
        msg = await message.reply_text(
            f"🎬 **{file['file_name']}**\n"
            f"📦 Size: {file['file_size']}\n\n"
            f"🔗 [Fast Link]({link})\n"
            f"⚠️ *Auto-deletes in 30 mins*",
            reply_markup=btn
        )
        asyncio.create_task(auto_delete(msg)) # 30 Min Delete

    if not found: await message.reply("❌ No files found. Try `/index_channel` first.")

# ==============================================================================
# 6. RENAME & CAPTION
# ==============================================================================
@bot.on_callback_query(filters.regex(r"^rename_"))
async def rename_cb(client, callback):
    msg_id = callback.data.split("_")[1]
    await callback.message.reply(
        f"✏️ **To Rename:**\nUse: `/genlink {msg_id} New_Name.mp4`", quote=True
    )

@bot.on_message(filters.command("genlink"))
async def gen_link(client, message):
    try:
        _, msg_id, name = message.text.split(maxsplit=2)
        link = f"{Config.BASE_URL}/watch/{msg_id}?name={name}"
        msg = await message.reply(
            f"✅ **Renamed!**\n\n[{name}]({link})\n\n_Click link to download with new name._",
            disable_web_page_preview=True
        )
        asyncio.create_task(auto_delete(msg))
    except:
        await message.reply("❌ Usage: `/genlink ID NewName`")

# ==============================================================================
# 7. TERABOX DOWNLOADER (With Thumbnails)
# ==============================================================================
@bot.on_message(filters.regex(r"terabox\.com|1024tera\.com"))
async def terabox_dl(client, message):
    url = message.text.strip()
    status = await message.reply("🔎 **Processing TeraBox...**")
    
    # 1. Get Direct Link (Basic)
    try:
        direct = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Cookie": "browserid=1;"}).url
    except:
        return await status.edit("❌ Link Error")

    # 2. Download
    path = f"downloads/{int(time.time())}.mp4"
    await status.edit("⬇️ **Downloading...**")
    async with aiohttp.ClientSession() as sess:
        async with sess.get(direct) as resp:
            if resp.status != 200: return await status.edit("❌ Failed.")
            with open(path, 'wb') as f:
                while True:
                    chunk = await resp.content.read(1024*1024)
                    if not chunk: break
                    f.write(chunk)
    
    # 3. Upload with Thumbnail
    await status.edit("⬆️ **Uploading...**")
    user_db = await db.users.find_one({'user_id': message.from_user.id})
    thumb = None
    if user_db and 'thumb_id' in user_db:
        thumb = await client.download_media(user_db['thumb_id'], file_name=f"downloads/th_{message.id}.jpg")

    log = await client.send_document(
        Config.CHANNEL_ID, document=path, thumb=thumb,
        caption=f"Source: {url}", progress=progress_bar, progress_args=(status, time.time())
    )
    
    # 4. Cleanup & Index
    await add_file(log)
    os.remove(path)
    if thumb: os.remove(thumb)
    
    link = f"{Config.BASE_URL}/watch/{log.id}"
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Fast Download", url=link)],
        [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_{log.id}")]
    ])
    msg = await status.edit(f"✅ **Done!**\n`{log.document.file_name}`", reply_markup=btn)
    asyncio.create_task(auto_delete(msg))

# ==============================================================================
# 8. THUMBNAIL & BROADCAST
# ==============================================================================
@bot.on_message(filters.command("set_thumb") & filters.reply)
async def set_thumb(client, message):
    if not message.reply_to_message.photo: return
    await db.users.update_one({'user_id': message.from_user.id}, 
                              {'$set': {'thumb_id': message.reply_to_message.photo.file_id}}, upsert=True)
    await message.reply("✅ **Thumbnail Saved!**")

@bot.on_message(filters.command("broadcast") & filters.user(Config.OWNER_ID))
async def broadcast(client, message):
    if not message.reply_to_message: return
    await message.reply("📢 Broadcasting...")
    users = await get_all_users()
    async for user in users:
        try: await message.reply_to_message.copy(user['user_id'])
        except: pass

# --- SERVER START ---
if __name__ == "__main__":
    print("Bot Starting on 8080...")
    Config.PORT = 8080 
    bot.loop.run_until_complete(web_server(bot))
    bot.run()
