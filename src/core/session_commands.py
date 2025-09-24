"""Session management commands for the Instagram bot."""

from typing import Optional, List
import logging
from pathlib import Path
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class SessionCommands:
    """Mixin class for session management commands."""
    
    async def handle_session_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /session_upload command."""
        if not update.message or not update.effective_user:
            return
            
        # Check if a file was uploaded
        if not update.message.document:
            await update.message.reply_text(
                "Please upload a cookies.txt file with this command.\n\n"
                "You can export cookies from Firefox using extensions like:\n"
                "- 'Export Cookies'\n"
                "- 'Cookie Quick Manager'\n\n"
                "The file must be in Netscape format and contain Instagram cookies."
            )
            return
            
        try:
            # Download the file
            file = await context.bot.get_file(update.message.document.file_id)
            temp_path = Path(f"/tmp/cookies_{update.effective_user.id}_{datetime.now().timestamp()}.txt")
            await file.download_to_drive(temp_path)
            
            # Try loading and validating the cookies
            try:
                session = self.session_manager.load_cookies_from_file(temp_path)
                if not session or not all(cookie in session for cookie in ['sessionid', 'csrftoken']):
                    raise ValueError("Missing required cookies (sessionid and csrftoken)")
                    
                # Store the session
                await self.session_storage.store_session(
                    user_id=update.effective_user.id,
                    username=session.get('ds_user_id', 'unknown'),
                    session_type='cookies_file',
                    session_data=session,
                    cookies_file_path=temp_path,
                    make_active=True
                )
                
                await update.message.reply_text(
                    "✅ Cookie file uploaded and validated successfully!\n"
                    "This session is now active and will be used for downloads."
                )
                
            finally:
                # Clean up temp file
                if temp_path.exists():
                    temp_path.unlink()
                    
        except Exception as e:
            logger.error(f"Failed to process cookie file: {e}")
            await update.message.reply_text(
                "❌ Failed to process the cookie file.\n"
                "Please ensure it's a valid Netscape format cookies.txt file "
                "containing Instagram cookies (sessionid and csrftoken)."
            )
    
    async def handle_session_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /session_list command."""
        if not update.message or not update.effective_user:
            return
            
        try:
            # Get all sessions for the user
            sessions = await self.session_storage.get_all_sessions(update.effective_user.id)
            
            if not sessions:
                await update.message.reply_text(
                    "You don't have any Instagram sessions stored.\n"
                    "Use /session_upload to add a new session from a cookies.txt file."
                )
                return
                
            # Format session list
            response = ["Your Instagram Sessions:"]
            for session in sessions:
                status = "✅ Active" if session['is_active'] else "⏸️ Inactive"
                type_icon = "📁" if session['session_type'] == 'cookies_file' else "🦊"
                expires = session['expires_at']
                expires_text = f"Expires: {expires:%Y-%m-%d}" if expires else "No expiration"
                
                response.append(
                    f"\n{type_icon} Session #{session['id']}\n"
                    f"Status: {status}\n"
                    f"Type: {session['session_type']}\n"
                    f"Last validated: {session['last_validated']:%Y-%m-%d %H:%M}\n"
                    f"{expires_text}"
                )
                
            # Add action buttons
            keyboard = []
            for session in sessions:
                if not session['is_active']:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"Activate Session #{session['id']}", 
                            callback_data=f"activate_session_{session['id']}"
                        )
                    ])
                keyboard.append([
                    InlineKeyboardButton(
                        f"Delete Session #{session['id']}", 
                        callback_data=f"delete_session_{session['id']}"
                    )
                ])
                
            await update.message.reply_text(
                "\n".join(response),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            await update.message.reply_text(
                "❌ Failed to retrieve sessions. Please try again later."
            )
    
    async def handle_session_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle session management button clicks."""
        if not update.callback_query or not update.effective_user:
            return
            
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data.startswith("activate_session_"):
                session_id = int(query.data.split("_")[-1])
                if await self.session_storage.set_active_session(update.effective_user.id, session_id):
                    await query.edit_message_text(
                        f"✅ Session #{session_id} is now active.\n"
                        "It will be used for future downloads."
                    )
                else:
                    await query.edit_message_text("❌ Failed to activate session.")
                    
            elif query.data.startswith("delete_session_"):
                session_id = int(query.data.split("_")[-1])
                if await self.session_storage.delete_session(update.effective_user.id, session_id):
                    await query.edit_message_text(f"✅ Session #{session_id} has been deleted.")
                else:
                    await query.edit_message_text("❌ Failed to delete session.")
                    
        except Exception as e:
            logger.error(f"Failed to handle session button: {e}")
            await query.edit_message_text("❌ An error occurred. Please try again.")
            
    async def cleanup_expired_sessions(self) -> None:
        """Clean up expired sessions. Called periodically by the maintenance task."""
        try:
            count = await self.session_storage.cleanup_expired_sessions()
            if count > 0:
                logger.info(f"Cleaned up {count} expired sessions")
        except Exception as e:
            logger.error(f"Failed to cleanup expired sessions: {e}")