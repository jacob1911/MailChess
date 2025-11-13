"""
Email Service - Handles email fetching and synchronization
Single Responsibility: Email operations (fetch, sync)
Depends on: email_utils module
"""
from utils.email_utils import fetch_new_threads, sync_existing_threads


class EmailService:
    """Service for email operations - follows Single Responsibility Principle"""

    @staticmethod
    def fetch_new(user_id, user_email, access_token, count=5):
        """
        Fetch new email threads from Gmail

        Args:
            user_id: User ID
            user_email: User email address
            access_token: Gmail access token
            count: Number of threads to fetch

        Returns:
            Dictionary with success status and stats
        """
        try:
            stats = fetch_new_threads(user_id, user_email, access_token, count)
            return {
                "success": True,
                "stats": stats
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "require_reauth": "credentials" in str(e).lower() or "token" in str(e).lower()
            }

    @staticmethod
    def sync_existing(user_id, user_email, access_token):
        """
        Synchronize existing email threads with Gmail

        Args:
            user_id: User ID
            user_email: User email address
            access_token: Gmail access token

        Returns:
            Dictionary with success status and stats
        """
        try:
            stats = sync_existing_threads(user_id, user_email, access_token)
            return {
                "success": True,
                "stats": stats
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "require_reauth": "credentials" in str(e).lower() or "token" in str(e).lower()
            }
