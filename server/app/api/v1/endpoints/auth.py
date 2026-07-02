"""
Authentication endpoints (session-cookie based).
"""
from fastapi import APIRouter, Request, Response, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.deps import DbSession, get_optional_user
from app.services.auth_service import AuthService
from app.core.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    session: DbSession = None,
):
    svc = AuthService(session)
    user = await svc.authenticate(username, password)
    if not user:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )

    token = svc.make_session_token(user)
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(settings.SESSION_COOKIE_NAME)
    return resp