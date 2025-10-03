"""Telethon authentication command handler."""

import logging
from typing import Optional, Dict
from datetime import datetime
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from src.services.telegram_session_storage import TelegramSessionStorage

logger = logging.getLogger(__name__)

# Conversation states
PHONE_NUMBER, CODE, PASSWORD = range(3)

class TelethonAuthCommand:
    """Handles Telethon authentication flow"""

    def __init__(self, api_id: int, api_hash: str, session_storage: TelegramSessionStorage):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_storage = session_storage
        self.temp_clients: Dict[int, TelegramClient] = {}
        self.sessions_path = Path("/app/sessions")
        self.sessions_path.mkdir(exist_ok=True)

    def get_handlers(self):
        """Get the conversation handler for Telethon auth"""
        return ConversationHandler(
            entry_points=[CommandHandler("telethon_login", self.start_auth)],
            states={
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.phone_number_received)],
                CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.code_received)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.password_received)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
            name="telethon_auth",
            persistent=False
        )

    async def start_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the authentication process."""
        if not update.message or not update.effective_user:
            return ConversationHandler.END

        user_id = update.effective_user.id
        
        # Clean up any existing temporary client
        if user_id in self.temp_clients:
            await self.temp_clients[user_id].disconnect()
            del self.temp_clients[user_id]

        await update.message.reply_text(
            "🔐 Telethon Authentication\n"
            "This will help you set up Telethon for large file uploads.\n\n"
            "Please send your phone number in international format: \n"
            "Example: +1234567890"
        )
        
        return PHONE_NUMBER

    async def phone_number_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the received phone number."""
        if not update.message or not update.effective_user:
            return ConversationHandler.END

        user_id = update.effective_user.id
        phone_number = update.message.text.strip()

        # Create a new Telethon client
        session_path = self.sessions_path / f"telethon_{user_id}.session"
        client = TelegramClient(str(session_path), self.api_id, self.api_hash)
        
        try:
            await client.connect()
            
            # Request the code
            await client.send_code_request(phone_number)
            
            # Store the client temporarily
            self.temp_clients[user_id] = client
            
            await update.message.reply_text(
                "📱 Verification code sent!\n"
                "Please enter the code you received:"
            )
            
            # Store the phone number in context
            context.user_data['phone_number'] = phone_number
            
            return CODE
            
        except Exception as e:
            logger.error(f"Failed to send code: {e}")
            await client.disconnect()
            await update.message.reply_text(
                "❌ Failed to send verification code.\n"
                "Please make sure your phone number is correct and try again."
            )
            return ConversationHandler.END

    async def code_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the received verification code."""
        if not update.message or not update.effective_user:
            return ConversationHandler.END

        user_id = update.effective_user.id
        code = update.message.text.strip()
        phone_number = context.user_data.get('phone_number')

        if user_id not in self.temp_clients or not phone_number:
            await update.message.reply_text("❌ Session expired. Please start over with /telethon_login")
            return ConversationHandler.END

        client = self.temp_clients[user_id]

        try:
            # Try to sign in with the code
            await client.sign_in(phone_number, code)
            
            # Save the session
            await self.save_session(user_id, client)
            
            await update.message.reply_text(
                "✅ Successfully authenticated!\n"
                "You can now use Telethon for large file uploads."
            )
            
            return ConversationHandler.END
            
        except SessionPasswordNeededError:
            await update.message.reply_text(
                "🔒 Two-factor authentication is enabled.\n"
                "Please enter your password:"
            )
            return PASSWORD
            
        except PhoneCodeInvalidError:
            await update.message.reply_text(
                "❌ Invalid code.\n"
                "Please try again or use /cancel to start over."
            )
            return CODE
            
        except Exception as e:
            logger.error(f"Failed to sign in: {e}")
            await update.message.reply_text(
                "❌ Failed to authenticate.\n"
                "Please try again with /telethon_login"
            )
            return ConversationHandler.END

    async def password_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle the received 2FA password."""
        if not update.message or not update.effective_user:
            return ConversationHandler.END

        user_id = update.effective_user.id
        password = update.message.text.strip()

        if user_id not in self.temp_clients:
            await update.message.reply_text("❌ Session expired. Please start over with /telethon_login")
            return ConversationHandler.END

        client = self.temp_clients[user_id]

        try:
            # Try to complete sign in with password
            await client.sign_in(password=password)
            
            # Save the session
            await self.save_session(user_id, client)
            
            await update.message.reply_text(
                "✅ Successfully authenticated!\n"
                "You can now use Telethon for large file uploads."
            )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Failed to sign in with password: {e}")
            await update.message.reply_text(
                "❌ Invalid password.\n"
                "Please try again or use /cancel to start over."
            )
            return PASSWORD

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the conversation."""
        if not update.message or not update.effective_user:
            return ConversationHandler.END

        user_id = update.effective_user.id
        
        # Clean up the temporary client
        if user_id in self.temp_clients:
            await self.temp_clients[user_id].disconnect()
            del self.temp_clients[user_id]

        await update.message.reply_text(
            "🚫 Authentication cancelled.\n"
            "You can start over with /telethon_login"
        )
        
        return ConversationHandler.END

    async def save_session(self, user_id: int, client: TelegramClient) -> None:
        """Save the Telethon session."""
        try:
            session_path = self.sessions_path / f"telethon_{user_id}.session"
            
            # Store the session in the database
            await self.session_storage.store_telegram_session(
                user_id=user_id,
                session_file_path=str(session_path),
                api_id=self.api_id,
                api_hash=self.api_hash,
                phone_number=None,  # We don't store the phone number for security
                created_at=datetime.now(),
                last_used_at=datetime.now()
            )
            
            # Clean up the temporary client
            if user_id in self.temp_clients:
                await client.disconnect()
                del self.temp_clients[user_id]
                
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            raise