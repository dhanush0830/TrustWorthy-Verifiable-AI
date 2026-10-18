"""Main FastAPI application entrypoint for Trustworthy and Verifiable AI."""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.investigate import router as investigate_router
from app.api.payments import router as payments_router
from app.core.config import get_settings
from app.db.scoped import AuthorizationError

settings = get_settings()

app = FastAPI(
    title="Trustworthy and Verifiable AI",
    description="Deterministic AI Complaint Investigation Platform",
    version="0.1.0",
)

# CORS configuration supporting local development and production Vercel origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AuthorizationError)
async def authorization_exception_handler(request: Request, exc: AuthorizationError):
    """Handle scoped authorization failures as 403 Forbidden."""
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc)},
    )


@app.get("/health", tags=["system"])
def health_check():
    """System health check endpoint."""
    return {
        "status": "ok",
        "project": "Trustworthy and Verifiable AI",
        "version": "0.1.0",
    }


# Include API routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(cases_router, prefix=settings.API_V1_STR)
app.include_router(payments_router, prefix=settings.API_V1_STR)
app.include_router(investigate_router, prefix=settings.API_V1_STR)
