"""Scheduled work that runs outside a request.

Each module here is entered with `python -m jobs.<name>` from a Railway cron
service running the same image and environment variables as the API, so DEV and
PROD stay isolated with no extra credential to manage.

Nothing in here may be imported by a route handler. A job is allowed to take
minutes and to touch every case in the book; a request is not.
"""
