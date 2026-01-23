import logging
import sqlite3
import datetime
import pytz
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
from telegram.error import BadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION ---
TOKEN = '7123456789:ABC-DefGhIjKlMnOpQrStUvWxYz'  # REPLACE THIS
ADMIN_ID = 123456789           # REPLACE WITH YOUR NUMERIC ID
IST = pytz.timezone('Asia/Kolkata')
PORT = 8080

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- WEB SERVER FOR PORT 8080 (HEALTH CHECK) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running successfully created by RETOUCH")

def start_web_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    logger.info(f"Web server started on port {PORT}")
    server.serve_forever()

# --- STATES FOR CONVERSATION HANDLERS ---
(
    ADD_CAT_NAME,
    ADD_CHAN_CAT, ADD_CHAN_NAME, ADD_CHAN_LINK, ADD_CHAN_PRICE, ADD_CHAN_GROUP_ID,
    SET_UPI, SET_PAYPAL,
    BROADCAST_SELECT_TYPE, BROADCAST_CONTENT, BROADCAST_DATETIME, BROADCAST_TARGETS,
    USER_UPLOAD_SCREENSHOT
) = range(13)

# --- DATABASE SETUP ---
def setup_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    # Categories
    c.execute('''CREATE TABLE IF NOT EXISTS categories 
                 (id INTEGER PRIMARY KEY, name TEXT)''')
    # Channels/Groups (Products)
    c.execute('''CREATE TABLE IF NOT EXISTS channels 
                 (id INTEGER PRIMARY KEY, category_id INTEGER, name TEXT, 
                  invite_link TEXT, price TEXT, channel_id TEXT)''')
    # Payment Settings
    c.execute('''CREATE TABLE IF NOT EXISTS payment_settings 
                 (id INTEGER PRIMARY KEY, upi_id TEXT, paypal_link TEXT)''')
    # Pending Payments
    c.execute('''CREATE TABLE IF NOT EXISTS pending_payments 
                 (user_id INTEGER, channel_db_id INTEGER, timestamp TEXT)''')
    # Subscriptions (Active Members)
    c.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                 (user_id INTEGER, channel_db_id INTEGER, join_date TEXT, 
                  expiry_date TEXT, channel_chat_id TEXT)''')
    # Broadcast Channels (List of channels admin can broadcast to)
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_channels 
                 (id INTEGER PRIMARY KEY, name TEXT, chat_id TEXT)''')
    
    # Initialize settings if empty
    c.execute("SELECT * FROM payment_settings")
    if not c.fetchone():
        c.execute("INSERT INTO payment_settings (upi_id, paypal_link) VALUES (?, ?)", 
                  ("not_set@upi", "paypal.me/notset"))
    
    conn.commit()
    conn.close()

setup_db()

# --- HELPER FUNCTIONS ---
def get_db():
    return sqlite3.connect('bot_data.db')

def is_admin(user_id):
    return user_id == ADMIN_ID

# --- ADMIN PANEL HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user.id):
        keyboard = [
            [InlineKeyboardButton("➕ Add Category", callback_data='admin_add_cat'),
             InlineKeyboardButton("➕ Add Channel/Group", callback_data='admin_add_chan')],
            [InlineKeyboardButton("💰 Set Payment Info", callback_data='admin_set_pay'),
             InlineKeyboardButton("📢 Setup Broadcast", callback_data='admin_broadcast')],
            [InlineKeyboardButton("➕ Add Broadcast Channel", callback_data='admin_add_bc_chan'),
             InlineKeyboardButton("🚫 Manage Expired", callback_data='admin_manage_expire')],
            [InlineKeyboardButton("👀 View Stats", callback_data='admin_stats')]
        ]
        await update.message.reply_text(
            "👑 **Admin Dashboard**\nSelect an option to customize your bot.\n\n🤖 **BOT created by RETOUCH**", 
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
        )
    else:
        # User View
        await user_show_categories(update, context)

# --- USER FLOW: SHOW CATEGORIES & CHANNELS ---

async def user_show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM categories")
    cats = c.fetchall()
    conn.close()

    keyboard = []
    for cat in cats:
        keyboard.append([InlineKeyboardButton(f"📂 {cat[1]}", callback_data=f"view_cat_{cat[0]}")])
    
    # ADDED BRANDING HERE
    text = "👋 Welcome! Please select a category to view our plans:\n\n🤖 **BOT created by RETOUCH**"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def user_show_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split('_')[2])
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE category_id=?", (cat_id,))
    chans = c.fetchall()
    conn.close()

    keyboard = []
    for chan in chans:
        # chan: id, cat_id, name, link, price, chan_id
        keyboard.append([InlineKeyboardButton(f"{chan[2]} - {chan[4]}", callback_data=f"buy_{chan[0]}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="user_home")])
    await query.message.edit_text("👇 Select a plan/group to join:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- PAYMENT FLOW ---

async def show_payment_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chan_db_id = int(query.data.split('_')[1])
    
    # Save selection to context
    context.user_data['selected_channel_id'] = chan_db_id

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT upi_id, paypal_link FROM payment_settings")
    settings = c.fetchone()
    c.execute("SELECT name, price FROM channels WHERE id=?", (chan_db_id,))
    channel_info = c.fetchone()
    conn.close()

    text = (f"💳 **Payment Gateway**\n\n"
            f"**Plan:** {channel_info[0]}\n"
            f"**Amount:** {channel_info[1]}\n\n"
            f"**Option 1: UPI**\n`{settings[0]}`\n\n"
            f"**Option 2: PayPal**\n{settings[1]}\n\n"
            f"⚠️ **Instructions:**\n1. Make the payment.\n2. Take a screenshot.\n3. Click the button below to upload.")

    keyboard = [[InlineKeyboardButton("📸 Upload Screenshot", callback_data="req_upload_ss")],
                [InlineKeyboardButton("🔙 Cancel", callback_data="user_home")]]
    
    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def request_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("📤 Please send your payment screenshot now.")
    return USER_UPLOAD_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Please send a photo.")
        return USER_UPLOAD_SCREENSHOT
    
    user = update.effective_user
    photo_file_id = update.message.photo[-1].file_id
    selected_chan_id = context.user_data.get('selected_channel_id')

    if not selected_chan_id:
        await update.message.reply_text("Session expired. Please start over /start")
        return ConversationHandler.END

    # Notify Admin
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, price FROM channels WHERE id=?", (selected_chan_id,))
    chan_info = c.fetchone()
    conn.close()

    keyboard = [
        [InlineKeyboardButton("✅ Accept", callback_data=f"appr_{user.id}_{selected_chan_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}")]
    ]
    
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_file_id,
        caption=(f"🔔 **New Payment Verification**\n\n"
                 f"**User:** {user.first_name} (@{user.username})\n"
                 f"**ID:** `{user.id}`\n"
                 f"**Plan:** {chan_info[0]}\n"
                 f"**Price:** {chan_info[1]}"),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await update.message.reply_text("✅ Screenshot sent to Admin for approval. You will be notified shortly.")
    return ConversationHandler.END

# --- ADMIN APPROVAL LOGIC ---

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    action = data[0]
    user_id = int(data[1])

    if action == 'rej':
        await context.bot.send_message(user_id, "❌ **Payment Rejected**\n\nYour payment screenshot was not approved by the admin.")
        await query.message.edit_caption(caption=query.message.caption + "\n\n🔴 **REJECTED**")
    
    elif action == 'appr':
        chan_db_id = int(data[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM channels WHERE id=?", (chan_db_id,))
        channel = c.fetchone() # id, cat, name, link, price, chat_id
        
        # Calculate Expiry (Example: 30 days default, Admin can logic this better if needed)
        now = datetime.datetime.now(IST)
        expiry_date = now + datetime.timedelta(days=30)
        expiry_str = expiry_date.strftime("%Y-%m-%d %H:%M")
        join_str = now.strftime("%Y-%m-%d")

        # Add to Subscriptions
        c.execute("DELETE FROM subscriptions WHERE user_id=? AND channel_db_id=?", (user_id, chan_db_id))
        c.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?)", 
                  (user_id, chan_db_id, join_str, expiry_str, channel[5]))
        conn.commit()
        conn.close()

        # Generate Digital Bill
        user_info = await context.bot.get_chat(user_id)
        bill_text = (
            f"🧾 **PAYMENT ACCEPTED & DIGITAL BILL**\n"
            f"-----------------------------------\n"
            f"**Channel:** {channel[2]}\n"
            f"**Date Joined:** {join_str}\n"
            f"**Username:** @{user_info.username}\n"
            f"**User ID:** {user_id}\n"
            f"**Expiry Date:** {expiry_str}\n"
            f"-----------------------------------\n"
            f"🎉 **Welcome Message:**\nWelcome to the premium group! Please follow the rules.\n\n"
            f"🔗 **JOIN LINK:** {channel[3]}\n\n"
            f"🤖 **BOT created by RETOUCH**"
        )

        await context.bot.send_message(user_id, bill_text, parse_mode='Markdown')
        await query.message.edit_caption(caption=query.message.caption + "\n\n🟢 **ACCEPTED**")

# --- ADMIN CONFIGURATION CONVERSATIONS ---

# 1. Add Category
async def add_cat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("Enter name for the new Category:")
    return ADD_CAT_NAME

async def add_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Category '{name}' added.")
    return ConversationHandler.END

# 2. Add Channel
async def add_chan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fetch categories to show ID
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM categories")
    cats = c.fetchall()
    conn.close()
    
    msg = "Available Categories:\n" + "\n".join([f"ID: {c[0]} | Name: {c[1]}" for c in cats])
    await update.callback_query.message.reply_text(f"{msg}\n\nEnter CATEGORY ID for this channel:")
    return ADD_CHAN_CAT

async def add_chan_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_cat'] = update.message.text
    await update.message.reply_text("Enter Channel Display Name:")
    return ADD_CHAN_NAME

async def add_chan_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_name'] = update.message.text
    await update.message.reply_text("Enter Invite Link:")
    return ADD_CHAN_LINK

async def add_chan_link_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_link'] = update.message.text
    await update.message.reply_text("Enter Price (e.g., '₹500' or '$10'):")
    return ADD_CHAN_PRICE

async def add_chan_price_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_price'] = update.message.text
    await update.message.reply_text("Enter Channel/Group Telegram ID (e.g., -100123456789) for auto-kick:")
    return ADD_CHAN_GROUP_ID

async def add_chan_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = update.message.text
    d = context.user_data
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO channels (category_id, name, invite_link, price, channel_id) VALUES (?, ?, ?, ?, ?)",
              (d['new_chan_cat'], d['new_chan_name'], d['new_chan_link'], d['new_chan_price'], gid))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Channel added successfully.")
    return ConversationHandler.END

# 3. Add Broadcast Channel
async def add_bc_chan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("Enter Format: `Name|ChatID` (e.g. My Channel|-100123456)")
    return 1 # Reuse a simple state or define new

async def add_bc_chan_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name, chat_id = update.message.text.split('|')
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO broadcast_channels (name, chat_id) VALUES (?, ?)", (name.strip(), chat_id.strip()))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Broadcast channel saved.")
    except:
        await update.message.reply_text("❌ Error. Use format: Name|ChatID")
    return ConversationHandler.END

# --- BROADCAST SYSTEM ---

async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("To Bot Users", callback_data="bd_type_bot"),
         InlineKeyboardButton("To Channels", callback_data="bd_type_chan")]
    ]
    await update.callback_query.message.reply_text("📣 Select Broadcast Type:", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROADCAST_SELECT_TYPE

async def broadcast_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['bd_type'] = query.data
    
    if query.data == 'bd_type_chan':
        # Show list of channels
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM broadcast_channels")
        chans = c.fetchall()
        conn.close()
        if not chans:
            await query.message.reply_text("No broadcast channels set.")
            return ConversationHandler.END
        
        # Simple selection: Ask user to type ID (simplification for script length)
        txt = "Available Channels:\n" + "\n".join([f"ID: {c[0]} | Name: {c[1]}" for c in chans])
        await query.message.reply_text(f"{txt}\n\nEnter the ID of the channel to broadcast to:")
        return BROADCAST_TARGETS
    else:
        await query.message.reply_text("Enter the message/post (Text, Photo, or Video) to broadcast:")
        return BROADCAST_CONTENT

async def broadcast_target_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bd_target_id'] = update.message.text
    await update.message.reply_text("Enter the message/post (Text, Photo, or Video) to broadcast:")
    return BROADCAST_CONTENT

async def broadcast_content_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Store message ID and Chat ID to copy later
    context.user_data['bd_msg_id'] = update.message.message_id
    context.user_data['bd_from_chat'] = update.message.chat_id
    
    await update.message.reply_text("Enter Schedule Date/Time (IST)\nFormat: `YYYY-MM-DD HH:MM`\nExample: 2023-10-25 14:30")
    return BROADCAST_DATETIME

async def broadcast_schedule_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_str = update.message.text
    try:
        # Parse Time
        local_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        local_dt = IST.localize(local_dt)
        
        # Schedule Job
        context.job_queue.run_once(
            perform_broadcast, 
            local_dt, 
            data=context.user_data.copy(),
            name=f"bd_{datetime.datetime.now()}"
        )
        await update.message.reply_text(f"✅ Broadcast scheduled for {date_str} IST.")
    except ValueError:
        await update.message.reply_text("❌ Invalid Format. Try again.")
        return BROADCAST_DATETIME
    return ConversationHandler.END

async def perform_broadcast(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    msg_id = data['bd_msg_id']
    from_chat = data['bd_from_chat']
    bd_type = data['bd_type']

    try:
        if bd_type == 'bd_type_bot':
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT DISTINCT user_id FROM subscriptions") # Assuming users in sub table
            users = c.fetchall()
            conn.close()
            for u in users:
                try:
                    await context.bot.copy_message(chat_id=u[0], from_chat_id=from_chat, message_id=msg_id)
                except:
                    pass
        elif bd_type == 'bd_type_chan':
            target_db_id = data['bd_target_id']
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT chat_id FROM broadcast_channels WHERE id=?", (target_db_id,))
            res = c.fetchone()
            conn.close()
            if res:
                await context.bot.copy_message(chat_id=res[0], from_chat_id=from_chat, message_id=msg_id)
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

# --- EXPIRY CHECKER SYSTEM ---

async def check_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    """Run periodically to kick expired members"""
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    
    # Select expired subs
    c.execute("SELECT user_id, channel_chat_id, rowid FROM subscriptions WHERE expiry_date < ?", (now_str,))
    expired = c.fetchall()
    
    for item in expired:
        user_id, chat_id, row_id = item
        try:
            # Kick User
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id) # Unban so they can rejoin if they pay again
            
            # Notify User
            await context.bot.send_message(user_id, "⚠️ **Membership Expired**\nYour subscription has ended and you have been removed from the channel.")
            
            # Remove from DB
            c.execute("DELETE FROM subscriptions WHERE rowid=?", (row_id,))
            conn.commit()
        except BadRequest as e:
            logger.error(f"Failed to kick user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error processing expiry: {e}")
    
    conn.close()

# --- MAIN SETUP ---

def main():
    # Start Dummy Web Server for Port 8080 (For hosting health checks)
    threading.Thread(target=start_web_server, daemon=True).start()

    application = Application.builder().token(TOKEN).build()
    
    # Job Queue for Auto-Kick and Broadcasts
    job_queue = application.job_queue
    # Run expiry check every hour
    job_queue.run_repeating(check_expiry_job, interval=3600, first=10)

    # Conversation: Add Category
    cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_cat_start, pattern='admin_add_cat')],
        states={ADD_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cat_save)]},
        fallbacks=[]
    )

    # Conversation: Add Channel
    chan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_chan_start, pattern='admin_add_chan')],
        states={
            ADD_CHAN_CAT: [MessageHandler(filters.TEXT, add_chan_cat_save)],
            ADD_CHAN_NAME: [MessageHandler(filters.TEXT, add_chan_name_save)],
            ADD_CHAN_LINK: [MessageHandler(filters.TEXT, add_chan_link_save)],
            ADD_CHAN_PRICE: [MessageHandler(filters.TEXT, add_chan_price_save)],
            ADD_CHAN_GROUP_ID: [MessageHandler(filters.TEXT, add_chan_final)],
        },
        fallbacks=[]
    )
    
    # Conversation: User Payment
    pay_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(request_screenshot, pattern='req_upload_ss')],
        states={USER_UPLOAD_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)]},
        fallbacks=[]
    )

    # Conversation: Broadcast
    bd_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_menu, pattern='admin_broadcast')],
        states={
            BROADCAST_SELECT_TYPE: [CallbackQueryHandler(broadcast_type_handler)],
            BROADCAST_TARGETS: [MessageHandler(filters.TEXT, broadcast_target_save)],
            BROADCAST_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_content_save)],
            BROADCAST_DATETIME: [MessageHandler(filters.TEXT, broadcast_schedule_final)]
        },
        fallbacks=[]
    )
    
    # Conversation: Add Broadcast Channel
    bc_chan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_bc_chan_start, pattern='admin_add_bc_chan')],
        states={1: [MessageHandler(filters.TEXT, add_bc_chan_save)]},
        fallbacks=[]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(cat_conv)
    application.add_handler(chan_conv)
    application.add_handler(pay_conv)
    application.add_handler(bd_conv)
    application.add_handler(bc_chan_conv)
    
    # Callback Handlers
    application.add_handler(CallbackQueryHandler(user_show_channels, pattern='^view_cat_'))
    application.add_handler(CallbackQueryHandler(show_payment_options, pattern='^buy_'))
    application.add_handler(CallbackQueryHandler(admin_decision, pattern='^(appr|rej)_'))
    application.add_handler(CallbackQueryHandler(start, pattern='user_home'))

    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
