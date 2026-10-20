"""One business operation, one transaction; exceptions (including commit failures) roll back."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def unit_of_work(factory: Callable[[], Session]) -> Iterator[Session]:
    with factory() as session, session.begin():
        yield session
