import motor.motor_asyncio
from config import Config

# --- NUCLEAR FIX: Force Connection ---
# tlsAllowInvalidCertificates=True fixes the SSL Handshake error on Render
client = motor.motor_asyncio.AsyncIOMotorClient(
    Config.DB_URL,
    tls=True,
    tlsAllowInvalidCertificates=True
)
db = client['MyTelegramBot']

# Collections
files_col = db['files']
users_col = db['users']

async def add_file(msg):
    media = msg.video or msg.document or msg.audio
    if not media: return
    
    # Smart Name Detection
    filename = getattr(media, 'file_name', None)
    if not filename:
        filename = f"Video_{media.file_size}.mp4"

    file_det = {
        'file_id': media.file_id,
        'file_name': filename,
        'file_size': media.file_size,
        'caption': msg.caption or "",
        'msg_id': msg.id,
        'chat_id': Config.CHANNEL_ID
    }
    await files_col.update_one({'file_id': media.file_id}, {'$set': file_det}, upsert=True)

async def search_files(query):
    return files_col.find({'file_name': {'$regex': query, '$options': 'i'}})

async def get_file_by_id(file_id):
    return await files_col.find_one({'file_id': file_id})

async def add_user(user_id):
    await users_col.update_one({'user_id': user_id}, {'$set': {'user_id': user_id}}, upsert=True)

async def get_all_users():
    return users_col.find({})
