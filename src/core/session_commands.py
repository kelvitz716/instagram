"""Session management commands for the Instagram bot."""

from typing import Optional, List, Any
import asyncio
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
    
    def __init__(self, session_manager: InstagramSessionManager, services: Any):
        self.session_manager = session_manager
        self.services = services
    
    async def handle_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Interactive session management command."""
        if not update.message or not update.effective_user:
            return

        # Get current session status
        is_valid = await self.session_manager.is_valid()
        
        if not update.message.document:
            # Show different options based on session status
            if is_valid:
                keyboard = [
                    [InlineKeyboardButton("✅ Check Status", callback_data="check_status")],
                    [InlineKeyboardButton("🔄 Update Session", callback_data="upload_cookies")],
                    [InlineKeyboardButton("❌ Logout", callback_data="logout")]
                ]
                status = "🟢 *Active*"
            else:
                keyboard = [
                    [InlineKeyboardButton("🔑 Login with Cookies", callback_data="upload_cookies")],
                    [InlineKeyboardButton("❓ How to Get Cookies", callback_data="cookie_help")]
                ]
                status = "🔴 *Not Logged In*"
            
            await update.message.reply_text(
                "🔐 *Instagram Session Manager*\n\n"
                f"Current Status: {status}\n\n"
                "Select an option below to manage your Instagram login.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
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
                session = await self.session_manager.load_cookies_from_file(temp_path)
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
            # Validate storage
            storage_status = await self.services.session_storage.check_storage()
            if not storage_status['healthy']:
                await update.message.reply_text(
                    "⚠️ *Warning:* Session storage issues detected\n\n"
                    f"Issues found: {storage_status['issues']}\n"
                    "Some features may be limited.",
                    parse_mode='Markdown'
                )
            
            # Get all sessions with statistics
            sessions = await self.services.session_storage.get_all_sessions(update.effective_user.id)
            stats = await self.services.session_storage.get_session_stats(update.effective_user.id)
            
            if not sessions:
                keyboard = [[InlineKeyboardButton("📤 Upload New Session", callback_data="upload_cookies")]]
                await update.message.reply_text(
                    "📭 *No Active Sessions*\n\n"
                    "You don't have any Instagram sessions stored.\n"
                    "Would you like to upload a new session?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
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
        """Handle interactive session management buttons."""
        if not update.callback_query or not update.effective_user:
            return
            
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data == "upload_cookies":
                await query.edit_message_text(
                    "📤 *Upload Your Instagram Cookies*\n\n"
                    "1️⃣ Login to Instagram in your browser\n"
                    "2️⃣ Install a cookie exporter extension:\n"
                    "   • Firefox: 'Export Cookies'\n"
                    "   • Chrome: 'EditThisCookie'\n\n"
                    "3️⃣ Export cookies as Netscape format\n"
                    "4️⃣ Send the cookies.txt file here\n\n"
                    "_Just upload the file - I'll guide you through the rest!_",
                    parse_mode='Markdown'
                )
                
            elif query.data == "cookie_help":
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
                await query.edit_message_text(
                    "❓ *How to Get Instagram Cookies*\n\n"
                    "*Chrome Users:*\n"
                    "1. Install 'EditThisCookie' extension\n"
                    "2. Go to instagram.com and login\n"
                    "3. Click extension icon → Export\n"
                    "4. Save as cookies.txt\n\n"
                    "*Firefox Users:*\n"
                    "1. Install 'Export Cookies' extension\n"
                    "2. Go to instagram.com and login\n"
                    "3. Right-click → Export Cookies\n"
                    "4. Choose Netscape format\n\n"
                    "_Need help? Contact @kelvitz716_",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                
            elif query.data == "check_status":
                is_valid = await self.session_manager.is_valid()
                last_refresh = self.session_manager.last_refresh_time
                refresh_age = datetime.now() - last_refresh if last_refresh else None
                
                status_text = "🔐 *Session Status*\n\n"
                status_text += "Status: ✅ Active\n" if is_valid else "Status: ❌ Invalid\n"
                if refresh_age:
                    status_text += f"Last Verified: {refresh_age.seconds // 60} minutes ago\n"
                
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
                await query.edit_message_text(
                    status_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                
            elif query.data == "logout":
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Yes", callback_data="confirm_logout"),
                        InlineKeyboardButton("❌ No", callback_data="back_to_main")
                    ]
                ]
                await query.edit_message_text(
                    "❗ *Confirm Logout*\n\n"
                    "Are you sure you want to logout?\n"
                    "This will delete your current session.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                
            elif query.data == "confirm_logout":
                # Clear session
                await self.session_manager.clear_session()
                keyboard = [[InlineKeyboardButton("🔑 Login Again", callback_data="upload_cookies")]]
                await query.edit_message_text(
                    "✅ *Logged Out Successfully*\n\n"
                    "Your Instagram session has been removed.\n"
                    "Click below to login again when ready.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                
            elif query.data == "back_to_main":
                # Return to main session menu
                await self.handle_session(update, context)
                    
        except Exception as e:
            logger.error(f"Failed to handle session button: {e}")
            await query.edit_message_text("❌ An error occurred. Please try again.")
            
    async def handle_session_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Check the status of Instagram sessions."""
        if not update.effective_user:
            return
            
        try:
            # Get active session
            active_session = await self.services.session_storage.get_active_session(update.effective_user.id)
            if not active_session:
                await update.message.reply_text(
                    "❌ No active session found.\n"
                    "Please upload a session first."
                )
                return
                
            # Check session health
            status = await self.session_manager.validate_session(active_session['id'])
            stats = await self.services.session_storage.get_session_stats(update.effective_user.id)
            
            response = [
                "📊 *Session Status Report*\n",
                f"Session ID: `{active_session['id']}`\n",
                f"Type: {active_session['session_type']}\n",
                f"Health: {'✅ Good' if status['valid'] else '❌ Invalid'}\n",
                f"Downloads: {stats['total_downloads']}\n",
                f"Success Rate: {stats['success_rate']}%\n",
                "\n*Storage Stats:*\n",
                f"Space Used: {stats['storage_used']}\n",
                f"Downloads Today: {stats['downloads_today']}\n",
                f"Average Size: {stats['avg_download_size']}\n"
            ]
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Status", callback_data=f"refresh_status_{active_session['id']}")],
                [InlineKeyboardButton("🗑 Clear Cache", callback_data="clear_cache")]
            ]
            
            await update.message.reply_text(
                "".join(response),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Failed to check session status: {e}")
            await update.message.reply_text(
                "❌ Failed to check session status. Please try again later."
            )
    
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
            
            # Wait for file to be fully available
            while not cookies_dst.exists():
                await asyncio.sleep(0.1)
            
            await update.message.reply_text(
                "✅ Cookie file processed and activated successfully!\n"
                "The bot will now use these cookies for Instagram requests."
            )
            
        except Exception as e:
            logger.error(f"Error processing cookies: {e}", exc_info=True)
            raise ValueError(f"Failed to process cookies: {str(e)}")