"""Сквозной контекст: чей это LLM-вызов и в каком бюджет-режиме юзер."""
from contextlib import contextmanager
from contextvars import ContextVar

current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
budget_mode: ContextVar[str] = ContextVar("budget_mode", default="ok")  # 'ok'|'econom'


@contextmanager
def use_user(user_id: int | None):
    token = current_user_id.set(user_id)
    try:
        yield
    finally:
        current_user_id.reset(token)


@contextmanager
def use_budget_mode(mode: str):
    token = budget_mode.set(mode)
    try:
        yield
    finally:
        budget_mode.reset(token)
