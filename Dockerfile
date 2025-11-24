# Use a lightweight Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install a production WSGI server (like Gunicorn) if you haven't already
# pip install gunicorn (if missing from requirements.txt)

# Copy the rest of your application code
COPY . .

# Cloud Run needs to know which port to listen on (often 8080)
EXPOSE 8080 

# Run the application using Gunicorn (assuming your app file is 'app.py')
# Change 'app:app' if your main Flask app object or file is named differently
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
