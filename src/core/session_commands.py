"""Session management commands for the Instagram bot."""

from typing import Optional, List
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from src.core.session_manager import InstagramSessionManager
from src.services.session_storage import SessionStorageService

logger = logging.getLogger(__name__)

class SessionCommands:
    """Mixin class for session management commands."""
    
    async def handle_session_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /session command and cookie file uploads."""
        if not update.message or not update.effective_user:
            return
            
        # Check if this is just the command without a file
        if not update.message.document:
            if not update.message.caption or update.message.caption.strip().lower() != "/session":
                await update.message.reply_text(
                    "Please upload your cookies.txt file and add '/session' as the caption.\n\n"
                    "You can export cookies from Firefox using extensions like:\n"
                    "- 'Export Cookies'\n"
                    "- 'Cookie Quick Manager'\n\n"
                    "The file must be in Netscape format and contain Instagram cookies."
                )
            return

        # Check if this is a file upload with /session caption
        if update.message.caption and update.message.caption.strip().lower() == "/session":
            try:
                # Download the file to a unique temp path
                file = await context.bot.get_file(update.message.document.file_id)
                temp_path = Path(f"/tmp/cookies_{update.effective_user.id}_{datetime.now().timestamp()}.txt")
                
                # Download the file
                await file.download_to_drive(temp_path)
                
                # Process the cookies file
                await self._process_cookies_file(update, temp_path)
                
            except Exception as e:
                logger.error(f"Failed to process cookie file: {e}", exc_info=True)
                await update.message.reply_text(
                    f"❌ Failed to process the cookie file: {str(e)}\n\n"
                    "Please make sure it's a valid Netscape format cookies.txt file."
                )
                
            finally:
                # Clean up temp file
                if temp_path.exists():
                    temp_path.unlink()
            
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
                await self.services.session_storage.store_session(
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
            sessions = await self.services.session_storage.get_all_sessions(update.effective_user.id)
            
            if not sessions:
                await update.message.reply_text(
                    "You don't have any Instagram sessions stored.\n"
                    "Use /session_upload to add a new session from a cookies.txt file."
                )
                return
                
            # Format session list with new aesthetic
            now = datetime.now()
            response = [
                "🔐 INSTAGRAM SESSIONS\n"
                "==============================\n"
            ]
            
            for session in sessions:
                expires = session['expires_at']
                last_validated = session.get('last_validated')

                # Format dates if they are strings
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                if isinstance(last_validated, str):
                    last_validated = datetime.fromisoformat(last_validated.replace('Z', '+00:00'))

                # Calculate expiry status
                if expires:
                    days_left = (expires - now).days
                    if days_left > 7:
                        expiry_status = "✅"
                    elif days_left > 0:
                        expiry_status = "⚠️"
                    else:
                        expiry_status = "⛔️"
                    expires_text = f"Expires in {days_left} days"
                else:
                    expiry_status = "ℹ️"
                    expires_text = "No expiration"

                # Calculate validation status
                if last_validated:
                    days_since = (now - last_validated).days
                    if days_since < 1:
                        validate_status = "✅"
                    elif days_since < 7:
                        validate_status = "⚠️"
                    else:
                        validate_status = "⛔️"
                    last_validated_text = f"Validated {days_since}d ago"
                else:
                    validate_status = "⛔️"
                    last_validated_text = "Never validated"

                session_status = "✅ Active" if session['is_active'] else "⏸️ Inactive"
                type_icon = "📁" if session['session_type'] == 'cookies_file' else "🦊"
                
                response.append(
                    f"\n📎 SESSION #{session['id']}\n"
                    f"------------------------------\n"
                    f"├─ 🔵 Status    : {session_status}\n"
                    f"├─ 📂 Type      : {type_icon} {session['session_type']}\n"
                    f"├─ 🔄 Validated : {validate_status} {last_validated_text}\n"
                    f"╰─ ⏳ Expires   : {expiry_status} {expires_text}"
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
            
    async def _process_cookies_file(self, update: Update, temp_path: Path):
        """Process and validate an uploaded cookies file."""
        try:
            # Copy to destination with proper permissions
            cookies_dst = Path("gallery-dl-cookies.txt")
            
            # Read cookies first to validate
            cookies_content = temp_path.read_text()
            if "instagram.com" not in cookies_content:
                raise ValueError("No Instagram cookies found in file")
                
            # Write atomically to avoid file busy errors
            temp_dest = cookies_dst.with_suffix(".txt.tmp")
            temp_dest.write_text(cookies_content)
            temp_dest.chmod(0o644)  # Set proper permissions
            temp_dest.rename(cookies_dst)
            
            await update.message.reply_text(
                "✅ Cookie file processed and activated successfully!\n"
                "The bot will now use these cookies for Instagram requests."
            )
            
        except Exception as e:
            logger.error(f"Error processing cookies: {e}", exc_info=True)
            raise ValueError(f"Failed to process cookies: {str(e)}")