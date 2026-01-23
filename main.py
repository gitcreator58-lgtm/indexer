import logging
import yt_dlp
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
# We get the token from the Environment Variable (set in Render dashboard)
TOKEN = os.getenv("BOT_TOKEN")

# Check if token exists immediately to fail fast if it's missing
if not TOKEN:
    raise ValueError("No BOT_TOKEN found! Please add it in your Render Environment Variables.")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- WEB SERVER FOR HEALTH CHECKS ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running!')

def start_web_server():
    # Get port from environment variable or default to 8080
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logging.info(f"Web server running on port {port}")
    server.serve_forever()

# --- BOT LOGIC ---
async def convert_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_url = update.message.text
    
    if not user_url.startswith(('http://', 'https://')):
        await update.message.reply_text("Please send a valid HTTP/HTTPS link.")
        return

    await update.message.reply_text(f"Processing link: {user_url} \nPlease wait...")

    try:
        ydl_opts = {
            'format': 'best',
            'quiet': True,
            'noplaylist': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_url, download=False)
            
            direct_url = info.get('url', None)
            title = info.get('title', 'Unknown Title')

            if direct_url:
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
    # 1. Start the web server in a background thread
    threading.Thread(target=start_web_server, daemon=True).start()

    # 2. Start the Telegram Bot using the TOKEN we loaded at the top
    application = ApplicationBuilder().token(TOKEN).build()
    
    link_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), convert_link)
    application.add_handler(link_handler)

    print("Bot is polling...")
    application.run_polling()
