from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/bot")


@router.get("")
def status(request: Request):
    return request.app.state.bot.status()


@router.post("/start", status_code=202)
def start(request: Request):
    why = request.app.state.bot.start()
    if why:
        raise HTTPException(409, why)
    return request.app.state.bot.status()


@router.post("/stop")
def stop(request: Request):
    if not request.app.state.bot.stop():
        raise HTTPException(409, "the bot is not running (from here)")
    return request.app.state.bot.status()
