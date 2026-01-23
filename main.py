import logging
import yt_dlp
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN_HERE'  # Replace with your BotFather token

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def convert_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_url = update.message.text
    
    # Basic check to see if it looks like a URL
    if not user_url.startswith(('http://', 'https://')):
        await update.message.reply_text("Please send a valid HTTP/HTTPS link.")
        return

    await update.message.reply_text(f"Processing link: {user_url} \nPlease wait...")

    try:
        # yt-dlp options to extract information without downloading the file
        ydl_opts = {
            'format': 'best',  # Get best quality
            'quiet': True,     # Less terminal output
            'noplaylist': True # Download only single video, not playlists
        }

        # Extracting the direct link
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_url, download=False)
            
            # Get the direct download url from the info
            direct_url = info.get('url', None)
            title = info.get('title', 'Unknown Title')
            ext = info.get('ext', 'mp4')

            if direct_url:
                # Send the direct "supported" link back to the user
                message = (
                    f"✅ **Link Converted!**\n\n"
                    f"🎬 **Title:** {title}\n"
                    f"📥 **Direct Download:** [Click Here]({direct_url})"
                )
                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text("Could not extract a direct link from this URL.")

    except Exception as e:
        logging.error(f"Error processing link: {e}")
        await update.message.reply_text("❌ Failed to process this link. It might be unsupported or protected.")

if __name__ == '__main__':
    # Build the bot application
    application = ApplicationBuilder().token(TOKEN).build()

    # Handle text messages (assumed to be links)
    # filters.TEXT & ~filters.COMMAND ensures we don't catch commands like /start
    link_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), convert_link)
    
    application.add_handler(link_handler)

    print("Bot is running...")
    application.run_polling()
