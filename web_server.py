from aiohttp import web
from config import Config
import time

routes = web.RouteTableDef()

# --- 1. Health Check Route (Essential for Render) ---
@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "running", "server_time": time.time()})

# --- 2. The Fast Download / Stream Route ---
@routes.get("/watch/{message_id}")
async def stream_handler(request):
    try:
        # Parse the Message ID from URL
        message_id = int(request.match_info['message_id'])
        
        # Access the bot instance stored in the app
        bot = request.app['bot']

        # Get the File Message from the Channel
        msg = await bot.get_messages(Config.CHANNEL_ID, message_id)
        media = msg.video or msg.document or msg.audio

        if not media:
            return web.Response(text="Error: File not found or has been deleted from channel.", status=404)

        # --- RENAMING LOGIC ---
        # Check if user added ?name=NewName.mp4 to the link
        custom_name = request.query.get('name')
        original_name = media.file_name or "Unknown_File"
        
        if custom_name:
            final_name = custom_name
        else:
            final_name = original_name

        # --- HEADERS ---
        # These headers tell the browser: "Download this, and name it X"
        headers = {
            'Content-Disposition': f'attachment; filename="{final_name}"',
            'Content-Length': str(media.file_size),
            'Content-Type': getattr(media, "mime_type", "application/octet-stream")
        }

        # --- STREAMING ---
        # Initialize the Stream Response
        resp = web.StreamResponse(status=200, headers=headers)
        await resp.prepare(request)

        # Download chunks from Telegram and instantly write them to the User
        # This acts as a bridge: Telegram -> Server -> User
        async for chunk in bot.download_media(msg, stream=True):
            await resp.write(chunk)
        
        return resp

    except Exception as e:
        # Log error to console for debugging
        print(f"Stream Error: {e}")
        return web.Response(text=f"Server Error: {e}", status=500)

# --- 3. Server Startup Function ---
async def web_server(bot):
    app = web.Application()
    app.add_routes(routes)
    app['bot'] = bot # Attach bot to app so routes can use it
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Listen on 0.0.0.0 so the outside world can access it
    # Port is taken from Config (set in your Render Dashboard)
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    print(f"Web Server Running on Port {Config.PORT}")
