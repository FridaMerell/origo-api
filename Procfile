web: gunicorn origo.wsgi --worker-class gthread --workers 2 --threads 4 --timeout 60
release: python manage.py migrate --noinput && python manage.py ensure_scheduled_tasks
worker: python manage.py db_worker
