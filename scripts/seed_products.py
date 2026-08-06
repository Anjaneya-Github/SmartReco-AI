"""scripts/seed_products.py — Seed 20 AI/ML/tech courses via the Admin API."""
from __future__ import annotations
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(".env", override=True)

import httpx

BASE = "http://localhost:8000"

ADMIN_EMAIL    = "admin@smartreco.ai"
ADMIN_PASSWORD = "Admin1234!"

COURSES = [
    {"title": "Python for Machine Learning",
     "description": "Master Python fundamentals and essential ML libraries including NumPy, Pandas, and Scikit-learn. Build your first ML pipeline from scratch.",
     "category": "machine-learning", "difficulty": "beginner", "duration": 480,
     "price": None, "tags": ["python", "numpy", "pandas", "scikit-learn", "ml-basics"],
     "is_active": True},
    {"title": "Deep Learning with PyTorch",
     "description": "Build and train deep neural networks using PyTorch. Covers CNNs, RNNs, transformers, and production deployment patterns.",
     "category": "deep-learning", "difficulty": "intermediate", "duration": 720,
     "price": 49.99, "tags": ["pytorch", "deep-learning", "neural-networks", "cnn", "transformers"],
     "is_active": True},
    {"title": "Natural Language Processing with Transformers",
     "description": "From tokenisation to fine-tuning LLMs. Covers BERT, GPT, T5, and Hugging Face ecosystem for real-world NLP tasks.",
     "category": "nlp", "difficulty": "advanced", "duration": 900,
     "price": 79.99, "tags": ["nlp", "transformers", "bert", "gpt", "huggingface", "llm"],
     "is_active": True},
    {"title": "Computer Vision Fundamentals",
     "description": "Image classification, object detection, and segmentation using OpenCV and TensorFlow. Includes YOLO and ResNet projects.",
     "category": "computer-vision", "difficulty": "intermediate", "duration": 600,
     "price": 59.99, "tags": ["computer-vision", "opencv", "tensorflow", "yolo", "image-classification"],
     "is_active": True},
    {"title": "MLOps: Production Machine Learning",
     "description": "Deploy, monitor, and maintain ML models at scale. Covers MLflow, Docker, Kubernetes, CI/CD pipelines for ML.",
     "category": "mlops", "difficulty": "advanced", "duration": 840,
     "price": 89.99, "tags": ["mlops", "mlflow", "docker", "kubernetes", "deployment", "monitoring"],
     "is_active": True},
    {"title": "Data Science with Pandas and Matplotlib",
     "description": "Complete data analysis workflow: data cleaning, EDA, visualisation, and statistical analysis. Perfect for analysts moving into data science.",
     "category": "data-science", "difficulty": "beginner", "duration": 360,
     "price": None, "tags": ["pandas", "matplotlib", "seaborn", "eda", "statistics", "data-science"],
     "is_active": True},
    {"title": "Reinforcement Learning from Scratch",
     "description": "Build RL agents using Q-learning, policy gradients, and PPO. Environments include OpenAI Gym and custom simulations.",
     "category": "reinforcement-learning", "difficulty": "advanced", "duration": 780,
     "price": 69.99, "tags": ["reinforcement-learning", "q-learning", "ppo", "gym", "agents"],
     "is_active": True},
    {"title": "LangChain and LangGraph for AI Agents",
     "description": "Build production-grade AI applications with LangChain, LangGraph, and RAG pipelines. Covers agents, memory, and tool use.",
     "category": "generative-ai", "difficulty": "intermediate", "duration": 540,
     "price": 59.99, "tags": ["langchain", "langgraph", "rag", "agents", "llm", "openai", "vector-db"],
     "is_active": True},
    {"title": "Vector Databases and Semantic Search",
     "description": "Understand and implement semantic search using Qdrant, Pinecone, and Weaviate. Covers embedding models and retrieval-augmented generation.",
     "category": "generative-ai", "difficulty": "intermediate", "duration": 420,
     "price": 49.99, "tags": ["vector-database", "qdrant", "semantic-search", "embeddings", "rag"],
     "is_active": True},
    {"title": "FastAPI for ML Engineers",
     "description": "Build production REST APIs for serving ML models. Covers async patterns, Pydantic validation, auth, Docker deployment.",
     "category": "web-development", "difficulty": "intermediate", "duration": 480,
     "price": 39.99, "tags": ["fastapi", "python", "rest-api", "pydantic", "async", "docker"],
     "is_active": True},
    {"title": "Statistics for Data Science",
     "description": "Probability, hypothesis testing, Bayesian inference, and regression analysis. The mathematical foundation every data scientist needs.",
     "category": "data-science", "difficulty": "beginner", "duration": 540,
     "price": None, "tags": ["statistics", "probability", "hypothesis-testing", "regression", "bayesian"],
     "is_active": True},
    {"title": "TensorFlow 2 Complete Course",
     "description": "Build ML models with TensorFlow 2 and Keras. Covers classification, regression, time series, NLP, and TFLite deployment.",
     "category": "deep-learning", "difficulty": "intermediate", "duration": 660,
     "price": 54.99, "tags": ["tensorflow", "keras", "deep-learning", "tflite", "mobile-ml"],
     "is_active": True},
    {"title": "Recommender Systems: Collaborative & Content-Based",
     "description": "Build recommendation engines from scratch. Covers matrix factorisation, neural CF, knowledge graphs, and production serving.",
     "category": "machine-learning", "difficulty": "advanced", "duration": 720,
     "price": 74.99, "tags": ["recommender-systems", "collaborative-filtering", "matrix-factorization", "neural-cf"],
     "is_active": True},
    {"title": "AWS SageMaker for ML",
     "description": "Train, tune, and deploy ML models on AWS. Covers SageMaker Studio, Pipelines, Feature Store, and Model Monitor.",
     "category": "mlops", "difficulty": "intermediate", "duration": 600,
     "price": 64.99, "tags": ["aws", "sagemaker", "cloud-ml", "mlops", "deployment"],
     "is_active": True},
    {"title": "Feature Engineering for Machine Learning",
     "description": "Transform raw data into powerful features. Covers encoding, scaling, imputation, feature selection, and automated feature engineering.",
     "category": "machine-learning", "difficulty": "intermediate", "duration": 420,
     "price": 44.99, "tags": ["feature-engineering", "data-preprocessing", "feature-selection", "ml-pipeline"],
     "is_active": True},
    {"title": "Generative AI with Stable Diffusion",
     "description": "Create images, fine-tune diffusion models, and build AI art pipelines with Stable Diffusion, ControlNet, and LoRA.",
     "category": "generative-ai", "difficulty": "intermediate", "duration": 480,
     "price": 49.99, "tags": ["stable-diffusion", "generative-ai", "image-generation", "controlnet", "lora"],
     "is_active": True},
    {"title": "Time Series Forecasting with Python",
     "description": "ARIMA, Prophet, LSTM, and Transformer models for time series. Covers anomaly detection, demand forecasting, and financial analysis.",
     "category": "data-science", "difficulty": "intermediate", "duration": 540,
     "price": 54.99, "tags": ["time-series", "forecasting", "arima", "prophet", "lstm", "anomaly-detection"],
     "is_active": True},
    {"title": "Explainable AI and Model Interpretability",
     "description": "Understand black-box models with SHAP, LIME, and attention visualisation. Essential for regulated industries and responsible AI.",
     "category": "machine-learning", "difficulty": "advanced", "duration": 360,
     "price": 44.99, "tags": ["xai", "shap", "lime", "interpretability", "responsible-ai", "model-explanation"],
     "is_active": True},
    {"title": "SQL for Data Analysis",
     "description": "Master SQL from basics to advanced window functions, CTEs, and performance optimisation. Includes PostgreSQL and real business datasets.",
     "category": "data-science", "difficulty": "beginner", "duration": 300,
     "price": None, "tags": ["sql", "postgresql", "data-analysis", "window-functions", "cte"],
     "is_active": True},
    {"title": "Graph Neural Networks",
     "description": "Learn GNNs for social networks, molecular property prediction, and knowledge graphs. Covers GCN, GAT, GraphSAGE with PyTorch Geometric.",
     "category": "deep-learning", "difficulty": "advanced", "duration": 600,
     "price": 69.99, "tags": ["gnn", "graph-neural-networks", "pytorch-geometric", "knowledge-graph", "molecular"],
     "is_active": True},
]


def get_token() -> str:
    r = httpx.post(f"{BASE}/api/v1/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                   timeout=10)
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    token = r.json()["access_token"]
    print(f"Logged in as {ADMIN_EMAIL}")
    return token


def seed(token: str) -> None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    ok = 0
    # Use a persistent client with long timeout — first call loads the embedding model (~30s)
    with httpx.Client(timeout=120) as client:
        for course in COURSES:
            r = client.post(f"{BASE}/api/v1/admin/products",
                            json=course, headers=headers)
            if r.status_code == 201:
                print(f"  OK  {course['title']}")
                ok += 1
            else:
                print(f"  FAIL [{r.status_code}]  {course['title']}  {r.text[:100]}")
    print(f"\n{ok}/{len(COURSES)} products seeded.")


if __name__ == "__main__":
    print("Seeding products…")
    token = get_token()
    seed(token)
