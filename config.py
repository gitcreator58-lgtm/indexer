import os

class Config:
    # Get these from my.telegram.org
    API_ID = int(os.environ.get("API_ID", "12345"))
    API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
    
    # Get this from @BotFather
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token_here")
    
    # Database URL from MongoDB Atlas (make sure to use the srv string)
    DB_URL = os.environ.get("DB_URL", "mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority")
    
    # The ID of your Private Channel (Must start with -100)
    # Example: -1001234567890
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-100"))
    
    # Your Telegram User ID (Get from @RoseBot by typing /id)
    OWNER_ID = int(os.environ.get("OWNER_ID", "12345"))
    
    # The Public URL of your app on Render
    # IMPORTANT: Do NOT add a trailing slash at the end
    # Example: https://my-bot-app.onrender.com
    BASE_URL = os.environ.get("BASE_URL", "https://your-app-name.onrender.com")
    
    # Render automatically sets the PORT env var, but we default to 8080 just in case
    PORT = int(os.environ.get("PORT", "8080"))
