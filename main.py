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
TOKEN = '8362312218:AAE76YHbu2iHT3UE0QI-d2lDPOWmnHg5aQc' 
ADMIN_ID = 8072674531 
NOTIFICATION_GROUP_ID = -1001234567890 # <--- REPLACE WITH YOUR GROUP ID
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
    PAY_CHOOSE, PAY_INPUT_UPI, PAY_INPUT_PAYPAL,
    BROADCAST_SELECT_TYPE, BROADCAST_CONTENT, BROADCAST_DATETIME, BROADCAST_TARGETS, BROADCAST_BUTTONS,
    USER_UPLOAD_SCREENSHOT,
    USER_CHAT_MODE,
    ADMIN_REPLY_MODE,
    AIO_SET_LINKS, AIO_SET_PRICE, AIO_SET_DURATION,
    SET_NOTIFY_GROUP, SET_UPDATE_LINK, MANUAL_ADD_DETAILS
) = range(24)  # <--- FIXED THIS NUMBER TO 24

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
                  expiry_date TEXT, channel_chat_id TEXT, plan_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_channels 
                 (id INTEGER PRIMARY KEY, name TEXT, chat_id TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS all_users 
                 (user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS aio_settings
                 (id INTEGER PRIMARY KEY, links TEXT, price TEXT, duration INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_activity
                 (id INTEGER PRIMARY KEY, last_seen TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_chats
                 (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings
                 (id INTEGER PRIMARY KEY, notify_group_id TEXT, update_channel_link TEXT)''')
    
    c.execute("SELECT * FROM payment_settings")
    if not c.fetchone():
        c.execute("INSERT INTO payment_settings (upi_id, paypal_link) VALUES (?, ?)", ("not_set", "not_set"))

    c.execute("SELECT * FROM bot_settings")
    if not c.fetchone():
        c.execute("INSERT INTO bot_settings (notify_group_id, update_channel_link) VALUES (?, ?)", ("not_set", "not_set"))
    
    conn.commit()
    conn.close()

setup_db()

# --- HELPER FUNCTIONS ---
def get_db():
    return sqlite3.connect('bot_data.db')

def is_admin(user_id):
    return user_id == ADMIN_ID

def save_user(user):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO all_users (user_id, first_name, username) VALUES (?, ?, ?)", (user.id, user.first_name, user.username))
    conn.commit()
    conn.close()

def update_admin_activity():
    conn = get_db()
    c = conn.cursor()
    now = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR REPLACE INTO admin_activity (id, last_seen) VALUES (1, ?)", (now,))
    conn.commit()
    conn.close()

def is_admin_online():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_seen FROM admin_activity WHERE id=1")
    row = c.fetchone()
    conn.close()
    if not row: return False
    last_seen = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    last_seen = IST.localize(last_seen)
    now = datetime.datetime.now(IST)
    if (now - last_seen).total_seconds() < 600: return True
    return False

def set_active_chat(user_id, active=True):
    conn = get_db()
    c = conn.cursor()
    if active:
        c.execute("INSERT OR REPLACE INTO active_chats (user_id) VALUES (?)", (user_id,))
    else:
        c.execute("DELETE FROM active_chats WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_chat_active(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM active_chats WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res is not None

# --- START & MENUS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    
    if is_chat_active(user.id):
        set_active_chat(user.id, False)

    if is_admin(user.id):
        update_admin_activity()
        keyboard = [
            [InlineKeyboardButton("➕ Add Category", callback_data='admin_add_cat'),
             InlineKeyboardButton("➕ Add Channel/Plan", callback_data='admin_add_chan')],
            [InlineKeyboardButton("🌟 Set All-in-One Pack", callback_data='admin_set_aio')],
            [InlineKeyboardButton("💰 Set Payment Info", callback_data='admin_set_pay'),
             InlineKeyboardButton("📢 Setup Broadcast", callback_data='admin_broadcast')],
            [InlineKeyboardButton("🔔 Set Notify Group", callback_data='admin_set_group'),
             InlineKeyboardButton("📢 Set Updates Link", callback_data='admin_set_update')],
            [InlineKeyboardButton("➕ Add Broadcast Channel", callback_data='admin_add_bc_chan'),
             InlineKeyboardButton("🚫 Manage Expired", callback_data='admin_manage_expire')],
            [InlineKeyboardButton("👀 View Stats", callback_data='admin_stats'),
             InlineKeyboardButton("👥 View Members", callback_data='admin_view_members')],
            [InlineKeyboardButton("🗑 Manage / Delete Data", callback_data='admin_delete_menu')]
        ]
        text = "👑 **Admin Dashboard**\nSelect an option to customize your bot.\n\n🤖 **Powered by RETOUCH**"
        
        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        keyboard = [
            [InlineKeyboardButton("💎 Go Premium", callback_data='user_show_cats')],
            [InlineKeyboardButton("ℹ️ How to Use", callback_data='show_help'),
             InlineKeyboardButton("📞 Chat with Admin", callback_data='start_user_chat')]
        ]
        text = (
            "👋 **Welcome to Our Premium Store!**\n\n"
            "🚀 **Unlock Exclusive Content Today!**\n"
            "Click 'Go Premium' to see our plans.\n\n"
            "⚡ *Instant Access • Secure Payment • 24/7 Support*\n\n"
            "🤖 **Powered by RETOUCH**"
        )
        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- SETTINGS HANDLERS (GROUP & UPDATES) ---
async def admin_set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT notify_group_id FROM bot_settings WHERE id=1")
    current_gid = c.fetchone()[0]
    conn.close()

    text = (f"🔔 **Notification Group Settings**\n\n"
            f"🔹 **Current Group ID:** `{current_gid}`\n\n"
            f"👇 **To Set/Change:** Send the new Group ID (e.g. -100xxxx)\n"
            f"👇 **To Remove:** Click Delete below.")
    
    kb = [[InlineKeyboardButton("❌ Delete/Reset Group ID", callback_data='reset_notify_group')],
          [InlineKeyboardButton("🔙 Back", callback_data='user_home')]]
          
    await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return SET_NOTIFY_GROUP

async def save_notify_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gid = update.message.text
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE bot_settings SET notify_group_id=? WHERE id=1", (gid,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Notification Group set to: `{gid}`")
    return ConversationHandler.END

async def reset_notify_group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE bot_settings SET notify_group_id='not_set' WHERE id=1")
    conn.commit()
    conn.close()
    await update.callback_query.answer("Group ID Removed!", show_alert=True)
    await admin_set_group(update, context) # Refresh view
    return SET_NOTIFY_GROUP

async def admin_set_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("🔗 **Enter Updates Channel Link** (e.g., https://t.me/mychannel):")
    return SET_UPDATE_LINK

async def save_update_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE bot_settings SET update_channel_link=? WHERE id=1", (link,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Updates Link saved: {link}")
    return ConversationHandler.END

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

# --- 2. ADD CHANNEL ---
async def add_chan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM categories")
    cats = c.fetchall()
    conn.close()
    
    if not cats:
        await update.callback_query.message.reply_text("❌ No categories found. Add a category first.")
        return ConversationHandler.END

    kb = []
    row = []
    for cat in cats:
        row.append(InlineKeyboardButton(f"{cat[1]}", callback_data=str(cat[0])))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    await update.callback_query.message.reply_text("👇 **Select Category to add plan under:**", reply_markup=InlineKeyboardMarkup(kb))
    return ADD_CHAN_CAT

async def add_chan_cat_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_chan_cat'] = int(query.data)
    await query.message.reply_text("Enter Channel Display Name (e.g. VIP Plan):")
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
    await update.message.reply_text("Enter **Duration in Days** (e.g., 30):")
    return ADD_CHAN_DURATION

async def add_chan_duration_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['new_chan_duration'] = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Number only.")
        return ADD_CHAN_DURATION
    await update.message.reply_text("Enter Channel/Group Telegram ID (e.g., -100123...):")
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
    await update.message.reply_text("✅ Plan added successfully.")
    return ConversationHandler.END

# --- 3. ALL IN ONE ---
async def aio_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    await update.callback_query.message.reply_text("🌟 **All-in-One Setup**\nLinks (comma separated):")
    return AIO_SET_LINKS

async def aio_save_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['aio_links'] = update.message.text
    await update.message.reply_text("Enter Price:")
    return AIO_SET_PRICE

async def aio_save_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['aio_price'] = update.message.text
    await update.message.reply_text("Enter Duration (Days):")
    return AIO_SET_DURATION

async def aio_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dur = int(update.message.text)
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM aio_settings")
        c.execute("INSERT INTO aio_settings (links, price, duration) VALUES (?, ?, ?)", 
                  (context.user_data['aio_links'], context.user_data['aio_price'], dur))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ All-in-One Pack Set!")
    except:
        await update.message.reply_text("❌ Error.")
    return ConversationHandler.END

# --- 4. PAYMENT & MEMBERS ---
async def set_pay_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    keyboard = [
        [InlineKeyboardButton("🇮🇳 Set UPI", callback_data='set_pay_upi_btn')],
        [InlineKeyboardButton("🅿️ Set PayPal", callback_data='set_pay_paypal_btn')],
        [InlineKeyboardButton("🔙 Back", callback_data='user_home')]
    ]
    await update.callback_query.message.edit_text("💰 **Payment Settings**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return PAY_CHOOSE

async def set_pay_ask_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📝 Enter **UPI ID**:")
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
    await update.callback_query.message.reply_text("📝 Enter **PayPal Link**:")
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

async def admin_view_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT s.user_id, u.first_name, s.join_date, s.plan_name 
                 FROM subscriptions s 
                 LEFT JOIN all_users u ON s.user_id = u.user_id''')
    data = c.fetchall()
    conn.close()
    if not data:
        await update.callback_query.message.edit_text("Empty list.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='user_home')]]))
        return
    msg = "👥 **Paid Members List:**\n\n"
    for row in data:
        msg += f"👤 {row[1]} (`{row[0]}`)\n📅 {row[2]} | 📦 {row[3]}\n\n"
    if len(msg) > 4000: msg = msg[:4000] + "\n...(truncated)"
    await update.callback_query.message.edit_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='user_home')]]))

# --- 5. BROADCAST ---
async def broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    keyboard = [[InlineKeyboardButton("To Bot Users", callback_data="bd_type_bot"), InlineKeyboardButton("To Channels", callback_data="bd_type_chan")]]
    await update.callback_query.message.reply_text("📣 Select Type:", reply_markup=InlineKeyboardMarkup(keyboard))
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
            await query.message.reply_text("No broadcast channels saved. Go back and add one.")
            return ConversationHandler.END
            
        kb = []
        for ch in chans:
            kb.append([InlineKeyboardButton(f"📢 {ch[1]}", callback_data=f"bd_sel_{ch[0]}")])
        
        await query.message.reply_text("👇 **Select a Channel to Broadcast:**", reply_markup=InlineKeyboardMarkup(kb))
        return BROADCAST_TARGETS
    else:
        await query.message.reply_text("Enter post (Text/Photo/Video):")
        return BROADCAST_CONTENT

async def broadcast_target_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This handler now receives the callback from the channel selection
    query = update.callback_query
    await query.answer()
    chan_db_id = int(query.data.split('_')[2])
    context.user_data['bd_target_db_id'] = chan_db_id # Store DB ID
    
    await query.message.reply_text("Enter post (Text/Photo/Video):")
    return BROADCAST_CONTENT

async def broadcast_content_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bd_msg_id'] = update.message.message_id
    context.user_data['bd_from_chat'] = update.message.chat_id
    await update.message.reply_text("Add Buttons (Optional)?\nFormat: `Name-Link, Name2-Link2`\n\nType /skip to continue without buttons.")
    return BROADCAST_BUTTONS

async def broadcast_buttons_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '/skip':
        context.user_data['bd_buttons'] = None
    else:
        context.user_data['bd_buttons'] = text
        
    await update.message.reply_text("Enter Time (YYYY-MM-DD HH:MM AM/PM):")
    return BROADCAST_DATETIME

async def broadcast_schedule_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        local_dt = datetime.datetime.strptime(update.message.text, "%Y-%m-%d %I:%M %p")
        local_dt = IST.localize(local_dt)
        context.job_queue.run_once(perform_broadcast, local_dt, data=context.user_data.copy(), name=f"bd_{datetime.datetime.now()}")
        await update.message.reply_text("✅ Scheduled.")
    except:
        await update.message.reply_text("❌ Invalid Format.")
        return BROADCAST_DATETIME
    return ConversationHandler.END

async def perform_broadcast(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    
    reply_markup = None
    if data.get('bd_buttons'):
        kb = []
        raw_btns = data['bd_buttons'].split(',')
        row = []
        for btn in raw_btns:
            if '-' in btn:
                name, link = btn.split('-', 1)
                row.append(InlineKeyboardButton(name.strip(), url=link.strip()))
                if len(row) == 2: 
                    kb.append(row)
                    row = []
        if row: kb.append(row)
        reply_markup = InlineKeyboardMarkup(kb)

    try:
        conn = get_db()
        c = conn.cursor()
        
        if data['bd_type'] == 'bd_type_bot':
            c.execute("SELECT user_id FROM all_users")
            for u in c.fetchall():
                try: await context.bot.copy_message(u[0], data['bd_from_chat'], data['bd_msg_id'], reply_markup=reply_markup)
                except: pass
        else:
            # Fetch Chat ID from DB using saved ID
            c.execute("SELECT chat_id FROM broadcast_channels WHERE id=?", (data['bd_target_db_id'],))
            res = c.fetchone()
            if res: await context.bot.copy_message(res[0], data['bd_from_chat'], data['bd_msg_id'], reply_markup=reply_markup)
        conn.close()
    except Exception as e:
        logger.error(f"Broadcast Error: {e}")

# --- 6. UTILS ---
async def add_bc_chan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("Format: Name|ChatID")
    return 1

async def add_bc_chan_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name, chat_id = update.message.text.split('|')
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO broadcast_channels (name, chat_id) VALUES (?, ?)", (name.strip(), chat_id.strip()))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Saved.")
    except:
        await update.message.reply_text("❌ Error.")
    return ConversationHandler.END

async def admin_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    kb = [
        [InlineKeyboardButton("🗑 Delete Categories", callback_data='del_menu_cats')],
        [InlineKeyboardButton("🗑 Delete Channels", callback_data='del_menu_chans')],
        [InlineKeyboardButton("🗑 Delete All-in-One Pack", callback_data='del_reset_aio')], 
        [InlineKeyboardButton("🗑 Delete Broadcast Chans", callback_data='del_menu_bc')],
        [InlineKeyboardButton("🔄 Reset Payment Info", callback_data='del_reset_pay')],
        [InlineKeyboardButton("🔙 Back", callback_data='user_home')]
    ]
    await update.callback_query.message.edit_text("🗑 **Delete Manager**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def delete_item_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = get_db()
    c = conn.cursor()
    kb = []
    
    if data == 'del_reset_aio':
        c.execute("DELETE FROM aio_settings")
        conn.commit()
        conn.close()
        await query.answer("Deleted!", show_alert=True)
        return

    if data == 'del_menu_cats':
        c.execute("SELECT * FROM categories")
        for r in c.fetchall(): kb.append([InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"perform_del_cat_{r[0]}")])
    elif data == 'del_menu_chans':
        c.execute("SELECT * FROM channels")
        for r in c.fetchall(): kb.append([InlineKeyboardButton(f"❌ {r[2]}", callback_data=f"perform_del_chan_{r[0]}")])
    elif data == 'del_menu_bc':
        c.execute("SELECT * FROM broadcast_channels")
        for r in c.fetchall(): kb.append([InlineKeyboardButton(f"❌ {r[1]}", callback_data=f"perform_del_bc_{r[0]}")])
    elif data == 'del_reset_pay':
        c.execute("UPDATE payment_settings SET upi_id='not_set', paypal_link='not_set' WHERE id=1")
        conn.commit()
        conn.close()
        await query.answer("Reset!", show_alert=True)
        return

    conn.close()
    kb.append([InlineKeyboardButton("🔙 Back", callback_data='admin_delete_menu')])
    await query.message.edit_text("Select item:", reply_markup=InlineKeyboardMarkup(kb))

async def perform_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = get_db()
    c = conn.cursor()
    try:
        oid = int(data.split('_')[-1])
        if 'cat' in data:
            c.execute("DELETE FROM categories WHERE id=?", (oid,))
            c.execute("DELETE FROM channels WHERE category_id=?", (oid,))
            next_menu = 'del_menu_cats'
        elif 'chan' in data:
            c.execute("DELETE FROM channels WHERE id=?", (oid,))
            next_menu = 'del_menu_chans'
        elif 'bc' in data:
            c.execute("DELETE FROM broadcast_channels WHERE id=?", (oid,))
            next_menu = 'del_menu_bc'
        
        conn.commit()
        await query.answer("Deleted!", show_alert=True)
        await delete_item_selector(update._replace(callback_query=query._replace(data=next_menu)), context)
    finally:
        conn.close()

# --- 7. EXPIRY SYSTEM (UPDATED) ---
async def admin_manage_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("➕ Add Manual Sub", callback_data='expire_manual_add')],
        [InlineKeyboardButton("📉 Review Expired", callback_data='expire_manual_check')],
        [InlineKeyboardButton("⚡ Auto-Kick Info", callback_data='expire_auto_info')],
        [InlineKeyboardButton("🔙 Back", callback_data='user_home')]
    ]
    await update.callback_query.message.edit_text(
        "🕰 **Manage Expired Memberships**\n\n"
        "➕ **Add Manual:** Add a user who paid outside bot.\n"
        "📉 **Review:** Check list of expired members.\n"
        "⚡ **Auto-Kick:** System scans & kicks automatically.", 
        reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
    )

# --- MANUAL ADD SUB ---
async def manual_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "📝 **Manual Subscription Entry**\n\n"
        "Please enter details in this format:\n"
        "`UserID Days PlanName`\n\n"
        "Example: `123456789 30 VIP-Gold`"
    )
    return MANUAL_ADD_DETAILS

async def manual_add_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        parts = text.split(' ', 2) # Limit split to 3 parts
        uid = int(parts[0])
        days = int(parts[1])
        p_name = parts[2]
        
        conn = get_db()
        c = conn.cursor()
        now = datetime.datetime.now(IST)
        join_date = now.strftime("%Y-%m-%d")
        exp_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        
        # Use 0 for IDs as it's manual
        c.execute("INSERT INTO subscriptions (user_id, channel_db_id, join_date, expiry_date, channel_chat_id, plan_name) VALUES (?, 0, ?, ?, 0, ?)",
                  (uid, join_date, exp_date, p_name))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Added {uid} for {days} days ({p_name}).")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nFormat: `UserID Days PlanName`")
    return ConversationHandler.END

async def expire_manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    c.execute("SELECT user_id, expiry_date FROM subscriptions WHERE expiry_date < ?", (now_str,))
    expired = c.fetchall()
    conn.close()
    
    if not expired:
        await query.message.edit_text("✅ No expired members.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='admin_manage_expire')]]))
        return

    msg = "📉 **Expired Pending Removal:**\n" + "\n".join([f"ID: {r[0]} | Exp: {r[1]}" for r in expired])
    kb = [[InlineKeyboardButton("🚫 Kick All Listed", callback_data='expire_kick_now')], [InlineKeyboardButton("Back", callback_data='admin_manage_expire')]]
    await query.message.edit_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def expire_kick_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Processing...", show_alert=True)
    await check_expiry_job(context)
    await query.message.edit_text("✅ Done.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='user_home')]]))

async def expire_auto_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Active", show_alert=True)

async def check_expiry_job(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    c.execute('''SELECT s.user_id, s.channel_chat_id, s.rowid, s.join_date, s.expiry_date, u.first_name, s.plan_name 
                 FROM subscriptions s LEFT JOIN all_users u ON s.user_id=u.user_id WHERE s.expiry_date < ?''', (now_str,))
    for item in c.fetchall():
        try:
            if item[1] != 0: # Only try to ban if chat_id is valid
                await context.bot.ban_chat_member(item[1], item[0])
                await context.bot.unban_chat_member(item[1], item[0])
            
            await context.bot.send_message(item[0], "⚠️ **Membership Expired**\nYour plan has ended.")
            c.execute("DELETE FROM subscriptions WHERE rowid=?", (item[2],))
            conn.commit()
            
            # Notify Admin
            admin_msg = (f"🚫 **Member Removed (Expired)**\n\n"
                         f"👤 Name: {item[5]}\n🆔 ID: `{item[0]}`\n"
                         f"📦 Plan: {item[6]}\n📅 Expired: {item[4]}")
            await context.bot.send_message(ADMIN_ID, admin_msg, parse_mode='Markdown')
        except: pass
    conn.close()

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
    await update.callback_query.message.edit_text(f"📊 Stats: Cats {cats} | Plans {chans} | Users {users}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='user_home')]]))

# --- 9. SMART CHAT SYSTEM ---
async def user_start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    set_active_chat(user_id, True) # Lock user in chat
    
    if is_admin_online(): status = "🟢 **Admin is Online**"
    else: status = "🔴 **Admin is Offline**\n(Drop your message, we will reply soon)"
        
    kb = [[InlineKeyboardButton("❌ End Chat", callback_data='end_chat_mode')]]
    await query.message.edit_text(f"💬 **Chat with Admin**\n{status}\n\nAllowed: Text & Photos.", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return USER_CHAT_MODE

async def user_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_chat_active(user.id):
        await update.message.reply_text("⚠️ **Chat ended.**\nPlease click 'Chat with Admin' to start a new support request.", parse_mode='Markdown')
        return ConversationHandler.END

    msg = update.message
    if msg.video or msg.animation or msg.document:
        await msg.reply_text("❌ No Videos/GIFs.")
        return USER_CHAT_MODE
        
    caption_text = f"📩 **New Message**\n👤: {user.first_name} (@{user.username})\n🆔: `{user.id}`"
    if msg.caption: caption_text += f"\n\n{msg.caption}"
    
    kb = [[InlineKeyboardButton("↩️ Reply", callback_data=f"adm_reply_{user.id}"), InlineKeyboardButton("❌ End Chat", callback_data=f"adm_end_{user.id}")]]
    
    if msg.photo:
        await context.bot.send_photo(ADMIN_ID, msg.photo[-1].file_id, caption=caption_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        await context.bot.send_message(ADMIN_ID, f"{caption_text}\n\n{msg.text}", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        
    await msg.reply_text("✅ Sent.")
    return USER_CHAT_MODE

async def user_end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_active_chat(update.effective_user.id, False) # Unlock
    await start(update, context) 
    return ConversationHandler.END

async def admin_start_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    query = update.callback_query
    await query.answer()
    target = int(query.data.split('_')[2])
    context.user_data['reply_target'] = target
    kb = [[InlineKeyboardButton("❌ End Chat", callback_data=f'adm_end_{target}')]]
    await query.message.reply_text(f"Replying to `{target}`:", reply_markup=InlineKeyboardMarkup(kb))
    return ADMIN_REPLY_MODE

async def admin_send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    target = context.user_data.get('reply_target')
    if target:
        if not is_chat_active(target):
             await update.message.reply_text("⚠️ User has left the chat.")
             return ADMIN_REPLY_MODE
        await context.bot.copy_message(target, ADMIN_ID, update.message.message_id)
        await update.message.reply_text("✅ Sent.")
    return ADMIN_REPLY_MODE

async def admin_end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    query = update.callback_query
    await query.answer("Chat Ended")
    
    try:
        target_id = int(query.data.split('_')[2])
    except:
        target_id = context.user_data.get('reply_target')

    if target_id:
        set_active_chat(target_id, False) # Unlock user
        try:
            await context.bot.send_message(chat_id=target_id, text="🚫 **Chat has ended.**\nClick 'Chat with Admin' to reconnect.", parse_mode='Markdown')
        except:
            pass

    await start(update, context) 
    return ConversationHandler.END

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📚 **How to Use This Bot**\n\n"
        "1️⃣ **Go Premium:** Click 'Go Premium' to see plans.\n"
        "2️⃣ **Choose a Plan:** Select a category and plan.\n"
        "3️⃣ **Payment:** Pay via UPI or PayPal.\n"
        "4️⃣ **Screenshot:** Upload proof of payment.\n"
        "5️⃣ **Approval:** Admin verifies and sends you the link!\n\n"
        "📞 **Support:** Use 'Chat with Admin' for help."
    )
    await update.callback_query.message.edit_text(help_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='user_home')]]))

# --- USER STORE & PAYMENT ---
async def user_show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM categories")
    cats = c.fetchall()
    c.execute("SELECT * FROM aio_settings")
    aio = c.fetchone()
    conn.close()
    
    # 2 Column Layout
    kb = []
    if aio: kb.append([InlineKeyboardButton("🌟 All-in-One Pack", callback_data="buy_aio")])
    
    row = []
    for cat in cats:
        row.append(InlineKeyboardButton(f"📂 {cat[1]}", callback_data=f"view_cat_{cat[0]}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    kb.append([InlineKeyboardButton("🔙 Back", callback_data='user_home')])
    
    await update.callback_query.message.edit_text("👇 **Select a Category:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

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
    for chan in chans: kb.append([InlineKeyboardButton(f"{chan[2]} - {chan[4]}", callback_data=f"buy_{chan[0]}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="user_show_cats")])
    await query.message.edit_text("👇 Select a plan to join:", reply_markup=InlineKeyboardMarkup(kb))

async def show_payment_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT upi_id, paypal_link FROM payment_settings")
    sets = c.fetchone()
    
    category_name = "Premium"
    
    if data == 'buy_aio':
        context.user_data['is_aio'] = True
        c.execute("SELECT * FROM aio_settings")
        aio = c.fetchone()
        info = ["All-in-One Pack", aio[2], aio[3]]
        category_name = "All-in-One"
    else:
        context.user_data['is_aio'] = False
        chan_id = int(data.split('_')[1])
        context.user_data['selected_channel_id'] = chan_id
        c.execute("SELECT name, price, duration, category_id FROM channels WHERE id=?", (chan_id,))
        info = c.fetchone()
        
        c.execute("SELECT name FROM categories WHERE id=?", (info[3],))
        cat = c.fetchone()
        if cat: category_name = cat[0]
    
    conn.close()
    
    context.user_data['category_name'] = category_name 
    
    payment_txt = ""
    if sets[0] != 'not_set': payment_txt += f"🇮🇳 **UPI ID:** `{sets[0]}`\n\n"
    if sets[1] != 'not_set': payment_txt += f"🅿️ **PayPal:** {sets[1]}\n\n"
    if not payment_txt: payment_txt = "⚠️ No payment methods set."

    text = (f"💳 **Payment Gateway**\n\n"
            f"📦 **Plan:** {info[0]}\n"
            f"📂 **Category:** {category_name}\n"
            f"💸 **Price:** {info[1]}\n"
            f"⏳ **Duration:** {info[2]} Days\n\n"
            f"{payment_txt}"
            f"📸 **Step 2:** Upload Screenshot.")
            
    kb = [[InlineKeyboardButton("📸 Upload Screenshot", callback_data="req_upload_ss")], [InlineKeyboardButton("🔙 Cancel", callback_data="user_home")]]
    await query.message.edit_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

async def request_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("📤 **Please send your payment screenshot now.**")
    return USER_UPLOAD_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("❌ Please send a photo.")
        return USER_UPLOAD_SCREENSHOT
    
    user = update.effective_user
    conn = get_db()
    c = conn.cursor()
    
    if context.user_data.get('is_aio'):
        c.execute("SELECT * FROM aio_settings")
        aio = c.fetchone()
        plan_name, price = "All-in-One Pack", aio[2]
        callback_data = f"appr_{user.id}_aio"
    else:
        chan_id = context.user_data.get('selected_channel_id')
        c.execute("SELECT name, price FROM channels WHERE id=?", (chan_id,))
        info = c.fetchone()
        plan_name, price = info[0], info[1]
        callback_data = f"appr_{user.id}_{chan_id}"
        
    conn.close()
    
    now_str = datetime.datetime.now(IST).strftime("%Y-%m-%d %I:%M %p")
    caption = (f"🔔 **New Payment Verification**\n\n"
               f"👤 **User:** {user.first_name} (@{user.username})\n"
               f"🆔 **ID:** `{user.id}`\n"
               f"📦 **Plan:** {plan_name}\n"
               f"💸 **Price:** {price}\n"
               f"🕒 **Time:** {now_str}")
               
    kb = [[InlineKeyboardButton("✅ Accept", callback_data=callback_data), InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}")]]
    await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    await update.message.reply_text("✅ Sent to Admin for verification.")
    return ConversationHandler.END

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update_admin_activity()
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    action = data[0]
    uid = int(data[1])
    
    if action == 'rej':
        await context.bot.send_message(uid, "❌ **Payment Rejected.**")
        await query.message.edit_caption(query.message.caption + "\n\n🔴 **REJECTED**")
    
    elif action == 'appr':
        conn = get_db()
        c = conn.cursor()
        now = datetime.datetime.now(IST)
        join_date = now.strftime("%Y-%m-%d")
        join_time = now.strftime("%I:%M %p")
        
        # Get Bot Settings
        c.execute("SELECT notify_group_id, update_channel_link FROM bot_settings WHERE id=1")
        settings = c.fetchone()
        notify_gid = settings[0]
        update_link = settings[1]
        
        bot_username = (await context.bot.get_me()).username
        
        # AIO Logic
        if data[2] == 'aio':
            c.execute("SELECT * FROM aio_settings")
            aio = c.fetchone()
            links_list = aio[1].split(',')
            formatted_links = "\n".join([f"🔗 {link.strip()}" for link in links_list])
            plan_name = "All-in-One Pack"
            category_name = "All-in-One"
            duration = aio[3]
            
            expiry_dt = now + datetime.timedelta(days=duration)
            expiry_str = expiry_dt.strftime("%Y-%m-%d")
            expiry_db = expiry_dt.strftime("%Y-%m-%d %H:%M")
            
            c.execute("INSERT INTO subscriptions (user_id, join_date, expiry_date, plan_name, channel_chat_id, channel_db_id) VALUES (?, ?, ?, ?, 0, 0)", 
                      (uid, join_date, expiry_db, plan_name))
            
        else:
            cid = int(data[2])
            c.execute("SELECT * FROM channels WHERE id=?", (cid,))
            chan = c.fetchone() 
            plan_name = chan[2]
            duration = chan[6]
            formatted_links = f"🔗 **JOIN LINK:** {chan[3]}"
            
            # Fetch Category
            c.execute("SELECT name FROM categories WHERE id=?", (chan[1],))
            cat_row = c.fetchone()
            category_name = cat_row[0] if cat_row else "Premium"
            
            expiry_dt = now + datetime.timedelta(days=duration)
            expiry_str = expiry_dt.strftime("%Y-%m-%d")
            expiry_db = expiry_dt.strftime("%Y-%m-%d %H:%M")
            
            c.execute("INSERT INTO subscriptions (user_id, channel_db_id, join_date, expiry_date, channel_chat_id, plan_name) VALUES (?, ?, ?, ?, ?, ?)", 
                      (uid, cid, join_date, expiry_db, chan[5], plan_name))
        
        conn.commit()
        conn.close()
        
        user_info = await context.bot.get_chat(uid)
        
        await context.bot.send_message(uid, f"🎉 **Payment Accepted!**\n\nHere are your links:\n{formatted_links}", parse_mode='Markdown')
        
        invoice = (f"🧾 **DIGITAL INVOICE**\n"
                   f"━━━━━━━━━━━━━━━━━━━\n"
                   f"📅 **Date:** {join_date}\n"
                   f"🕒 **Time:** {join_time}\n"
                   f"👤 **Member:** {user_info.first_name}\n"
                   f"🆔 **User ID:** `{uid}`\n"
                   f"━━━━━━━━━━━━━━━━━━━\n"
                   f"📂 **Category:** {category_name}\n"
                   f"📦 **Plan:** {plan_name}\n"
                   f"⏳ **Duration:** {duration} Days\n"
                   f"🗓 **Expiry:** {expiry_str}\n"
                   f"📅 **Year:** {now.year}\n"
                   f"━━━━━━━━━━━━━━━━━━━\n"
                   f"✅ **Status:** PAID")
        await context.bot.send_message(uid, invoice, parse_mode='Markdown')
        await query.message.edit_caption(query.message.caption + "\n\n🟢 **ACCEPTED**")

        # GROUP NOTIFICATIONS
        if notify_gid != 'not_set':
            # 1. Main Alert
            group_msg = (f"🔥 **New VIP Member!** 🔥\n\n"
                         f"👤 **User:** {user_info.first_name}\n"
                         f"📦 **Plan:** {plan_name}\n"
                         f"📂 **Category:** {category_name}\n"
                         f"💰 **Amount:** PAID ✅\n"
                         f"📅 **Date:** {join_date}\n\n"
                         f"💡 **Purchase VIP only from the trusted source!**\n"
                         f"👉 [**Click Here to Buy**](https://t.me/{bot_username})")
            
            try:
                await context.bot.send_message(chat_id=notify_gid, text=group_msg, parse_mode='Markdown', disable_web_page_preview=True)
                
                # 2. Update Channel Alert (Separate Message)
                if update_link != 'not_set':
                    update_msg = (f"📢 **Stay Updated!**\n\n"
                                  f"See future updates, proofs, and news here:\n"
                                  f"👉 {update_link}\n\n"
                                  f"Get more information related to the VIP channel!")
                    await context.bot.send_message(chat_id=notify_gid, text=update_msg, parse_mode='Markdown')
                    
            except Exception as e:
                logger.error(f"Failed to send group notification: {e}")

# --- MAIN ---
async def pay_conv_entry(update, context):
    return await request_screenshot(update, context)

def main():
    threading.Thread(target=start_web_server, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    application.job_queue.run_repeating(check_expiry_job, interval=3600, first=10)

    application.add_handler(CommandHandler("start", start))
    
    # HANDLERS
    cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_cat_start, pattern='admin_add_cat')],
        states={ADD_CAT_NAME: [MessageHandler(filters.TEXT, add_cat_save)]},
        fallbacks=[], allow_reentry=True)
    
    chan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_chan_start, pattern='admin_add_chan')],
        states={
            ADD_CHAN_CAT: [CallbackQueryHandler(add_chan_cat_save)],
            ADD_CHAN_NAME: [MessageHandler(filters.TEXT, add_chan_name_save)],
            ADD_CHAN_LINK: [MessageHandler(filters.TEXT, add_chan_link_save)],
            ADD_CHAN_PRICE: [MessageHandler(filters.TEXT, add_chan_price_save)],
            ADD_CHAN_DURATION: [MessageHandler(filters.TEXT, add_chan_duration_save)],
            ADD_CHAN_GROUP_ID: [MessageHandler(filters.TEXT, add_chan_final)],
        },
        fallbacks=[], allow_reentry=True)

    aio_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(aio_start, pattern='admin_set_aio')],
        states={
            AIO_SET_LINKS: [MessageHandler(filters.TEXT, aio_save_links)],
            AIO_SET_PRICE: [MessageHandler(filters.TEXT, aio_save_price)],
            AIO_SET_DURATION: [MessageHandler(filters.TEXT, aio_final)],
        },
        fallbacks=[], allow_reentry=True)

    pay_settings_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_pay_menu, pattern='admin_set_pay')],
        states={
            PAY_CHOOSE: [CallbackQueryHandler(set_pay_ask_upi, pattern='set_pay_upi_btn'), CallbackQueryHandler(set_pay_ask_paypal, pattern='set_pay_paypal_btn')],
            PAY_INPUT_UPI: [MessageHandler(filters.TEXT, set_pay_save_upi)],
            PAY_INPUT_PAYPAL: [MessageHandler(filters.TEXT, set_pay_save_paypal)],
        },
        fallbacks=[CallbackQueryHandler(start, pattern='user_home')], allow_reentry=True)
    
    # Broadcast Flow: Select Type -> (Select Channel) -> Content -> Buttons -> Time
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_menu, pattern='admin_broadcast')],
        states={
            BROADCAST_SELECT_TYPE: [CallbackQueryHandler(broadcast_type_handler)],
            BROADCAST_TARGETS: [CallbackQueryHandler(broadcast_target_save, pattern='^bd_sel_')],
            BROADCAST_CONTENT: [MessageHandler(filters.ALL, broadcast_content_save)],
            BROADCAST_BUTTONS: [MessageHandler(filters.TEXT, broadcast_buttons_save)],
            BROADCAST_DATETIME: [MessageHandler(filters.TEXT, broadcast_schedule_final)]
        },
        fallbacks=[], allow_reentry=True)

    bc_chan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_bc_chan_start, pattern='admin_add_bc_chan')],
        states={1: [MessageHandler(filters.TEXT, add_bc_chan_save)]},
        fallbacks=[], allow_reentry=True)
        
    manual_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(manual_add_start, pattern='expire_manual_add')],
        states={MANUAL_ADD_DETAILS: [MessageHandler(filters.TEXT, manual_add_save)]},
        fallbacks=[], allow_reentry=True)
        
    set_group_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_set_group, pattern='admin_set_group')],
        states={
            SET_NOTIFY_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_notify_group),
                CallbackQueryHandler(reset_notify_group_handler, pattern='reset_notify_group')
            ]
        },
        fallbacks=[CallbackQueryHandler(start, pattern='user_home')], 
        allow_reentry=True)
        
    set_update_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_set_update, pattern='admin_set_update')],
        states={SET_UPDATE_LINK: [MessageHandler(filters.TEXT, save_update_link)]},
        fallbacks=[], allow_reentry=True)

    user_chat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_start_chat, pattern='start_user_chat')],
        states={USER_CHAT_MODE: [MessageHandler(filters.TEXT | filters.PHOTO, user_send_message), MessageHandler(filters.VIDEO, user_send_message)]},
        fallbacks=[CallbackQueryHandler(user_end_chat, pattern='end_chat_mode')], allow_reentry=True)

    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_start_reply, pattern='^adm_reply_')],
        states={ADMIN_REPLY_MODE: [MessageHandler(filters.TEXT | filters.PHOTO, admin_send_reply)]},
        fallbacks=[CallbackQueryHandler(admin_end_chat, pattern='^adm_end_')], allow_reentry=True)
    
    pay_process_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(pay_conv_entry, pattern='req_upload_ss')],
        states={USER_UPLOAD_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)]},
        fallbacks=[], allow_reentry=True
    )

    # ADDING HANDLERS
    application.add_handler(cat_conv)
    application.add_handler(chan_conv)
    application.add_handler(aio_conv)
    application.add_handler(pay_settings_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(bc_chan_conv)
    application.add_handler(manual_add_conv)
    application.add_handler(set_group_conv)
    application.add_handler(set_update_conv)
    application.add_handler(user_chat_conv)
    application.add_handler(admin_reply_conv)
    application.add_handler(pay_process_conv)

    # General Callbacks
    application.add_handler(CallbackQueryHandler(user_show_categories, pattern='user_show_cats'))
    application.add_handler(CallbackQueryHandler(user_show_channels, pattern='^view_cat_'))
    application.add_handler(CallbackQueryHandler(show_payment_options, pattern='^buy_'))
    application.add_handler(CallbackQueryHandler(admin_decision, pattern='^(appr|rej)_'))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern='admin_stats'))
    application.add_handler(CallbackQueryHandler(admin_view_members, pattern='admin_view_members'))
    application.add_handler(CallbackQueryHandler(admin_manage_expire, pattern='admin_manage_expire'))
    application.add_handler(CallbackQueryHandler(expire_manual_check, pattern='expire_manual_check'))
    application.add_handler(CallbackQueryHandler(expire_kick_now, pattern='expire_kick_now'))
    application.add_handler(CallbackQueryHandler(expire_auto_info, pattern='expire_auto_info'))
    application.add_handler(CallbackQueryHandler(admin_delete_menu, pattern='admin_delete_menu'))
    application.add_handler(CallbackQueryHandler(delete_item_selector, pattern='^(del_menu|del_reset)'))
    application.add_handler(CallbackQueryHandler(perform_delete, pattern='^perform_del'))
    application.add_handler(CallbackQueryHandler(show_help, pattern='show_help'))
    application.add_handler(CallbackQueryHandler(start, pattern='user_home'))

    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
