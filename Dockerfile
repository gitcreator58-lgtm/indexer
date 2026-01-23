# Use an official lightweight Python image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose Port 8080 (Matches the port in your Python script)
EXPOSE 8080

# Command to run the bot
CMD ["python", "main.py"]
