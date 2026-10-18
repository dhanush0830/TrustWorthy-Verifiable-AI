"""Scoped database query helper enforcing SEC-01 and Design Rule 2.

Invariants:
- Customer access is strictly bounded to the customer's own identity.
- Knowing a record ID (case_id, payment_id, order_id) grants zero access if out-of-scope.
- Deny by default.
"""
from typing import Any, TypeVar

from sqlalchemy.orm import Query, Session

from app.models.user import User, UserRole

T = TypeVar("T")


class AuthorizationError(PermissionError):
    """Raised when an operation violates role or boundary scoping."""


def scoped_query(db: Session, model: type[T], user: User) -> Query[T]:
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
            cust_col = getattr(model, "customer_id")
            return db.query(model).filter(cust_col == user.id)
        elif model == User or (hasattr(model, "__tablename__") and getattr(model, "__tablename__", None) == "users"):
            id_col = getattr(model, "id")
            return db.query(model).filter(id_col == user.id)
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
    model: type[T],
    record_id: Any,
    user: User
) -> T | None:
    """Retrieve a single record strictly within the user's authorized scope.

    A known record ID grants nothing if it belongs to another customer.
    """
    query = scoped_query(db, model, user)
    id_col = getattr(model, "id")
    return query.filter(id_col == record_id).first()
