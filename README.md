# Ticket Management System with AI RAG & Token Dashboard

This repository implements an end-to-end automated email ticketing system that parses incoming queries, runs zero-shot classification, queries pgvector for similar resolved references, validates generated response drafts against guardrails, and aggregates token metrics on a sleek dark-mode dashboard.

---

## Setup & Startup Instructions

Follow these steps to run the complete stack (databases, background jobs, FastAPI backend, and dashboard client interface) with a single command:

1. **Clone the repository**:
   ```bash
   git clone <repository_url>
   cd ticket
   ```

2. **Configure your Environment**:
   Copy the example environment configuration:
   ```bash
   cp .env.example .env
   ```
   Open the newly created `.env` file and insert your active API credentials (such as your `OPENROUTER_API_KEY` and Gmail OAuth2 configuration credentials).

3. **Start the Application Stack**:
   Start all containers (Postgres + pgvector, Redis, MinIO, FastAPI Backend, Celery Worker, Nginx Frontend Dashboard) in detached mode:
   ```bash
   docker compose up -d
   ```

4. **Access the Dashboard**:
   Open your browser and navigate to:
   **[http://localhost:5173](http://localhost:5173)**
