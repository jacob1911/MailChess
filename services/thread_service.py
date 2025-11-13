"""
Thread Service - Handles business logic for email threads
Single Responsibility: Thread management
"""
from models import db, Thread, Message
from sqlalchemy import func
from datetime import datetime, timezone


class ThreadService:
    """Service for managing email threads - follows Single Responsibility Principle"""

    @staticmethod
    def get_threads_for_user(user_id, user_email):
        """
        Get all threads for a user, enriched with metadata

        Args:
            user_id: User ID
            user_email: User email address

        Returns:
            List of Thread objects with added attributes (latest_message_date, other_person)
        """
        # Get threads sorted by newest message
        threads = db.session.query(Thread)\
            .filter(Thread.user_id == user_id)\
            .outerjoin(Message, Thread.id == Message.thread_id)\
            .group_by(Thread.id)\
            .order_by(func.max(Message.date).desc())\
            .all()

        # Enrich threads with computed attributes
        for thread in threads:
            ThreadService._enrich_thread(thread, user_email)

        return threads

    @staticmethod
    def _enrich_thread(thread, user_email):
        """
        Enrich thread with latest_message_date and other_person attributes

        Args:
            thread: Thread object to enrich
            user_email: Current user's email
        """
        thread.latest_message_date = None
        thread.other_person = None

        for msg in thread.messages:
            # Find latest message date
            if msg.date:
                if thread.latest_message_date is None or msg.date > thread.latest_message_date:
                    thread.latest_message_date = msg.date

            # Find other person in conversation
            if not thread.other_person:
                if msg.sender and msg.sender != user_email:
                    thread.other_person = msg.sender
                elif msg.recipient and msg.recipient != user_email:
                    thread.other_person = msg.recipient

    @staticmethod
    def get_thread_by_id(thread_id, user_id):
        """
        Get a thread by ID and verify ownership

        Args:
            thread_id: Thread ID
            user_id: User ID

        Returns:
            Thread object or None if not found/unauthorized
        """
        thread = Thread.query.get(thread_id)
        if thread and thread.user_id == user_id:
            return thread
        return None

    @staticmethod
    def create_thread(user_id, subject, gmail_thread_id=None, fen=None):
        """
        Create a new thread

        Args:
            user_id: User ID
            subject: Thread subject
            gmail_thread_id: Gmail thread ID (optional, will generate temp ID if not provided)
            fen: Chess FEN position (optional)

        Returns:
            Created Thread object
        """
        import time

        if not gmail_thread_id:
            # Generate temporary ID
            gmail_thread_id = f"temp_{user_id}_{int(time.time() * 1000)}"

        thread = Thread(
            user_id=user_id,
            gmail_thread_id=gmail_thread_id,
            subject=subject,
            fen=fen or "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            last_updated=datetime.now(timezone.utc)
        )

        db.session.add(thread)
        db.session.commit()

        return thread

    @staticmethod
    def get_thread_messages(thread_id):
        """
        Get all messages for a thread, ordered by date

        Args:
            thread_id: Thread ID

        Returns:
            List of Message objects
        """
        return Message.query.filter_by(thread_id=thread_id).order_by(Message.date.asc()).all()

    @staticmethod
    def format_message_for_api(msg):
        """
        Format a message for API response

        Args:
            msg: Message object

        Returns:
            Dictionary with formatted message data
        """
        body = msg.body_html if msg.body_html else msg.body_plain
        is_html = bool(msg.body_html)

        return {
            "id": msg.id,
            "sender": msg.sender,
            "recipient": msg.recipient,
            "body": body,
            "is_html": is_html,
            "move": msg.move,
            "timestamp": msg.date.isoformat() if msg.date else None
        }

    @staticmethod
    def clear_user_threads(user_id):
        """
        Clear all threads and messages for a user

        Args:
            user_id: User ID

        Returns:
            Dictionary with statistics (threads_deleted, messages_deleted)
        """
        threads = Thread.query.filter_by(user_id=user_id).all()
        threads_deleted = len(threads)

        messages_deleted = 0
        for thread in threads:
            messages = Message.query.filter_by(thread_id=thread.id).all()
            messages_deleted += len(messages)
            for msg in messages:
                db.session.delete(msg)
            db.session.delete(thread)

        db.session.commit()

        return {
            "threads_deleted": threads_deleted,
            "messages_deleted": messages_deleted
        }
