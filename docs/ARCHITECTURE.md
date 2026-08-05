# Architecture

Frontend

Jinja2

Bootstrap

JavaScript

↓

FastAPI

↓

PostgreSQL

↓

LangGraph

↓

Mesh API

↓

Qdrant

↓

Recommendation Storage

↓

Dashboard

                       SmartReco AI

                +----------------------+
                |   Browser (Jinja2)   |
                +----------------------+
                           |
                           |
                   Event Collector JS
                           |
                Batch Every 5 Seconds
                           |
                           ▼
                 FastAPI Backend
      ------------------------------------
      Auth
      Product CRUD
      Event API
      Recommendation API
      Admin
      ------------------------------------
             |                    |
             |                    |
             ▼                    ▼
      PostgreSQL             Recommendation Agent
             |                    |
             |                    |
             |              LangGraph Workflow
             |                    |
             |                    ▼
             |             Mesh API (GPT)
             |                    |
             ▼                    ▼
      Recommendation Table   Qdrant Vector DB