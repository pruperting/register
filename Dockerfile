FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py register.py handoff_prompt.md synthesise.py ./
COPY templates/ templates/
COPY static/ static/
EXPOSE 5000
# Single worker: background jobs are in-process threads. No --preload.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", \
     "--timeout", "120", "app:app"]
