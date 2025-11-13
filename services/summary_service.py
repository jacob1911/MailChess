"""
Summary Service - Handles AI-powered conversation summarization
Single Responsibility: Generate summaries using OpenAI
"""
from openai import OpenAI
import os
import re


class SummaryService:
    """Service for generating conversation summaries - follows Single Responsibility Principle"""

    def __init__(self, api_key=None):
        """
        Initialize SummaryService with OpenAI API key

        Args:
            api_key: OpenAI API key (defaults to environment variable)
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.client = None

        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)

    def is_configured(self):
        """Check if OpenAI API is properly configured"""
        return self.client is not None

    def generate_summary(self, messages, thread_subject):
        """
        Generate a summary of the conversation using OpenAI

        Args:
            messages: List of Message objects
            thread_subject: Subject of the thread

        Returns:
            Dictionary with keys: success, summary, tokens_used, error
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "OpenAI API key not configured"
            }

        # Format conversation text
        conversation_text = self._format_conversation(messages, thread_subject)

        # Print to terminal for debugging
        print("\n\n" + conversation_text + "\n\n")

        try:
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Cost-effective model
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": f"Generer et kort referat af denne skak-email samtale:\n\n{conversation_text}"
                    }
                ],
                max_tokens=200,  # Limit response length (~150 words)
                temperature=0.7,  # Creativity level (0-2)
                presence_penalty=0.0,
                frequency_penalty=0.0
            )

            summary = response.choices[0].message.content.strip()

            # Print summary to terminal
            print("\n\n=== OPENAI REFERAT ===")
            print(summary)
            print("======================\n\n")

            return {
                "success": True,
                "summary": summary,
                "tokens_used": response.usage.total_tokens
            }

        except Exception as e:
            print(f"OpenAI Error: {str(e)}")
            return {
                "success": False,
                "error": f"OpenAI API error: {str(e)}"
            }

    def _format_conversation(self, messages, thread_subject):
        """
        Format messages into a readable conversation string

        Args:
            messages: List of Message objects
            thread_subject: Subject of the thread

        Returns:
            Formatted conversation string
        """
        lines = []
        lines.append("=" * 80)
        lines.append(f"CONVERSATION: {thread_subject}")
        lines.append("=" * 80)
        lines.append("")

        for msg in messages:
            sender = msg.sender if msg.sender else "Unknown"
            timestamp = msg.date.strftime('%d/%m/%Y %H:%M:%S') if msg.date else "No date"

            # Get message body (prefer plain text)
            if msg.body_plain:
                body = msg.body_plain
            elif msg.body_html:
                # Strip HTML tags
                body = re.sub(r'<[^>]+>', '', msg.body_html).strip()
            else:
                body = "(No content)"

            # Format message
            lines.append(f"[{timestamp}] {sender}:")
            if msg.move:
                lines.append(f"  Move: {msg.move}")
            lines.append(f"  {body}")
            lines.append("")

        lines.append("=" * 80)
        lines.append(f"Total messages: {len(messages)}")
        lines.append("=" * 80)

        return "\n".join(lines)

    def _get_system_prompt(self):
        """Get the system prompt for OpenAI"""
        return """Du er en hjælpsom assistent der laver korte, præcise referater af skak-email samtaler.

Regler for dit referat:
- Skriv på dansk
- Maksimalt 3-5 sætninger
- Fokuser på skakspillets status og vigtige træk
- Nævn hvem der spiller
- Vær kort og præcis
- Brug ikke overflødig information"""
