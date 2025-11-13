"""
Label Service - Handles business logic for custom labels
Single Responsibility: Label management
"""
from models import db, CustomLabel, Message
from werkzeug.utils import secure_filename
from flask import current_app
import os
import time


class LabelService:
    """Service for managing custom labels - follows Single Responsibility Principle"""

    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

    @staticmethod
    def get_user_labels(user_id):
        """
        Get all custom labels for a user

        Args:
            user_id: User ID

        Returns:
            List of CustomLabel objects
        """
        return CustomLabel.query.filter_by(user_id=user_id).order_by(CustomLabel.created_at.desc()).all()

    @staticmethod
    def format_label_for_api(label):
        """
        Format a label for API response

        Args:
            label: CustomLabel object

        Returns:
            Dictionary with label data
        """
        return {
            "id": label.id,
            "name": label.name,
            "display_name": label.display_name,
            "icon_path": label.icon_path,
            "color": label.color
        }

    @staticmethod
    def create_label(user_id, display_name, color='#6B7280', icon_file=None):
        """
        Create a new custom label

        Args:
            user_id: User ID
            display_name: Display name for the label
            color: Hex color code
            icon_file: Optional file upload object

        Returns:
            Tuple of (CustomLabel object, error_message)
            error_message is None if successful
        """
        # Validate input
        if not display_name:
            return None, "Display name is required"

        # Generate internal name (uppercase, no spaces)
        name = display_name.upper().replace(' ', '_')

        # Check if label already exists
        existing = CustomLabel.query.filter_by(user_id=user_id, name=name).first()
        if existing:
            return None, f"Label '{display_name}' already exists"

        # Handle icon upload
        icon_path = None
        if icon_file and icon_file.filename:
            icon_path, error = LabelService._save_icon(user_id, icon_file)
            if error:
                return None, error

        # Create label
        try:
            new_label = CustomLabel(
                user_id=user_id,
                name=name,
                display_name=display_name,
                icon_path=icon_path,
                color=color
            )
            db.session.add(new_label)
            db.session.commit()
            return new_label, None

        except Exception as e:
            db.session.rollback()
            return None, f"Failed to create label: {str(e)}"

    @staticmethod
    def _save_icon(user_id, icon_file):
        """
        Save icon file to upload folder

        Args:
            user_id: User ID
            icon_file: File upload object

        Returns:
            Tuple of (icon_path, error_message)
        """
        if not LabelService._allowed_file(icon_file.filename):
            return None, "Invalid file type"

        filename = secure_filename(icon_file.filename)
        # Add user_id and timestamp to make filename unique
        unique_filename = f"{user_id}_{int(time.time())}_{filename}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)

        try:
            icon_file.save(filepath)
            # Return relative path for web access
            return f"/static/label_icons/{unique_filename}", None
        except Exception as e:
            return None, f"Failed to save icon: {str(e)}"

    @staticmethod
    def _allowed_file(filename):
        """Check if file extension is allowed"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in LabelService.ALLOWED_EXTENSIONS

    @staticmethod
    def delete_label(label_id, user_id):
        """
        Delete a custom label

        Args:
            label_id: Label ID
            user_id: User ID (for authorization)

        Returns:
            Tuple of (success: bool, error_message: str or None)
        """
        label = CustomLabel.query.get(label_id)

        if not label:
            return False, "Label not found"

        if label.user_id != user_id:
            return False, "Unauthorized"

        try:
            # Delete icon file if exists
            if label.icon_path:
                LabelService._delete_icon_file(label.icon_path)

            # Remove label from all messages
            LabelService._remove_label_from_messages(user_id, label.name)

            # Delete label
            db.session.delete(label)
            db.session.commit()

            return True, None

        except Exception as e:
            db.session.rollback()
            return False, f"Failed to delete label: {str(e)}"

    @staticmethod
    def _delete_icon_file(icon_path):
        """Delete icon file from filesystem"""
        try:
            # Extract filename from path (/static/label_icons/filename.png)
            filename = icon_path.split('/')[-1]
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            print(f"Warning: Failed to delete icon file: {e}")

    @staticmethod
    def _remove_label_from_messages(user_id, label_name):
        """Remove label from all user messages"""
        messages = Message.query.filter_by(user_id=user_id).all()
        for msg in messages:
            if msg.label_ids:
                labels = [l.strip() for l in msg.label_ids.split(',')]
                if label_name in labels:
                    labels.remove(label_name)
                    msg.label_ids = ','.join(labels) if labels else None
        db.session.commit()
