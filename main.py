import logging
import yt_dlp
import os
import threading
import uuid
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
TOKEN = os.getenv("BOT_TOKEN")
# Get the external URL of your app (Render provides this automatically)
# If running locally, you might need to use 'http://localhost:8080'
APP_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8080")

# In-memory storage for generated links (restarts will clear this)
# Structure: { "uuid": "direct_video_url" }
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
                direct_url = STORED_VIDEOS[video_id]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                # HTML Template with HLS.js support for streaming links
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Video Stream</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
                    <style>
                        body {{ margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; }}
                        video {{ width: 100%; max-width: 1000px; height: auto; max-height: 100vh; }}
                        .btn {{ position: fixed; top: 20px; left: 20px; padding: 10px 20px; background: #fff; text-decoration: none; color: #000; border-radius: 5px; font-family: sans-serif; opacity: 0.7; }}
                    </style>
                </head>
                <body>
                    <a href="{direct_url}" class="btn">Download Raw File</a>
                    <video id="video" controls autoplay></video>
                    <script>
                        var video = document.getElementById('video');
                        var videoSrc = "{direct_url}";
                        
                        // Check if it's HLS (m3u8) or standard MP4
                        if (Hls.isSupported() && (videoSrc.includes('.m3u8') || !videoSrc.includes('.mp4'))) {{
                            var hls = new Hls();
                            hls.loadSource(videoSrc);
                            hls.attachMedia(video);
                        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                            // Native HLS support (Safari)
                            video.src = videoSrc;
                        }} else {{
                            // Standard MP4
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
    # ThreadingHTTPServer handles multiple requests better, but HTTPServer is standard
    server = HTTPServer(('0.0.0.0', port), StreamingRequestHandler)
    logging.info(f"Web server running on port {port}")
    server.serve_forever()

# --- BOT LOGIC ---
async def convert_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_url = update.message.text
    
    if not user_url.startswith(('http://', 'https://')):
        await update.message.reply_text("Please send a valid HTTP/HTTPS link.")
        return

    status_msg = await update.message.reply_text(f"🔍 **Analyzing:** {user_url}\n⏳ Please wait...", parse_mode='Markdown')

    try:
        # Options to grab the direct stream URL
        ydl_opts = {
            'format': 'best', 
            'quiet': True,
            'noplaylist': True,
            # Force generic extractor if specific one fails, useful for unknown streaming sites
            'force_generic_extractor': False 
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info
            info = ydl.extract_info(user_url, download=False)
            
            direct_url = info.get('url', None)
            title = info.get('title', 'Unknown Title')
            
            if direct_url:
                # 1. Generate a unique ID for this video
                unique_id = str(uuid.uuid4())[:8] # Short 8-char ID
                
                # 2. Store the direct link in our memory
                STORED_VIDEOS[unique_id] = direct_url
                
                # 3. Create the HTML link pointing to OUR bot's server
                # Ensure APP_URL doesn't have a trailing slash
                base_url = APP_URL.rstrip('/')
                watch_link = f"{base_url}/watch?id={unique_id}"

                message = (
                    f"✅ **Stream Converted!**\n\n"
                    f"🎬 **Title:** {title}\n"
                    f"🔗 **HTML Stream Link:**\n{watch_link}\n\n"
                    f"_(Click the link above to watch in browser)_"
                )
                
                # Edit the previous "Please wait" message
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=message, parse_mode='Markdown')
            else:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Could not extract a stream URL.")

    except Exception as e:
        logging.error(f"Error: {e}")
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Failed. The link might be protected or unsupported.")

if __name__ == '__main__':
    # 1. Start Web Server
    threading.Thread(target=start_web_server, daemon=True).start()

    # 2. Start Bot
    application = ApplicationBuilder().token(TOKEN).build()
    link_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), convert_link)
    application.add_handler(link_handler)

    print("Bot is running...")
    application.run_polling()
