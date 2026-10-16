FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY token_accounting.py context_compactor.py retired_knowledge.py app.py project_search.py obsidian_tasks.py register.py checkpoints.py herald_status.py export-herald-status.py handoff_prompt.md debrief_prompt.md synthesise.py ./
COPY templates/ templates/
COPY static/ static/
EXPOSE 5000
# Single worker: background jobs are in-process threads. No --preload.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", \
     "--timeout", "120", "app:app"]
