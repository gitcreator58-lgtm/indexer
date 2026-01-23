import logging
import yt_dlp
import os
import threading
import uuid
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8080")

# In-memory storage for generated links
STORED_VIDEOS = {}

if not TOKEN:
    raise ValueError("No BOT_TOKEN found! Please add it in your Environment Variables.")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- WEB SERVER (Serves the HTML Player) ---
class StreamingRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        # 1. Health Check Route (for Render)
        if parsed_path.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Bot is running and ready to stream!')
            return

        # 2. Watch Route (e.g. /watch?id=12345)
        if parsed_path.path == "/watch":
            query_params = parse_qs(parsed_path.query)
            video_id = query_params.get('id', [None])[0]

            if video_id and video_id in STORED_VIDEOS:
                video_data = STORED_VIDEOS[video_id]
                direct_url = video_data['url']

                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                # HTML Template with HLS.js support for streaming links
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Stream Player</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
                    <style>
                        body {{ margin: 0; background: #000; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100vh; color: #fff; font-family: sans-serif; }}
                        video {{ width: 100%; max-width: 1000px; height: auto; max-height: 80vh; }}
                        .btn {{ padding: 10px 20px; background: #2196F3; text-decoration: none; color: #fff; border-radius: 5px; margin-bottom: 20px; }}
                    </style>
                </head>
                <body>
                    <a href="{direct_url}" class="btn">Download / Direct Link</a>
                    <video id="video" controls autoplay playsinline></video>
                    <script>
                        var video = document.getElementById('video');
                        var videoSrc = "{direct_url}";
                        
                        // Check if it's HLS (m3u8) or standard MP4
                        if (Hls.isSupported() && (videoSrc.includes('.m3u8') || !videoSrc.includes('.mp4'))) {{
                            var hls = new Hls();
                            hls.loadSource(videoSrc);
                            hls.attachMedia(video);
                        }} else {{
                            // Standard MP4 or native HLS support
                            video.src = videoSrc;
                        }}
                    </script>
                </body>
                </html>
                """
                self.wfile.write(html_content.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'Video Link Expired or Not Found.')
            return

def start_web_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), StreamingRequestHandler)
    logging.info(f"Web server running on port {port}")
    server.serve_forever()

# --- BOT LOGIC ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the command /start is issued."""
    user = update.effective_user
    welcome_message = (
        f"👋 **Hello {user.first_name}!**\n\n"
        "I am a **Stream Converter Bot**. \n"
        "I can convert unsupported video links (like M3U8 streams) into a direct HTML player link.\n\n"
        "🚀 **How to use me:**\n"
        "Just send me a link from a supported site (YouTube, TikTok, Hanime, etc.) and wait for the magic!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def convert_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_url = update.message.text
    
    if not user_url.startswith(('http://', 'https://')):
        await update.message.reply_text("Please send a valid HTTP/HTTPS link.")
        return

    status_msg = await update.message.reply_text(f"🔍 **Analyzing:** {user_url}\nAttempting to extract stream...", parse_mode='Markdown')

    try:
        # Options to bypass protections and extract info
        ydl_opts = {
            'format': 'best', 
            'quiet': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'ignoreerrors': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'http_headers': {'Referer': user_url}
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(user_url, download=False)
            except Exception as extract_error:
                # Debug Mode: Show the exact error to the user
                error_str = str(extract_error)
                if len(error_str) > 2000: error_str = error_str[:2000]
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id, 
                    message_id=status_msg.message_id, 
                    text=f"❌ **Extraction Failed**\n\nTechnical Error:\n`{error_str}`", 
                    parse_mode='Markdown'
                )
                return

            if not info:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Extraction returned no data (NULL).")
                return

            direct_url = info.get('url', None)
            title = info.get('title', 'Unknown Title')
            
            if direct_url:
                unique_id = str(uuid.uuid4())[:8]
                STORED_VIDEOS[unique_id] = {'url': direct_url}
                
                base_url = APP_URL.rstrip('/')
                watch_link = f"{base_url}/watch?id={unique_id}"

                message = (
                    f"✅ **Stream Ready!**\n\n"
                    f"🎬 **Title:** {title}\n"
                    f"🔗 **Watch Online:**\n{watch_link}\n\n"
                    f"_(Link valid until bot restarts)_"
                )
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=message, parse_mode='Markdown')
            else:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Found video metadata, but no direct URL. (Likely DRM protected).")

    except Exception as e:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"❌ **Bot Error:**\n`{str(e)}`", parse_mode='Markdown')

if __name__ == '__main__':
    # 1. Start Web Server
    threading.Thread(target=start_web_server, daemon=True).start()

    # 2. Start Bot
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Register Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), convert_link))

    print("Bot is running...")
    application.run_polling()
