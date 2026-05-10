import os
import json
import asyncio
from datetime import datetime
from typing import List, Dict
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
THRESHOLD = 10

# Хранилище для временных альбомов (в памяти)
pending_albums = {}

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

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("📦 Заархивировать текущие исключения", callback_data="archive_current")],
        [InlineKeyboardButton("📜 Архив исключений", callback_data="show_archives")],
        [InlineKeyboardButton("🗑 Очистить текущие", callback_data="clear_current")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_archive_keyboard(archives: List[Dict]):
    """Клавиатура со списком архивов"""
    keyboard = []
    for idx, archive in enumerate(archives):
        name = archive.get("name", "Без названия")
        date = archive.get("date", "")[:10]
        # Подсчитываем количество элементов в архиве
        items_count = len(archive.get("items", []))
        keyboard.append([
            InlineKeyboardButton(f"📁 {name} ({date}) - {items_count} шт", callback_data=f"view_archive_{idx}"),
            InlineKeyboardButton("🗑", callback_data=f"delete_archive_{idx}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return
    
    await update.message.reply_text(
        "🤖 *Бот для накопления исключений*\n\n"
        "📸 Отправляйте мне:\n"
        "• Одиночные фото\n"
        "• Альбомы (группы фото)\n"
        "• Документы\n"
        "• Текст\n\n"
        "📦 Когда накопится больше 10 исключений, вы получите уведомление\n"
        "💾 Используйте меню для архивации",
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
    
    # Если этого альбома еще нет в pending
    if media_group_id not in pending_albums:
        pending_albums[media_group_id] = {
            "items": [],
            "timestamp": datetime.now().isoformat(),
            "chat_id": chat_id,
            "message_id": update.message.message_id
        }
    
    # Добавляем фото в альбом
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        pending_albums[media_group_id]["items"].append({
            "type": "photo",
            "file_id": file_id
        })
    
    # Отменяем предыдущий таймер, если есть
    if f"timer_{media_group_id}" in context.user_data:
        context.user_data[f"timer_{media_group_id}"].cancel()
    
    # Устанавливаем новый таймер на сохранение альбома
    task = asyncio.create_task(save_album_after_delay(update, context, media_group_id))
    context.user_data[f"timer_{media_group_id}"] = task

async def save_album_after_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    """Сохраняет альбом после задержки (чтобы собрать все фото)"""
    await asyncio.sleep(1.5)  # Ждем 1.5 секунды для сбора всех фото альбома
    
    if media_group_id in pending_albums:
        album_data = pending_albums[media_group_id]
        
        if album_data["items"]:
            data = load_data()
            
            # Сохраняем альбом как один объект
            album_exception = {
                "type": "album",
                "album_id": str(uuid4()),
                "items": album_data["items"],
                "timestamp": album_data["timestamp"]
            }
            data["current_exceptions"].append(album_exception)
            save_data(data)
            
            # Отправляем подтверждение
            photo_count = len(album_data["items"])
            total_count = len(data["current_exceptions"])
            
            await context.bot.send_message(
                chat_id=album_data["chat_id"],
                text=f"✅ Добавлено {photo_count}. Всего исключений: {total_count}"
            )
            
            # Проверяем порог
            if total_count > THRESHOLD:
                for admin_id in ADMIN_IDS:
                    await context.bot.send_message(
                        admin_id,
                        f"⚠️ Накопилось {total_count} исключений (больше {THRESHOLD})\nПора исключить людей!",
                        parse_mode=ParseMode.MARKDOWN
                    )
        
        # Удаляем из временного хранилища
        del pending_albums[media_group_id]
        
        # Удаляем таймер
        if f"timer_{media_group_id}" in context.user_data:
            del context.user_data[f"timer_{media_group_id}"]

async def handle_single_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка одиночного фото (не в альбоме)"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    # Если это часть медиа-группы, игнорируем (обработается handle_media_group)
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
    await update.message.reply_text(f"✅ Одиночное фото добавлено. Всего исключений: {count}")
    
    if count > THRESHOLD:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {count} исключений (больше {THRESHOLD})\nПора исключить людей!",
                parse_mode=ParseMode.MARKDOWN
            )

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
    await update.message.reply_text(f"✅ Документ '{file_name}' добавлен. Всего исключений: {count}")
    
    if count > THRESHOLD:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {count} исключений (больше {THRESHOLD})\nПора исключить людей!",
                parse_mode=ParseMode.MARKDOWN
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    # Если ждем название архива
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
                f"📦 Содержит {len(archive['items'])} элементов\n\n"
                f"Теперь можно накапливать новые исключения",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text("❌ Нет исключений для архивации", reply_markup=get_main_keyboard())
        return
    
    # Обычный текст как исключение
    data = load_data()
    data["current_exceptions"].append({
        "type": "text",
        "content": update.message.text,
        "timestamp": datetime.now().isoformat()
    })
    save_data(data)
    
    count = len(data["current_exceptions"])
    await update.message.reply_text(f"✅ Текст добавлен. Всего исключений: {count}")
    
    if count > THRESHOLD:
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(
                admin_id,
                f"⚠️ *ВНИМАНИЕ!*\n\nНакопилось {count} исключений!",
                parse_mode=ParseMode.MARKDOWN
            )

async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка пересланных сообщений"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    # Если переслан альбом
    if update.message.media_group_id:
        await handle_media_group(update, context)
        return
    
    # Пересланное фото
    if update.message.photo:
        await handle_single_photo(update, context)

# ========== ФУНКЦИИ ДЛЯ ОТПРАВКИ ==========
async def send_exception(context: ContextTypes.DEFAULT_TYPE, chat_id: int, exception: Dict):
    """Отправляет одно исключение (может быть альбомом, фото, документом или текстом)"""
    
    if exception["type"] == "album":
        # Отправляем как альбом
        media_group = []
        for item in exception["items"]:
            if item["type"] == "photo":
                media_group.append(InputMediaPhoto(item["file_id"]))
        
        if media_group:
            try:
                await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                return True
            except Exception as e:
                print(f"Ошибка отправки альбома: {e}")
                # Если не получилось отправить альбом, отправляем по отдельности
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
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ Нет доступа")
        return
    
    data = load_data()
    
    if query.data == "archive_current":
        if len(data["current_exceptions"]) == 0:
            await query.edit_message_text("❌ Нет исключений для архивации")
            return
        
        context.user_data["awaiting_archive_name"] = True
        await query.edit_message_text(
            "📝 Введите название для этого архива:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_archive")]])
        )
    
    elif query.data == "show_archives":
        if not data["archives"]:
            await query.edit_message_text("📭 Архив пуст", reply_markup=get_main_keyboard())
        else:
            await query.edit_message_text(
                "📚 *Архив исключений:*\n\n🗑 Нажмите на корзину, чтобы удалить архив",
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
            
            # Подсчитываем количество элементов разных типов
            album_count = sum(1 for i in items if i["type"] == "album")
            photo_count = sum(1 for i in items if i["type"] == "photo")
            doc_count = sum(1 for i in items if i["type"] == "document")
            text_count = sum(1 for i in items if i["type"] == "text")
            
            photos_in_albums = sum(len(i["items"]) for i in items if i["type"] == "album")
            
            msg = f"📦 *{name}*\n📅 {date[:10]}\n\n"
            msg += f"📊 Статистика:\n"
            msg += f"• Альбомов: {album_count} (всего фото в альбомах: {photos_in_albums})\n"
            msg += f"• Одиночных фото: {photo_count}\n"
            msg += f"• Документов: {doc_count}\n"
            msg += f"• Текстов: {text_count}\n\n"
            msg += f"⬇️ Показываю содержимое ({len(items)} исключений):"
            
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
            
            # Отправляем все элементы архива
            for item in items:
                await send_exception(context, query.message.chat_id, item)
                await asyncio.sleep(0.5)  # Задержка между отправками
            
            # Отправляем клавиатуру для управления архивом
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
    print("📸 Отправляйте альбомы - они будут сохраняться как одно исключение!")
    
    # Создаем приложение
    app = Application.builder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    
    # Обработчики сообщений (ВАЖНО: порядок имеет значение!)
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.FORWARDED, handle_single_photo))
    app.add_handler(MessageHandler(filters.PHOTO & filters.FORWARDED, handle_forwarded))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Обработка кнопок
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Запуск
    app.run_polling()

if __name__ == "__main__":
    main()