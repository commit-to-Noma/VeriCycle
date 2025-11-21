# 1. Use a base image with Python
FROM python:3.11-slim

# 2. Install system tools and Node.js (needed for your Hedera scripts)
RUN apt-get update && apt-get install -y curl
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
RUN apt-get install -y nodejs

# 3. Set up the working directory
WORKDIR /app

# 4. Copy Python dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy Node.js dependencies and install them
COPY package.json .
RUN npm install

# 6. Copy the rest of your application code
COPY . .

# 7. Tell Render to run the app using Gunicorn
CMD gunicorn -w 4 -b 0.0.0.0:$PORT app:app