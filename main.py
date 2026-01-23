import os
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
from telegram.error import BadRequest, Forbidden
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- CONFIGURATION ---
TOKEN = '8501324652:AAEE84y5ZCnkWjMayqvL9w3OB1tFaAHf6oY' 
ADMIN_ID = 8072674531 
IST = pytz.timezone('Asia/Kolkata')
PORT = 8080

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running successfully created by RETOUCH")

def start_web_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    logger.info(f"Web server started on port {PORT}")
    server.serve_forever()

# --- STATES ---
(
    ADD_CAT_NAME,
    ADD_CHAN_CAT, ADD_CHAN_NAME, ADD_CHAN_LINK, ADD_CHAN_PRICE, ADD_CHAN_DURATION, ADD_CHAN_GROUP_ID,
    PAY_CHOOSE, PAY_INPUT_UPI, PAY_INPUT_PAYPAL, # New Payment States
    BROADCAST_SELECT_TYPE, BROADCAST_CONTENT, BROADCAST_DATETIME, BROADCAST_TARGETS,
    USER_UPLOAD_SCREENSHOT,
    USER_CHAT_MODE,
    ADMIN_REPLY_MODE
) = range(17)

# --- DATABASE SETUP ---
def setup_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS categories 
                 (id INTEGER PRIMARY KEY, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels 
                 (id INTEGER PRIMARY KEY, category_id INTEGER, name TEXT, 
                  invite_link TEXT, price TEXT, channel_id TEXT, duration INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS payment_settings 
                 (id INTEGER PRIMARY KEY, upi_id TEXT, paypal_link TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                 (user_id INTEGER, channel_db_id INTEGER, join_date TEXT, 
                  expiry_date TEXT, channel_chat_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_channels 
                 (id INTEGER PRIMARY KEY, name TEXT, chat_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS all_users 
                 (user_id INTEGER PRIMARY KEY)''')
    
    c.execute("SELECT * FROM payment_settings")
    if not c.fetchone():
        c.execute("INSERT INTO payment_settings (upi_id, paypal_link) VALUES (?, ?)", 
                  ("not_set", "not_set"))
    conn.commit()
    conn.close()

setup_db()

# --- HELPER FUNCTIONS ---
def get_db():
    return sqlite3.connect('bot_data.db')

def is_admin(user_id):
    return user_id == ADMIN_ID

def save_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO all_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# --- START & ADMIN DASHBOARD ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id) 

    if is_admin(user.id):
        keyboard = [
            [InlineKeyboardButton("➕ Add Category", callback_data='admin_add_cat'),
             InlineKeyboardButton("➕ Add Channel/Group", callback_data='admin_add_chan')],
            [InlineKeyboardButton("💰 Set Payment Info", callback_data='admin_set_pay'),
             InlineKeyboardButton("📢 Setup Broadcast", callback_data='admin_broadcast')],
            [InlineKeyboardButton("➕ Add Broadcast Channel", callback_data='admin_add_bc_chan'),
             InlineKeyboardButton("🚫 Manage Expired", callback_data='admin_manage_expire')],
            [InlineKeyboardButton("👀 View Stats", callback_data='admin_stats'),
             InlineKeyboardButton("🗑 Manage / Delete Data", callback_data='admin_delete_menu')]
        ]
        text = "👑 **Admin Dashboard**\nSelect an option to customize your bot.\n\n🤖 **BOT created by RETOUCH**"
        
        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await user_show_categories(update, context)

# --- 1. ADD CATEGORY ---
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

# --- 2. ADD CHANNEL (FIXED ID ISSUE) ---
async def add_chan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM categories")
    cats = c.fetchall()
    conn.close()
    
    if not cats:
        await update.callback_query.message.reply_text("❌ No categories found. Add a category first.")
        return ConversationHandler.END

    msg = "Available Categories:\n" + "\n".join([f"ID: {c[0]} | Name: {c[1]}" for c in cats])
    await update.callback_query.message.reply_text(f"{msg}\n\n👇 **IMPORTANT:**\nEnter the **ID Number** of the category (e.g. 1):")
    return ADD_CHAN_CAT

async def add_chan_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_input = update.message.text
    if not text_input.isdigit():
        await update.message.reply_text("❌ Invalid ID. Please enter the **Number** only (e.g. 1). Try again:")
        return ADD_CHAN_CAT
        
    context.user_data['new_chan_cat'] = int(text_input)
    await update.message.reply_text("Enter Channel Display Name (e.g. VIP Plan):")
    return ADD_CHAN_NAME

async def add_chan_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_name'] = update.message.text
    await update.message.reply_text("Enter Invite Link:")
    return ADD_CHAN_LINK

async def add_chan_link_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_link'] = update.message.text
    await update.message.reply_text("Enter Price (e.g., '₹500'):")
    return ADD_CHAN_PRICE

async def add_chan_price_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_chan_price'] = update.message.text
    await update.message.reply_text("Enter **Duration in Days** (e.g., 30 for 1 month, 365 for 1 year):")
    return ADD_CHAN_DURATION

async def add_chan_duration_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['new_chan_duration'] = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number for days.")
        return ADD_CHAN_DURATION
        
    await update.message.reply_text("Enter Channel/Group Telegram ID (e.g., -100123456789) for auto-kick:")
    return ADD_CHAN_GROUP_ID

async def add_chan_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = update.message.text
    d = context.user_data
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO channels (category_id, name, invite_link, price, channel_id, duration) VALUES (?, ?, ?, ?, ?, ?)",
              (d['new_chan_cat'], d['new_chan_name'], d['new_chan_link'], d['new_chan_price'], gid, d['new_chan_duration']))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Channel/Plan added successfully.")
    return ConversationHandler.END

# --- 3. SET PAYMENT INFO (NEW SEPARATE BUTTONS) ---
async def set_pay_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇮🇳 Set UPI", callback_data='set_pay_upi_btn')],
        [InlineKeyboardButton("🅿️ Set PayPal", callback_data='set_pay_paypal_btn')],
        [InlineKeyboardButton("🔙 Back", callback_data='user_home')]
    ]
    await update.callback_query.message.edit_text("💰 **Payment Settings**\nSelect which method you want to configure:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return PAY_CHOOSE

async def set_pay_ask_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📝 Enter your **UPI ID**:")
    return PAY_INPUT_UPI

async def set_pay_save_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_upi = update.message.text
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE payment_settings SET upi_id=? WHERE id=1", (new_upi,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ UPI ID Updated!")
    return ConversationHandler.END

async def set_pay_ask_paypal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📝 Enter your **PayPal Link**:")
    return PAY_INPUT_PAYPAL

async def set_pay_save_paypal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_paypal = update.message.text
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE payment_settings SET paypal_link=? WHERE id=1", (new_paypal,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ PayPal Link Updated!")
    return ConversationHandler.END

# --- 4. BROADCAST SYSTEM ---
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
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM broadcast_channels")
        chans = c.fetchall()
        conn.close()
        if not chans:
            await query.message.reply_text("No broadcast channels set.")
            return ConversationHandler.END
        txt = "Available Channels:\n" + "\n".join([f"ID: {c[0]} | Name: {c[1]}" for c in chans])
        await query.message.reply_text(f"{txt}\n\nEnter the ID of the channel to broadcast to:")
        return BROADCAST_TARGETS
    else:
        await query.message.reply_text("Enter the message/post (Text, Photo, or Video):")
        return BROADCAST_CONTENT

async def broadcast_target_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bd_target_id'] = update.message.text
    await update.message.reply_text("Enter the message/post (Text, Photo, or Video):")
    return BROADCAST_CONTENT

async def broadcast_content_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bd_msg_id'] = update.message.message_id
    context.user_data['bd_from_chat'] = update.message.chat_id
    await update.message.reply_text("Enter Schedule Date/Time (12-Hour Format)\nFormat: `YYYY-MM-DD HH:MM AM/PM`\nExample: `2026-01-25 02:30 PM`")
    return BROADCAST_DATETIME

async def broadcast_schedule_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_str = update.message.text
    try:
        local_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %I:%M %p")
        local_dt = IST.localize(local_dt)
        
        context.job_queue.run_once(
            perform_broadcast, 
            local_dt, 
            data=context.user_data.copy(),
            name=f"bd_{datetime.datetime.now()}"
        )
        await update.message.reply_text(f"✅ Broadcast scheduled for {date_str}")
    except ValueError:
        await update.message.reply_text("❌ Invalid Format. Use `2026-01-25 02:30 PM`")
        return BROADCAST_DATETIME
    return ConversationHandler.END

async def perform_broadcast(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    msg_id = data['bd_msg_id']
    from_chat = data['bd_from_chat']
    bd_type = data['bd_type']

    try:
        conn = get_db()
        c = conn.cursor()
        
        if bd_type == 'bd_type_bot':
            c.execute("SELECT user_id FROM all_users")
            users = c.fetchall()
            for u in users:
                try:
                    await context.bot.copy_message(chat_id=u[0], from_chat_id=from_chat, message_id=msg_id)
                except (Forbidden, BadRequest):
                    pass 
                    
        elif bd_type == 'bd_type_chan':
            target_db_id = data['bd_target_id']
            c.execute("SELECT chat_id FROM broadcast_channels WHERE id=?", (target_db_id,))
            res = c.fetchone()
            if res:
                await context.bot.copy_message(chat_id=res[0], from_chat_id=from_chat, message_id=msg_id)
        
        conn.close()
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")

# --- 5. ADD BROADCAST CHANNEL ---
async def add_bc_chan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("Enter Format: `Name|ChatID` (e.g. News|-100123...)")
    return 1

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

# --- 6. DELETE / MANAGE DATA ---
async def admin_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🗑 Delete Categories", callback_data='del_menu_cats')],
        [InlineKeyboardButton("🗑 Delete Channels", callback_data='del_menu_chans')],
        [InlineKeyboardButton("🗑 Delete Broadcast Chans", callback_data='del_menu_bc')],
        [InlineKeyboardButton("🔄 Reset Payment Info", callback_data='del_reset_pay')],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data='user_home')]
    ]
    await update.callback_query.message.edit_text("🗑 **Delete Manager**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def delete_item_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = get_db()
    c = conn.cursor()
    keyboard = []
    
    if data == 'del_menu_cats':
        c.execute("SELECT * FROM categories")
        rows = c.fetchall()
        for r in rows:
            keyboard.append([InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"perform_del_cat_{r[0]}")])
            
    elif data == 'del_menu_chans':
        c.execute("SELECT * FROM channels")
        rows = c.fetchall()
        for r in rows:
            keyboard.append([InlineKeyboardButton(f"❌ {r[2]}", callback_data=f"perform_del_chan_{r[0]}")])
            
    elif data == 'del_menu_bc':
        c.execute("SELECT * FROM broadcast_channels")
        rows = c.fetchall()
        for r in rows:
            keyboard.append([InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"perform_del_bc_{r[0]}")])
            
    elif data == 'del_reset_pay':
        c.execute("UPDATE payment_settings SET upi_id='not_set', paypal_link='not_set' WHERE id=1")
        conn.commit()
        conn.close()
        await query.answer("Payment info reset!", show_alert=True)
        return

    conn.close()
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='admin_delete_menu')])
    await query.message.edit_text("Select item to delete:", reply_markup=InlineKeyboardMarkup(keyboard))

async def perform_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = get_db()
    c = conn.cursor()
    
    try:
        if data.startswith('perform_del_cat_'):
            oid = int(data.split('_')[-1])
            c.execute("DELETE FROM categories WHERE id=?", (oid,))
            c.execute("DELETE FROM channels WHERE category_id=?", (oid,))
            await query.answer("Deleted!", show_alert=True)
            await delete_item_selector(update._replace(callback_query=query._replace(data='del_menu_cats')), context)
            
        elif data.startswith('perform_del_chan_'):
            oid = int(data.split('_')[-1])
            c.execute("DELETE FROM channels WHERE id=?", (oid,))
            await query.answer("Deleted!", show_alert=True)
            await delete_item_selector(update._replace(callback_query=query._replace(data='del_menu_chans')), context)
            
        elif data.startswith('perform_del_bc_'):
            oid = int(data.split('_')[-1])
            c.execute("DELETE FROM broadcast_channels WHERE id=?", (oid,))
            await query.answer("Deleted!", show_alert=True)
            await delete_item_selector(update._replace(callback_query=query._replace(data='del_menu_bc')), context)
            
        conn.commit()
    finally:
        conn.close()

# --- 7. EXPIRY SYSTEM ---
async def admin_manage_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Running expiry check...", show_alert=True)
    await check_expiry_job(context)
    await update.callback_query.message.reply_text("✅ Expiry Check Done.")

async def check_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    
    c.execute("SELECT user_id, channel_chat_id, rowid FROM subscriptions WHERE expiry_date < ?", (now_str,))
    expired = c.fetchall()
    
    for item in expired:
        user_id, chat_id, row_id = item
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(user_id, "⚠️ **Membership Expired**")
            c.execute("DELETE FROM subscriptions WHERE rowid=?", (row_id,))
            conn.commit()
        except Exception:
            pass
    conn.close()

# --- 8. STATS ---
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT count(*) FROM categories")
    cats = c.fetchone()[0]
    c.execute("SELECT count(*) FROM channels")
    chans = c.fetchone()[0]
    c.execute("SELECT count(*) FROM all_users")
    users = c.fetchone()[0]
    conn.close()
    text = f"📊 **Stats**\n📂 Categories: {cats}\n📺 Plans: {chans}\n👥 Total Users: {users}"
    await update.callback_query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='user_home')]]))

# --- 9. USER CHAT ---
async def user_start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("❌ End Chat", callback_data='end_chat_mode')]]
    await query.message.edit_text("💬 **Chat with Admin**\nAllowed: Text & Photos Only.", reply_markup=InlineKeyboardMarkup(keyboard))
    return USER_CHAT_MODE

async def user_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    
    if msg.video or msg.animation or msg.document or msg.sticker:
        await msg.reply_text("❌ Videos/GIFs not allowed.")
        return USER_CHAT_MODE

    kb = [[InlineKeyboardButton("↩️ Reply", callback_data=f"adm_reply_{user.id}"), InlineKeyboardButton("❌ End Chat", callback_data="adm_end_chat")]]
    await context.bot.copy_message(chat_id=ADMIN_ID, from_chat_id=user.id, message_id=msg.message_id, caption=msg.caption, reply_markup=InlineKeyboardMarkup(kb))
    await msg.reply_text("✅ Sent.")
    return USER_CHAT_MODE

async def user_end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await user_show_categories(update, context)
    return ConversationHandler.END

# --- 10. ADMIN REPLY ---
async def admin_start_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target = int(query.data.split('_')[2])
    context.user_data['reply_target'] = target
    kb = [[InlineKeyboardButton("❌ End Chat", callback_data='adm_end_chat')]]
    await query.message.reply_text(f"Replying to `{target}`:", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_REPLY_MODE

async def admin_send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = context.user_data.get('reply_target')
    if target:
        await context.bot.copy_message(chat_id=target, from_chat_id=ADMIN_ID, message_id=update.message.message_id)
        await update.message.reply_text("✅ Sent.")
    return ADMIN_REPLY_MODE

async def admin_end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Chat Ended")
    await start(update, context) 
    return ConversationHandler.END

# --- USER STORE FLOW (FIXED) ---
async def user_show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM categories")
    cats = c.fetchall()
    conn.close()
    kb = []
    for cat in cats:
        kb.append([InlineKeyboardButton(f"📂 {cat[1]}", callback_data=f"view_cat_{cat[0]}")])
    kb.append([InlineKeyboardButton("📞 Chat with Admin", callback_data="start_user_chat")])
    
    text = "👋 Welcome! Select a category:\n\n🤖 **BOT created by RETOUCH**"
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def user_show_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split('_')[2])
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE category_id=?", (cat_id,))
    chans = c.fetchall()
    conn.close()
    kb = []
    for chan in chans:
        kb.append([InlineKeyboardButton(f"{chan[2]} - {chan[4]}", callback_data=f"buy_{chan[0]}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="user_home")])
    await query.message.edit_text("👇 Select a plan to join:", reply_markup=InlineKeyboardMarkup(kb))

# --- PAYMENT ---
async def show_payment_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chan_id = int(query.data.split('_')[1])
    context.user_data['selected_channel_id'] = chan_id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT upi_id, paypal_link FROM payment_settings")
    sets = c.fetchone()
    c.execute("SELECT name, price FROM channels WHERE id=?", (chan_id,))
    info = c.fetchone()
    conn.close()
    text = f"💳 **Plan:** {info[0]}\n**Price:** {info[1]}\n\nUPI: `{sets[0]}`\nPayPal: {sets[1]}"
    kb = [[InlineKeyboardButton("📸 Upload Screenshot", callback_data="req_upload_ss")], [InlineKeyboardButton("🔙 Cancel", callback_data="user_home")]]
    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def request_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("📤 Send screenshot now.")
    return USER_UPLOAD_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Photo only.")
        return USER_UPLOAD_SCREENSHOT
    
    user = update.effective_user
    chan_id = context.user_data.get('selected_channel_id')
    if not chan_id: return ConversationHandler.END
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name, price FROM channels WHERE id=?", (chan_id,))
    info = c.fetchone()
    conn.close()
    
    kb = [[InlineKeyboardButton("✅ Accept", callback_data=f"appr_{user.id}_{chan_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}")]]
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=f"User: {user.first_name}\nPlan: {info[0]}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Sent to Admin.")
    return ConversationHandler.END

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    action = data[0]
    uid = int(data[1])
    
    if action == 'rej':
        await context.bot.send_message(uid, "❌ Payment Rejected.")
        await query.message.edit_caption("🔴 REJECTED")
    elif action == 'appr':
        cid = int(data[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM channels WHERE id=?", (cid,))
        chan = c.fetchone() 
        
        duration_days = chan[6]
        now = datetime.datetime.now(IST)
        exp = now + datetime.timedelta(days=duration_days)
        exp_str = exp.strftime("%Y-%m-%d %H:%M")
        
        c.execute("INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?)", (uid, cid, now.strftime("%Y-%m-%d"), exp_str, chan[5]))
        conn.commit()
        conn.close()
        
        await context.bot.send_message(uid, f"✅ Accepted!\nPlan: {chan[2]}\nExpires: {exp_str}\n\nLink: {chan[3]}")
        await query.message.edit_caption("🟢 ACCEPTED")

# --- MAIN ---
def main():
    threading.Thread(target=start_web_server, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    application.job_queue.run_repeating(check_expiry_job, interval=3600, first=10)

    application.add_handler(CommandHandler("start", start))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_cat_start, pattern='admin_add_cat')],
        states={ADD_CAT_NAME: [MessageHandler(filters.TEXT, add_cat_save)]},
        fallbacks=[], allow_reentry=True))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_chan_start, pattern='admin_add_chan')],
        states={
            ADD_CHAN_CAT: [MessageHandler(filters.TEXT, add_chan_cat_save)],
            ADD_CHAN_NAME: [MessageHandler(filters.TEXT, add_chan_name_save)],
            ADD_CHAN_LINK: [MessageHandler(filters.TEXT, add_chan_link_save)],
            ADD_CHAN_PRICE: [MessageHandler(filters.TEXT, add_chan_price_save)],
            ADD_CHAN_DURATION: [MessageHandler(filters.TEXT, add_chan_duration_save)],
            ADD_CHAN_GROUP_ID: [MessageHandler(filters.TEXT, add_chan_final)],
        },
        fallbacks=[], allow_reentry=True))

    # Updated Payment Conversation
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(set_pay_menu, pattern='admin_set_pay')],
        states={
            PAY_CHOOSE: [
                CallbackQueryHandler(set_pay_ask_upi, pattern='set_pay_upi_btn'),
                CallbackQueryHandler(set_pay_ask_paypal, pattern='set_pay_paypal_btn')
            ],
            PAY_INPUT_UPI: [MessageHandler(filters.TEXT, set_pay_save_upi)],
            PAY_INPUT_PAYPAL: [MessageHandler(filters.TEXT, set_pay_save_paypal)],
        },
        fallbacks=[CallbackQueryHandler(start, pattern='user_home')], allow_reentry=True))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_menu, pattern='admin_broadcast')],
        states={
            BROADCAST_SELECT_TYPE: [CallbackQueryHandler(broadcast_type_handler)],
            BROADCAST_TARGETS: [MessageHandler(filters.TEXT, broadcast_target_save)],
            BROADCAST_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_content_save)],
            BROADCAST_DATETIME: [MessageHandler(filters.TEXT, broadcast_schedule_final)]
        },
        fallbacks=[], allow_reentry=True))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(add_bc_chan_start, pattern='admin_add_bc_chan')],
        states={1: [MessageHandler(filters.TEXT, add_bc_chan_save)]},
        fallbacks=[], allow_reentry=True))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(user_start_chat, pattern='start_user_chat')],
        states={USER_CHAT_MODE: [MessageHandler(filters.TEXT | filters.PHOTO, user_send_message), MessageHandler(filters.VIDEO, user_send_message)]},
        fallbacks=[CallbackQueryHandler(user_end_chat, pattern='end_chat_mode')], allow_reentry=True))

    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_start_reply, pattern='^adm_reply_')],
        states={ADMIN_REPLY_MODE: [MessageHandler(filters.TEXT | filters.PHOTO, admin_send_reply)]},
        fallbacks=[CallbackQueryHandler(admin_end_chat, pattern='adm_end_chat')], allow_reentry=True))
    
    application.add_handler(CallbackQueryHandler(pay_conv_entry, pattern='req_upload_ss')) 
    pay_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(request_screenshot, pattern='req_upload_ss')],
        states={USER_UPLOAD_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)]},
        fallbacks=[], allow_reentry=True
    )
    application.add_handler(pay_conv)

    application.add_handler(CallbackQueryHandler(user_show_channels, pattern='^view_cat_'))
    application.add_handler(CallbackQueryHandler(show_payment_options, pattern='^buy_'))
    application.add_handler(CallbackQueryHandler(admin_decision, pattern='^(appr|rej)_'))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern='admin_stats'))
    application.add_handler(CallbackQueryHandler(admin_manage_expire, pattern='admin_manage_expire'))
    application.add_handler(CallbackQueryHandler(admin_delete_menu, pattern='admin_delete_menu'))
    application.add_handler(CallbackQueryHandler(delete_item_selector, pattern='^(del_menu|del_reset)'))
    application.add_handler(CallbackQueryHandler(perform_delete, pattern='^perform_del'))
    application.add_handler(CallbackQueryHandler(start, pattern='user_home'))

    print("Bot is running...")
    application.run_polling()

async def pay_conv_entry(update, context):
    return await request_screenshot(update, context)

if __name__ == '__main__':
    main()
