import motor.motor_asyncio
from config import Config

client = motor.motor_asyncio.AsyncIOMotorClient(Config.DB_URL)
db = client['MyTelegramBot']
files_col = db['files']

async def add_file(msg):
    # Only index video or documents
    media = msg.video or msg.document
    if not media: return

    file_det = {
        'file_id': media.file_id,
        'file_name': media.file_name or "Unknown",
        'file_size': media.file_size,
        'caption': msg.caption or "No Caption",
        'msg_id': msg.id,
        'chat_id': Config.CHANNEL_ID
    }
    # Avoid duplicates
    await files_col.update_one({'file_id': media.file_id}, {'$set': file_det}, upsert=True)

async def search_files(query):
    # Regex search for the movie name
    return files_col.find({'file_name': {'$regex': query, '$options': 'i'}})

async def get_file_by_id(file_id):
    return await files_col.find_one({'file_id': file_id})
