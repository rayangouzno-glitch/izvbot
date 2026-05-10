import os
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Set
from uuid import uuid4

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "8761068431:AAEQBuY8_4Xp8qmraNPDcVjTR8DerpHJHVY"
ADMIN_IDS = [1348427586]
DATA_FILE = "exceptions_data.json"
SETTINGS_FILE = "settings_data.json"
THRESHOLD = 10

# Хранилище для временных альбомов (в памяти)
pending_albums = {}

# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
def load_data():
    """Загружает данные из JSON файла"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"current_exceptions": [], "archives": []}

def save_data(data):
    """Сохраняет данные в JSON файл"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_settings():
    """Загружает настройки"""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notify_all_users": False, "subscribed_users": []}

def save_settings(settings):
    """Сохраняет настройки"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("📸 Текущие исключения", callback_data="show_current")],
        [InlineKeyboardButton("📦 Заархивировать текущие", callback_data="archive_current")],
        [InlineKeyboardButton("📜 Архив исключений", callback_data="show_archives")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("🗑 Очистить текущие", callback_data="clear_current")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_settings_keyboard(settings):
    """Клавиатура настроек"""
    notify_status = "✅ Вкл" if settings.get("notify_all_users", False) else "❌ Выкл"
    keyboard = [
        [InlineKeyboardButton(f"📢 Уведомления всем: {notify_status}", callback_data="toggle_notifications")],
        [InlineKeyboardButton("👥 Список подписчиков", callback_data="show_subscribers")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_archive_keyboard(archives: List[Dict]):
    """Клавиатура со списком архивов"""
    keyboard = []
    for idx, archive in enumerate(archives):
        name = archive.get("name", "Без названия")
        date = archive.get("date", "")[:10]
        items_count = len(archive.get("items", []))
        keyboard.append([
            InlineKeyboardButton(f"📁 {name} ({date}) - {items_count} шт", callback_data=f"view_archive_{idx}"),
            InlineKeyboardButton("🗑", callback_data=f"delete_archive_{idx}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    """Клавиатура с кнопкой назад"""
    keyboard = [[InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(keyboard)

# ========== ФУНКЦИИ ДЛЯ УВЕДОМЛЕНИЙ ==========
async def notify_all_subscribers(context: ContextTypes.DEFAULT_TYPE, message: str, parse_mode: str = None):
    """Отправляет уведомление всем подписчикам"""
    settings = load_settings()
    if not settings.get("notify_all_users", False):
        return
    
    subscribers = settings.get("subscribed_users", [])
    for user_id in subscribers:
        try:
            if user_id not in ADMIN_IDS:  # Не дублируем админу
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=parse_mode,
                    reply_markup=get_back_keyboard()
                )
        except Exception as e:
            print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

async def notify_new_exception(context: ContextTypes.DEFAULT_TYPE, exception_type: str, count: int):
    """Уведомляет о новом исключении"""
    settings = load_settings()
    
    # Уведомляем админа
    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"✅ Новое исключение добавлено!\nТип: {exception_type}\nВсего исключений: {count}",
            reply_markup=get_back_keyboard()
        )
    
    # Уведомляем всех подписчиков (если включено)
    if settings.get("notify_all_users", False):
        subscribers = settings.get("subscribed_users", [])
        for user_id in subscribers:
            if user_id not in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"📸 Добавлено новое исключение!\nТип: {exception_type}\nВсего накоплено: {count}",
                        reply_markup=get_back_keyboard()
                    )
                except:
                    pass

# ========== ОБРАБОТЧИКИ КОМАНД ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user_id = update.effective_user.id
    
    # Добавляем пользователя в подписчики (если他不是 админ)
    if user_id not in ADMIN_IDS:
        settings = load_settings()
        if user_id not in settings.get("subscribed_users", []):
            settings["subscribed_users"].append(user_id)
            save_settings(settings)
            await update.message.reply_text(
                "👋 Добро пожаловать!\n"
                "Вы будете получать уведомления о новых исключениях (если админ включит эту функцию)."
            )
    
    await update.message.reply_text(
        "🤖 *Бот для накопления исключений*\n\n"
        "📸 Отправляйте мне:\n"
        "• Одиночные фото\n"
        "• Альбомы (группы фото)\n"
        "• Документы\n"
        "• Текст\n\n"
        "📦 Когда накопится больше 10 исключений, вы получите уведомление\n"
        "💾 Используйте меню для управления",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )

async def show_current_exceptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущие накопленные исключения"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    data = load_data()
    current = data["current_exceptions"]
    
    if not current:
        await query.edit_message_text(
            "📭 *Нет текущих исключений*\n\nОтправьте фото, документы или текст, чтобы начать накопление.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_back_keyboard()
        )
        return
    
    # Подсчитываем статистику
    album_count = sum(1 for i in current if i["type"] == "album")
    photo_count = sum(1 for i in current if i["type"] == "photo")
    doc_count = sum(1 for i in current if i["type"] == "document")
    text_count = sum(1 for i in current if i["type"] == "text")
    photos_in_albums = sum(len(i["items"]) for i in current if i["type"] == "album")
    
    msg = f"📸 *Текущие исключения*\n\n"
    msg += f"📊 *Статистика:*\n"
    msg += f"• Альбомов: {album_count} (всего фото: {photos_in_albums})\n"
    msg += f"• Одиночных фото: {photo_count}\n"
    msg += f"• Документов: {doc_count}\n"
    msg += f"• Текстов: {text_count}\n\n"
    msg += f"📦 *Всего исключений:* {len(current)}\n"
    msg += f"⚠️ *Порог:* {THRESHOLD}\n\n"
    msg += f"⬇️ *Содержимое:*"
    
    await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
    
    # Показываем содержимое
    for item in current:
        await send_exception(context, query.message.chat_id, item)
        await asyncio.sleep(0.3)
    
    await query.message.reply_text(
        "📌 *Управление:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_keyboard()
    )

async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка альбома (группы фото)"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    media_group_id = update.message.media_group_id
    chat_id = update.effective_chat.id
    
    if media_group_id not in pending_albums:
        pending_albums[media_group_id] = {
            "items": [],
            "timestamp": datetime.now().isoformat(),
            "chat_id": chat_id,
            "message_id": update.message.message_id
        }
    
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        pending_albums[media_group_id]["items"].append({
            "type": "photo",
            "file_id": file_id
        })
    
    if f"timer_{media_group_id}" in context.user_data:
        context.user_data[f"timer_{media_group_id}"].cancel()
    
    task = asyncio.create_task(save_album_after_delay(update, context, media_group_id))
    context.user_data[f"timer_{media_group_id}"] = task

async def save_album_after_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    """Сохраняет альбом после задержки"""
    await asyncio.sleep(1.5)
    
    if media_group_id in pending_albums:
        album_data = pending_albums[media_group_id]
        
        if album_data["items"]:
            data = load_data()
            
            album_exception = {
                "type": "album",
                "album_id": str(uuid4()),
                "items": album_data["items"],
                "timestamp": album_data["timestamp"]
            }
            data["current_exceptions"].append(album_exception)
            save_data(data)
            
            photo_count = len(album_data["items"])
            total_count = len(data["current_exceptions"])
            
            await context.bot.send_message(
                chat_id=album_data["chat_id"],
                text=f"✅ Альбом из {photo_count} фото добавлен! Всего: {total_count}",
                reply_markup=get_back_keyboard()
            )
            
            # Уведомления
            await notify_new_exception(context, f"альбом ({photo_count} фото)", total_count)
            
            if total_count > THRESHOLD:
                for admin_id in ADMIN_IDS:
                    await context.bot.send_message(
                        admin_id,
                        f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {total_count} исключений!\nПора исключить людей!",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_back_keyboard()
                    )
                await notify_all_subscribers(context, f"⚠️ Внимание! Накопилось {total_count} исключений!")
        
        del pending_albums[media_group_id]
        if f"timer_{media_group_id}" in context.user_data:
            del context.user_data[f"timer_{media_group_id}"]

async def handle_single_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка одиночного фото"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    if update.message.media_group_id:
        return
    
    data = load_data()
    file_id = update.message.photo[-1].file_id
    
    data["current_exceptions"].append({
        "type": "photo",
        "file_id": file_id,
        "timestamp": datetime.now().isoformat()
    })
    save_data(data)
    
    count = len(data["current_exceptions"])
    await update.message.reply_text(f"✅ Фото добавлено! Всего: {count}", reply_markup=get_back_keyboard())
    
    await notify_new_exception(context, "фото", count)
    
    if count > THRESHOLD:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {count} исключений!\nПора исключить людей!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_back_keyboard()
            )
        await notify_all_subscribers(context, f"⚠️ Внимание! Накопилось {count} исключений!")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка документов"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    data = load_data()
    file_id = update.message.document.file_id
    file_name = update.message.document.file_name or "документ"
    
    data["current_exceptions"].append({
        "type": "document",
        "file_id": file_id,
        "file_name": file_name,
        "timestamp": datetime.now().isoformat()
    })
    save_data(data)
    
    count = len(data["current_exceptions"])
    await update.message.reply_text(f"✅ Документ '{file_name}' добавлен! Всего: {count}", reply_markup=get_back_keyboard())
    
    await notify_new_exception(context, f"документ ({file_name})", count)
    
    if count > THRESHOLD:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {count} исключений!\nПора исключить людей!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_back_keyboard()
            )
        await notify_all_subscribers(context, f"⚠️ Внимание! Накопилось {count} исключений!")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    if context.user_data.get("awaiting_archive_name"):
        archive_name = update.message.text.strip()
        context.user_data["awaiting_archive_name"] = False
        
        data = load_data()
        if data["current_exceptions"]:
            archive = {
                "name": archive_name,
                "date": datetime.now().isoformat(),
                "items": data["current_exceptions"].copy()
            }
            data["archives"].append(archive)
            data["current_exceptions"] = []
            save_data(data)
            
            await update.message.reply_text(
                f"✅ Архив *{archive_name}* сохранён!\n"
                f"📦 Содержит {len(archive['items'])} элементов",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text("❌ Нет исключений для архивации", reply_markup=get_main_keyboard())
        return
    
    data = load_data()
    data["current_exceptions"].append({
        "type": "text",
        "content": update.message.text,
        "timestamp": datetime.now().isoformat()
    })
    save_data(data)
    
    count = len(data["current_exceptions"])
    await update.message.reply_text(f"✅ Текст добавлен! Всего: {count}", reply_markup=get_back_keyboard())
    
    await notify_new_exception(context, "текст", count)
    
    if count > THRESHOLD:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {count} исключений!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_back_keyboard()
            )
        await notify_all_subscribers(context, f"⚠️ Внимание! Накопилось {count} исключений!")

# ========== ФУНКЦИИ ДЛЯ ОТПРАВКИ ==========
async def send_exception(context: ContextTypes.DEFAULT_TYPE, chat_id: int, exception: Dict):
    """Отправляет одно исключение"""
    if exception["type"] == "album":
        media_group = []
        for item in exception["items"]:
            if item["type"] == "photo":
                media_group.append(InputMediaPhoto(item["file_id"]))
        
        if media_group:
            try:
                await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                return True
            except:
                for item in exception["items"]:
                    await context.bot.send_photo(chat_id=chat_id, photo=item["file_id"])
                    await asyncio.sleep(0.3)
                return True
    
    elif exception["type"] == "photo":
        await context.bot.send_photo(chat_id=chat_id, photo=exception["file_id"])
        return True
    
    elif exception["type"] == "document":
        await context.bot.send_document(chat_id=chat_id, document=exception["file_id"])
        return True
    
    elif exception["type"] == "text":
        await context.bot.send_message(chat_id=chat_id, text=f"📝 {exception['content']}")
        return True
    
    return False

# ========== КОЛБЭКИ МЕНЮ ==========
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Настройки доступны всем, но изменение только админу
    if query.data == "settings":
        settings = load_settings()
        await query.edit_message_text(
            "⚙️ *Настройки бота*\n\n"
            "Здесь можно настроить уведомления для всех пользователей.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_settings_keyboard(settings)
        )
        return
    
    # Остальные функции только для админа
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ Нет доступа", reply_markup=get_back_keyboard())
        return
    
    data = load_data()
    settings = load_settings()
    
    if query.data == "show_current":
        await show_current_exceptions(update, context)
    
    elif query.data == "archive_current":
        if len(data["current_exceptions"]) == 0:
            await query.edit_message_text("❌ Нет исключений для архивации", reply_markup=get_back_keyboard())
            return
        
        context.user_data["awaiting_archive_name"] = True
        await query.edit_message_text(
            "📝 Введите название для этого архива:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_archive")]])
        )
    
    elif query.data == "show_archives":
        if not data["archives"]:
            await query.edit_message_text("📭 Архив пуст", reply_markup=get_back_keyboard())
        else:
            await query.edit_message_text(
                "📚 *Архив исключений:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_archive_keyboard(data["archives"])
            )
    
    elif query.data == "clear_current":
        data["current_exceptions"] = []
        save_data(data)
        await query.edit_message_text("🗑 Текущие исключения очищены", reply_markup=get_main_keyboard())
    
    elif query.data == "back_to_main":
        await query.edit_message_text("🏠 Главное меню:", reply_markup=get_main_keyboard())
    
    elif query.data == "cancel_archive":
        context.user_data.pop("awaiting_archive_name", None)
        await query.edit_message_text("Архивация отменена", reply_markup=get_main_keyboard())
    
    elif query.data == "toggle_notifications":
        settings["notify_all_users"] = not settings.get("notify_all_users", False)
        save_settings(settings)
        status = "включены" if settings["notify_all_users"] else "выключены"
        await query.edit_message_text(
            f"✅ Уведомления для всех пользователей {status}\n\n"
            f"Теперь {'будут' if settings['notify_all_users'] else 'не будут'} приходить уведомления о новых исключениях.",
            reply_markup=get_settings_keyboard(settings)
        )
    
    elif query.data == "show_subscribers":
        subscribers = settings.get("subscribed_users", [])
        if not subscribers:
            await query.edit_message_text("👥 Нет подписчиков", reply_markup=get_settings_keyboard(settings))
        else:
            msg = "👥 *Список подписчиков:*\n\n"
            for idx, sub_id in enumerate(subscribers, 1):
                msg += f"{idx}. `{sub_id}`\n"
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=get_settings_keyboard(settings))
    
    elif query.data.startswith("delete_archive_"):
        idx = int(query.data.split("_")[2])
        if idx < len(data["archives"]):
            archive_name = data["archives"][idx].get("name", "Без названия")
            data["archives"].pop(idx)
            save_data(data)
            
            if not data["archives"]:
                await query.edit_message_text(f"✅ Архив '{archive_name}' удален\n\n📭 Архив пуст", reply_markup=get_main_keyboard())
            else:
                await query.edit_message_text(
                    f"✅ Архив '{archive_name}' удален\n\n📚 *Архив исключений:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_archive_keyboard(data["archives"])
                )
    
    elif query.data.startswith("view_archive_"):
        idx = int(query.data.split("_")[2])
        if idx < len(data["archives"]):
            archive = data["archives"][idx]
            name = archive.get("name", "Без названия")
            date = archive.get("date", "")
            items = archive.get("items", [])
            
            album_count = sum(1 for i in items if i["type"] == "album")
            photo_count = sum(1 for i in items if i["type"] == "photo")
            doc_count = sum(1 for i in items if i["type"] == "document")
            text_count = sum(1 for i in items if i["type"] == "text")
            photos_in_albums = sum(len(i["items"]) for i in items if i["type"] == "album")
            
            msg = f"📦 *{name}*\n📅 {date[:10]}\n\n"
            msg += f"📊 Статистика:\n"
            msg += f"• Альбомов: {album_count} (всего фото: {photos_in_albums})\n"
            msg += f"• Одиночных фото: {photo_count}\n"
            msg += f"• Документов: {doc_count}\n"
            msg += f"• Текстов: {text_count}\n\n"
            msg += f"⬇️ Показываю содержимое ({len(items)} исключений):"
            
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
            
            for item in items:
                await send_exception(context, query.message.chat_id, item)
                await asyncio.sleep(0.5)
            
            keyboard = [
                [InlineKeyboardButton("🗑 Удалить этот архив", callback_data=f"delete_archive_{idx}")],
                [InlineKeyboardButton("🔙 К списку архивов", callback_data="show_archives")]
            ]
            await query.message.reply_text("📌 *Управление архивом:*", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== ЗАПУСК ==========
def main():
    """Запуск бота"""
    print("🤖 Запуск бота...")
    print(f"👑 Администратор: {ADMIN_IDS[0]}")
    print(f"📊 Порог уведомлений: {THRESHOLD}")
    print("✅ Бот готов к работе!\n")
    print("📸 Особенности:")
    print("• Альбомы сохраняются как одно исключение")
    print("• Есть кнопка 'Текущие исключения' для просмотра")
    print("• Уведомления можно включить для всех пользователей")
    print("• Кнопка 'Меню' добавлена к каждому сообщению")
    
    app = Application.builder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.FORWARDED, handle_single_photo))
    app.add_handler(MessageHandler(filters.PHOTO & filters.FORWARDED, handle_media_group))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Обработка кнопок
    app.add_handler(CallbackQueryHandler(button_callback))
    
    app.run_polling()

if __name__ == "__main__":
    main()
