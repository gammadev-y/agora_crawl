# Use the official Playwright image, which includes all necessary browser dependencies.
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set the working directory inside the container.
WORKDIR /app

# Copy the Python dependency file.
COPY requirements.txt .

# Install the Python dependencies. The `playwright install` command is crucial.
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps

# Copy the rest of the application code into the container.
COPY . .

# Ensure the current directory is in Python path for module imports
ENV PYTHONPATH=/app
ENV PYTHONPATH=${PYTHONPATH}:/app

# Define the entrypoint that will be executed when the container starts.
# This allows arguments to be passed to the python command.
ENTRYPOINT ["python", "main.py"]