"""Scoped database query helper enforcing SEC-01 and Design Rule 2.

Invariants:
- Customer access is strictly bounded to the customer's own identity.
- Knowing a record ID (case_id, payment_id, order_id) grants zero access if out-of-scope.
- Deny by default.
"""
from typing import Type, TypeVar, Optional, Any
from sqlalchemy.orm import Session, Query
from sqlalchemy import false

from app.models.user import User, UserRole

T = TypeVar("T")


class AuthorizationError(PermissionError):
    """Raised when an operation violates role or boundary scoping."""
    pass


def scoped_query(db: Session, model: Type[T], user: User) -> Query[T]:
    """Return a SQLAlchemy Query strictly scoped to the authenticated user.

    Args:
        db: Active database session.
        model: SQLAlchemy model class.
        user: Authenticated user entity.

    Returns:
        Query scoped by customer boundary or merchant role.

    Raises:
        AuthorizationError: If an unauthorized access pattern or unknown role is encountered.
    """
    if user is None:
        raise AuthorizationError("Access denied: Unauthenticated user.")

    # Customer scope: strictly restricted to their own records
    if user.role == UserRole.CUSTOMER:
        if hasattr(model, "customer_id"):
            return db.query(model).filter(getattr(model, "customer_id") == user.id)
        elif model == User or (hasattr(model, "__tablename__") and model.__tablename__ == "users"):
            return db.query(model).filter(getattr(model, "id") == user.id)
        else:
            # Deny by default: customers cannot query models without customer context
            raise AuthorizationError(
                f"Access denied: Customer cannot access model '{getattr(model, '__name__', str(model))}'."
            )

    # Agent and Reviewer scope: authorized within merchant operations
    elif user.role in (UserRole.AGENT, UserRole.REVIEWER):
        return db.query(model)

    # Deny by default for any unknown role
    raise AuthorizationError(f"Access denied: Unrecognized role '{user.role}'.")


def get_scoped_record(
    db: Session,
    model: Type[T],
    record_id: Any,
    user: User
) -> Optional[T]:
    """Retrieve a single record strictly within the user's authorized scope.

    A known record ID grants nothing if it belongs to another customer.
    """
    query = scoped_query(db, model, user)
    return query.filter(getattr(model, "id") == record_id).first()
