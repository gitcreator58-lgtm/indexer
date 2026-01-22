from aiohttp import web
from config import Config

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root(request):
    return web.json_response({"status": "running"})

@routes.get("/watch/{message_id}")
async def stream(request):
    try:
        message_id = int(request.match_info['message_id'])
        bot = request.app['bot']
        msg = await bot.get_messages(Config.CHANNEL_ID, message_id)
        media = msg.video or msg.document
        
        # RENAME LOGIC
        custom_name = request.query.get('name')
        final_name = custom_name if custom_name else (media.file_name or "video.mp4")
        
        headers = {
            'Content-Disposition': f'attachment; filename="{final_name}"',
            'Content-Length': str(media.file_size)
        }
        
        resp = web.StreamResponse(status=200, headers=headers)
        await resp.prepare(request)
        
        async for chunk in bot.download_media(msg, stream=True):
            await resp.write(chunk)
        return resp
    except:
        return web.Response(status=404)

async def web_server(bot):
    app = web.Application()
    app.add_routes(routes)
    app['bot'] = bot
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", Config.PORT).start()
