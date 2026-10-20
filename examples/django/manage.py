#!/usr/bin/env python
"""The Django command line for the API demo: python manage.py migrate, then python manage.py runserver."""
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
