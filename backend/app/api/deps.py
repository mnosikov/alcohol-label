from typing import Annotated

from fastapi import Depends, Header, HTTPException

from backend.app.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
ReviewTokenHeader = Annotated[str | None, Header()]


def require_review_token(
    settings: SettingsDep,
    x_review_token: ReviewTokenHeader = None,
) -> None:
    if settings.review_token_required and x_review_token != settings.review_token:
        raise HTTPException(status_code=401, detail="Review token required")
