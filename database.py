import motor.motor_asyncio
import certifi
from config import Config

# --- Database Connection ---
# We add tlsCAFile=certifi.where() to fix the SSL Handshake Error
client = motor.motor_asyncio.AsyncIOMotorClient(
    Config.DB_URL,
    tlsCAFile=certifi.where()
)
db = client['MyTelegramBot']

# --- Collections ---
files_col = db['files']
users_col = db['users']

# --- File Indexing Functions ---
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
    # Avoid duplicates: Update if exists, Insert if new
    await files_col.update_one({'file_id': media.file_id}, {'$set': file_det}, upsert=True)

async def search_files(query):
    # Regex search for the movie name (Case insensitive)
    return files_col.find({'file_name': {'$regex': query, '$options': 'i'}})

async def get_file_by_id(file_id):
    return await files_col.find_one({'file_id': file_id})

# --- User Management Functions ---
async def add_user(user_id):
    # Save user to DB if they don't exist
    user_data = {'user_id': user_id}
    await users_col.update_one({'user_id': user_id}, {'$set': user_data}, upsert=True)

async def get_all_users():
    # Return a cursor to iterate over all users
    return users_col.find({})
