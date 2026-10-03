import os

os.environ["DJANGO_ENV"] = "test"

from .settings import *  # noqa: F403