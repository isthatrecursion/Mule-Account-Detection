"""Stable persistence failures; never expose driver SQL/parameters as public messages."""


class PersistenceConflict(Exception):
    def __init__(self) -> None:
        super().__init__("The request conflicts with committed state.")


class LeaseLost(PersistenceConflict):
    pass


class AccessDenied(Exception):
    def __init__(self) -> None:
        super().__init__("Access to the requested resource is not permitted.")
