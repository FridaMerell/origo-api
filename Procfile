web: gunicorn origo.wsgi --worker-class gevent --worker-connections 1000
release: python manage.py migrate --noinput
worker: python manage.py db_worker