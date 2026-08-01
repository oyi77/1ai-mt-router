import multiprocessing
import os

bind = "0.0.0.0:8080"
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
worker_class = "uvicorn.workers.UvicornWorker"
# Declare the worker role so background tasks like the metrics collector
# run under a predictable role (a future scheduler can set ROLE=scheduler).
raw_env = ["ROLE=worker"]
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
accesslog = "-"
errorlog = "-"
loglevel = "info"
