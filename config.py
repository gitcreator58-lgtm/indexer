import os

class Config:
    API_ID = int(os.environ.get("API_ID", "12345"))
    API_HASH = os.environ.get("API_HASH", "your_hash")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
    # MongoDB URL (Get free from MongoDB Atlas)
    DB_URL = os.environ.get("DB_URL", "mongodb+srv://...")
    # ID of the private channel to index
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100xxxxxxx"))
    # Your ID (to control the bot)
    OWNER_ID = int(os.environ.get("OWNER_ID", "12345"))
    # The public URL of your app (e.g., https://my-app.onrender.com)
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080")
    PORT = int(os.environ.get("PORT", "8080"))
