import os
import time
import math
import asyncio
import aiohttp
import requests
from pyrogram import Client, filters, errors
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database import add_file, search_files, add_user, get_all_users
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

# --- Helper: Progress Bar for Upload/Download ---
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
        
        tmp = progress_str + \
            "\n**Speed:** {:.2f} MB/s".format(speed / 1024 / 1024) + \
            "\n**ETA:** {:.2f} s".format(time_to_completion / 1000)
        
        try:
            await status_msg.edit(f"**Processing...**\n{tmp}")
        except:
            pass

# --- Helper: TeraBox Direct Link Generator ---
def get_terabox_direct_link(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Cookie": "browserid=1; lang=en;" 
    }
    try:
        req = requests.get(url, headers=headers)
        return req.url 
    except:
        return None

# --- Feature: TeraBox Downloader ---
@bot.on_message(filters.regex(r"terabox\.com|1024tera\.com"))
async def terabox_handler(client, message):
    url = message.text.strip()
    status_msg = await message.reply("🔎 **Processing TeraBox Link...**\nPlease wait, this can take time.")

    try:
        # 1. Download to Server
        direct_link = get_terabox_direct_link(url)
        if not direct_link:
            return await status_msg.edit("❌ Failed to get direct link from TeraBox.")

        file_path = f"downloads/terabox_{int(time.time())}.mp4"
        await status_msg.edit(f"⬇️ **Downloading to Server...**\n(This consumes server bandwidth)")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(direct_link) as resp:
                if resp.status != 200:
                    return await status_msg.edit("❌ TeraBox refused connection.")
                with open(file_path, 'wb') as f:
                    while True:
                        chunk = await resp.content.read(1024*1024)
                        if not chunk: break
                        f.write(chunk)
        
        # 2. Upload to Telegram
        await status_msg.edit("⬆️ **Uploading to Telegram Cloud...**")
        start_time = time.time()
        
        log_msg = await client.send_document(
            Config.CHANNEL_ID,
            document=file_path,
            caption=f"Source: {url}",
            progress=progress_bar,
            progress_args=(status_msg, start_time)
        )
        
        await add_file(log_msg) # Index
        os.remove(file_path) # Cleanup
        
        stream_link = f"{Config.BASE_URL}/watch/{log_msg.id}"
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Fast Download", url=stream_link)],
            [InlineKeyboardButton("📺 Watch Online", url=stream_link)]
        ])
        
        await status_msg.edit(
            f"✅ **TeraBox Uploaded!**\n\n**File:** `{log_msg.document.file_name}`\n**Size:** {log_msg.document.file_size}",
            reply_markup=btn
        )

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** {e}")
        if os.path.exists(file_path):
            os.remove(file_path)

# --- Feature: Search & Index ---
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
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Fast Download", url=stream_link)],
            [InlineKeyboardButton("🗑 Delete (30m)", callback_data=f"del_msg")]
        ])
        sent_msg = await message.reply_text(
            f"🎬 **File Found:**\n`{file['file_name']}`\n\n🔗 [Fast Link]({stream_link})",
            reply_markup=btn
        )
        asyncio.create_task(auto_delete(sent_msg, 1800))

    if not found:
        await message.reply("❌ No files found.")

async def auto_delete(msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass

# --- Feature: Broadcast ---
@bot.on_message(filters.command("broadcast") & filters.user(Config.OWNER_ID))
async def broadcast_handler(client, message):
    if not message.reply_to_message:
        return await message.reply("Please reply to a message to broadcast it.")
    
    msg = await message.reply("📢 **Starting Broadcast...**")
    users = await get_all_users()
    
    sent = 0
    failed = 0
    async for user in users:
        try:
            await message.reply_to_message.copy(chat_id=user['user_id'])
            sent += 1
        except errors.FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_to_message.copy(chat_id=user['user_id'])
            sent += 1
        except Exception:
            failed += 1
            
    await msg.edit(f"✅ **Broadcast Complete!**\n\nSent: {sent}\nFailed: {failed}")

# --- Feature: Welcome Message (DEBUG MODE) ---
# I have replaced the old handler with this secure one.
@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    print(f"DEBUG: Start command received from {message.from_user.id}")

    # 1. Try to Save User (Catch Error if DB fails)
    try:
        await add_user(message.from_user.id)
    except Exception as e:
        print(f"DEBUG: Database Error: {e}")

    # 2. Define Content
    LIVE_IMG = "https://files.catbox.moe/maft7d.jpg"
    welcome_text = (
        f"👋 **Hello {message.from_user.mention}!**\n\n"
        f"🟢 **Bot Status:** `Online & High Speed`\n"
        f"I am your advanced **File Manager & Stream Bot**. Here is what I can do:\n\n"
        f"🚀 **Fast Speed:** I convert Telegram files into **Direct High-Speed Download Links**.\n\n"
        f"🔎 **Instant Search:** Type `/search Name` to find any movie.\n\n"
        f"📥 **External Downloader:** Send me a **TeraBox** link to download it.\n\n"
        f"✏️ **Smart Rename:** Add `?name=NewName.mkv` to your download link.\n\n"
        f"⏱ **Auto-Delete:** Search results delete after 30 mins.\n\n"
        f"📺 **Streaming:** Watch videos directly in your browser."
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Me to Your Group", url=f"http://t.me/{client.me.username}?startgroup=true"),
            InlineKeyboardButton("📢 Updates Channel", url="https://t.me/YourChannelLink")
        ],
        [
            InlineKeyboardButton("🆘 Support", url="https://t.me/YourUserName"),
            InlineKeyboardButton("🔎 Search Mode", switch_inline_query_current_chat="")
        ]
    ])

    # 3. Try to Send Photo (Fallback to text if Image fails)
    try:
        await client.send_photo(
            chat_id=message.chat.id,
            photo=LIVE_IMG,
            caption=welcome_text,
            reply_markup=buttons
        )
    except Exception as e:
        print(f"DEBUG: Image Failed: {e}")
        # Send Text Only if Image Fails
        await client.send_message(
            chat_id=message.chat.id,
            text=f"⚠️ **Image Error (Bot is Online):**\n\n{welcome_text}",
            reply_markup=buttons
        )

# --- Start Bot & Web Server ---
if __name__ == "__main__":
    print("Bot Starting on Port 8080...")
    Config.PORT = 8080 
    bot.loop.run_until_complete(web_server(bot))
    bot.run()
