# HROne SWE Trainee Assessment

This project implements an employee attendance management API using FastAPI and MongoDB.

## Technologies Used

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic

## Features

- Employee creation and listing
- Attendance punch-in and punch-out
- Attendance record listing and regularization
- Employee monthly attendance analytics
- Department summary and trend analytics
- Late-arrival leaderboard
- Query execution plan inspection through the explain endpoint

## Prerequisites

- Python 3.10 or newer
- MongoDB 6.0 or newer

## Setup and Installation

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure the MongoDB connection using `MONGO_URI` and `MONGO_DB` environment variables. You can use a local `.env` file for development, but do not commit it to GitHub.

## Run the Application

From the project root directory, run:

```bash
python -m uvicorn app.main:app --port 8000
```

## API Documentation and Testing

After starting the application, open the following URLs:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/health

Use Swagger UI to send requests and inspect API responses.

## Validation

Check the Python syntax using:

```bash
python -m py_compile app/main.py
```

## Submission

The repository contains the application code, dependency list, and assessment documentation (`REVIEW.md` and `DECISIONS.md`).

Do not commit `.env` files, credentials, virtual environments, or database dumps.