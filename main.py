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

# In-memory storage
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
        
        # 1. Health Check
        if parsed_path.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Bot is running.')
            return

        # 2. Watch Route
        if parsed_path.path == "/watch":
            query_params = parse_qs(parsed_path.query)
            video_id = query_params.get('id', [None])[0]

            if video_id and video_id in STORED_VIDEOS:
                video_data = STORED_VIDEOS[video_id]
                direct_url = video_data['url']
                referer = video_data.get('referer', '') # Get original referer if needed

                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                # HTML with HLS.js and Custom Headers logic (simulated)
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Stream Player</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
                    <style>
                        body {{ margin: 0; background: #000; display: flex; flex-direction: column; justify-content: center; align-items: center; height: 100vh; color: #fff; font-family: sans-serif; }}
                        video {{ width: 100%; max-width: 1000px; height: auto; max-height: 80vh; box-shadow: 0 0 20px rgba(255,255,255,0.1); }}
                        .btn-container {{ margin-bottom: 20px; }}
                        .btn {{ padding: 10px 20px; background: #2196F3; text-decoration: none; color: #fff; border-radius: 5px; margin: 0 10px; }}
                    </style>
                </head>
                <body>
                    <div class="btn-container">
                        <a href="{direct_url}" class="btn">Download / Direct Link</a>
                    </div>
                    <video id="video" controls autoplay playsinline></video>
                    <script>
                        var video = document.getElementById('video');
                        var videoSrc = "{direct_url}";
                        
                        if (Hls.isSupported() && (videoSrc.includes('.m3u8') || !videoSrc.includes('.mp4'))) {{
                            var hls = new Hls();
                            hls.loadSource(videoSrc);
                            hls.attachMedia(video);
                            hls.on(Hls.Events.MANIFEST_PARSED, function() {{
                                video.play();
                            }});
                        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
                            video.src = videoSrc;
                            video.addEventListener('loadedmetadata', function() {{
                                video.play();
                            }});
                        }} else {{
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
    welcome_message = (
        "👋 **Hello! I am your Stream Converter Bot.**\n\n"
        "Send me any video link (YouTube, Hanime, TikTok, etc.), and I will generate "
        "a direct HTML streaming link for you.\n\n"
        "🚀 **Just paste a link to start!**"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def convert_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_url = update.message.text
    
    if not user_url.startswith(('http://', 'https://')):
        await update.message.reply_text("Please send a valid HTTP/HTTPS link.")
        return

    status_msg = await update.message.reply_text(f"🔍 **Analyzing:** {user_url}\nAttempting to bypass protections...", parse_mode='Markdown')

    try:
        # --- NEW ROBUST OPTIONS ---
        ydl_opts = {
            'format': 'best', 
            'quiet': True,
            'noplaylist': True,
            'nocheckcertificate': True, # Bypass SSL errors
            'geo_bypass': True,         # Try to bypass geo-restrictions
            # 1. Fake User Agent (Looks like Chrome on Windows)
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            # 2. Pass Referer (Some sites check this)
            'http_headers': {
                'Referer': user_url
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(user_url, download=False)
            
            direct_url = info.get('url', None)
            title = info.get('title', 'Unknown Title')
            
            if direct_url:
                unique_id = str(uuid.uuid4())[:8]
                
                # Store URL AND the referer (original link)
                STORED_VIDEOS[unique_id] = {
                    'url': direct_url,
                    'referer': user_url
                }
                
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
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ Extractor found no video URL.")

    except Exception as e:
        # Error Printing enabled for debugging
        error_text = str(e)
        logging.error(f"Error: {error_text}")
        
        # User-friendly error message
        final_msg = "❌ **Failed to Process Link**\n\n"
        if "HTTP Error 403" in error_text:
            final_msg += "Reason: **Access Denied (403)**. The site blocked the bot's IP."
        elif "geo" in error_text.lower():
            final_msg += "Reason: **Geo-Blocked**. Content not available in server region."
        else:
            final_msg += f"Reason: `{error_text[:100]}...`" # Show first 100 chars of error
            
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=final_msg, parse_mode='Markdown')

if __name__ == '__main__':
    threading.Thread(target=start_web_server, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Add Start Handler
    application.add_handler(CommandHandler("start", start))
    
    # Add Link Handler
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), convert_link))
    
    print("Bot is running...")
    application.run_polling()
