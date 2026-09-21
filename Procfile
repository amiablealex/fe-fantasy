web: gunicorn wsgi:app --worker-class gthread --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT
worker: python -m worker.tick
