"""
재료 최저가 발주 도우미 — 웹 서버

실행:  uvicorn server:app --reload --port 8000   (order_app 폴더에서)
환경변수:
  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET  네이버 개발자센터에서 발급 (없으면 샘플 데이터)
  ACCESS_CODE                            (선택) 설정하면 이 코드를 아는 사람만 검색 가능
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import shopping

BASE = Path(__file__).parent
app = FastAPI(title="재료 최저가 발주 도우미")


def _check_access(code: str | None) -> None:
    expected = os.getenv("ACCESS_CODE")
    if expected and not hmac.compare_digest(code or "", expected):
        raise HTTPException(status_code=401, detail="접속 코드가 필요합니다.")


@app.get("/api/status")
def status():
    return {
        "naver_configured": shopping.has_credentials(),
        "access_code_required": bool(os.getenv("ACCESS_CODE")),
    }


@app.get("/api/search")
async def search(
    q: str = Query(..., min_length=1, max_length=100),
    exclude: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=50),
    x_access_code: str | None = Header(default=None),
):
    _check_access(x_access_code)
    exclude_words = [w.strip() for w in exclude.split(",") if w.strip()]
    try:
        return await shopping.search_lowest(q, exclude_words, limit)
    except shopping.SearchError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static"), name="static")
