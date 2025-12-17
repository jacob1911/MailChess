#!/usr/bin/env python3
"""
Setup script to generate environ.env with required configuration.
Run this before starting the app.
"""

import os
import secrets
import sys

ENV_FILE = "environ.env"
EXAMPLE_FILE = "environ.env.example"

def generate_secret_key():
    """Generate a secure random secret key for Flask"""
    return secrets.token_hex(32)

def create_environ_file():
    """Create environ.env with required keys"""
    
    if os.path.exists(ENV_FILE):
        print(f"✓ {ENV_FILE} already exists. Skipping creation.")
        return
    
    print(f"Generating {ENV_FILE}...")
    
    # Generate Flask secret key
    flask_secret = generate_secret_key()
    
    # Template content with emphasis on shared OpenAI key
    content = f"""# MailChess Environment Configuration
# Generated automatically on {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

# Flask Secret Key (auto-generated - do not share)
FLASK_SECRET_KEY={flask_secret}

# Google OAuth (get from https://console.cloud.google.com/)
# Create OAuth 2.0 credentials (Desktop application)
# Add http://127.0.0.1:5000/ and http://127.0.0.1:5000/auth/callback as Authorized redirect URIs
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# OpenAI API Key
# ⚠️  IMPORTANT: Use the shared OpenAI API key provided by the team.
# This key has paid tokens that are shared for development.
# DO NOT create a new personal key - use the team's key instead!
# Contact the development team if you need the key.
OPENAI_API_KEY=sk-proj-your-team-openai-api-key
"""
    
    try:
        with open(ENV_FILE, 'w') as f:
            f.write(content)
        print(f"✓ Created {ENV_FILE}")
        print(f"\n⚠️  IMPORTANT: You must fill in the missing credentials:")
        print(f"   1. GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from Google Cloud Console")
        print(f"   2. OPENAI_API_KEY - Use the SHARED team key (not your own!)")
        print(f"\n   See comments in {ENV_FILE} for instructions.")
        return True
    except Exception as e:
        print(f"✗ Error creating {ENV_FILE}: {e}", file=sys.stderr)
        return False

def create_example_file():
    """Create environ.env.example as a template (for git)"""
    
    example_content = """# MailChess Environment Configuration Template
# Copy this file to environ.env and fill in your actual credentials
# DO NOT COMMIT environ.env to git (it's in .gitignore)

# Flask Secret Key (auto-generated during setup)
FLASK_SECRET_KEY=your-generated-secret-key

# Google OAuth (get from https://console.cloud.google.com/)
# Create OAuth 2.0 credentials (Desktop application)
# Add http://127.0.0.1:5000/ and http://127.0.0.1:5000/auth/callback as Authorized redirect URIs
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# OpenAI API Key (get from https://platform.openai.com/account/api-keys)
OPENAI_API_KEY=sk-proj-your-openai-api-key
"""
    
    if os.path.exists(EXAMPLE_FILE):
        return  # Already exists
    
    try:
        with open(EXAMPLE_FILE, 'w') as f:
            f.write(example_content)
        print(f"✓ Created {EXAMPLE_FILE} (for reference)")
    except Exception as e:
        print(f"✗ Error creating {EXAMPLE_FILE}: {e}", file=sys.stderr)

def main():
    print("=" * 60)
    print("MailChess Environment Setup")
    print("=" * 60)
    print()
    
    create_example_file()
    success = create_environ_file()
    
    print()
    if success:
        print("=" * 60)
        print("Setup complete! Next steps:")
        print("=" * 60)
        print("1. Open environ.env and fill in your API credentials")
        print("2. Run: start.bat (Windows) or python app.py (direct run)")
        print("=" * 60)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
