"""Custom piece sets and board images: plain folders in the player's data folder (`pieces/<set>/wK.svg ... bP.svg`, `boards/<name>.png`), listed and served to the UI.
The player's own files (for example images they are allowed to use for themselves) never enter the repository. Uploads are validated: size, type, and no scripts in SVG."""
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/themes")

PIECES = [c + p for c in "wb" for p in "KQRBNP"]
EXT = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}")
MAX_BYTES = 3_000_000
BAD_SVG = re.compile(rb"<\s*script|<\s*foreignObject|\bon\w+\s*=|javascript:|<\s*iframe|<\s*embed|<\s*object|xlink:href\s*=\s*[\"']\s*https?:|href\s*=\s*[\"']\s*https?:", re.I)
MAGIC = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".webp": b"RIFF"}


def dirs(request: Request):
    d = request.app.state.config.data_dir
    return d / "pieces", d / "boards"


def check_name(name: str):
    if not NAME.fullmatch(name) or ".." in name:
        raise HTTPException(422, "use letters, digits, space, dash, underscore or dot in names")


async def read_capped(request: Request) -> bytes:
    """The request body, refused as soon as it is larger than the limit (not after it was all read into memory)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(413, "the file is larger than 3 MB")
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(413, "the file is larger than 3 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def check_content(ext: str, data: bytes):
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "the file is larger than 3 MB")
    if ext == ".svg":
        if not data.lstrip().startswith((b"<?xml", b"<svg", b"<!--", b"<!DOCTYPE")) or BAD_SVG.search(data):
            raise HTTPException(422, "that SVG is not accepted (scripts, links or embedded objects are not allowed)")
    elif not data.startswith(MAGIC[ext]):
        raise HTTPException(422, f"that file is not a real {ext[1:]} image")


@router.get("")
def list_themes(request: Request):
    pieces_dir, boards_dir = dirs(request)
    pieces = []
    if pieces_dir.is_dir():
        for d in sorted(p for p in pieces_dir.iterdir() if p.is_dir() and NAME.fullmatch(p.name)):
            files = {f.stem: f.name for f in d.iterdir() if f.suffix.lower() in EXT and f.stem in PIECES}
            if len(files) == 12:
                pieces.append({"id": d.name, "name": d.name, "files": {k: f"/api/themes/pieces/{quote(d.name)}/{quote(v)}" for k, v in files.items()}})
    boards = []
    if boards_dir.is_dir():
        boards = [{"id": f.stem, "name": f.stem, "url": f"/api/themes/boards/{quote(f.name)}"} for f in sorted(boards_dir.iterdir()) if f.suffix.lower() in EXT and NAME.fullmatch(f.name)]
    return {"pieces": pieces, "boards": boards, "pieces_dir": str(pieces_dir), "boards_dir": str(boards_dir)}


def serve(path: Path):
    if not path.is_file() or path.suffix.lower() not in EXT:
        raise HTTPException(404, "no such file")
    return FileResponse(path, media_type=EXT[path.suffix.lower()], headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})


@router.get("/pieces/{name}/{file}")
def get_piece(name: str, file: str, request: Request):
    check_name(name), check_name(file)
    return serve(dirs(request)[0] / name / file)


@router.get("/boards/{file}")
def get_board(file: str, request: Request):
    check_name(file)
    return serve(dirs(request)[1] / file)


@router.put("/pieces/{name}/{file}", status_code=204)
async def put_piece(name: str, file: str, request: Request):
    check_name(name), check_name(file)
    p = Path(file)
    if p.stem not in PIECES or p.suffix.lower() not in EXT:
        raise HTTPException(422, "piece files are named wK, wQ, wR, wB, wN, wP, bK, ... with .svg or .png")
    data = await read_capped(request)
    check_content(p.suffix.lower(), data)
    folder = dirs(request)[0] / name
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(p.stem + ".*"):                                    # one image per piece: a new extension replaces the old file
        old.unlink()
    (folder / file).write_bytes(data)
    return Response(status_code=204)


@router.put("/boards/{file}", status_code=204)
async def put_board(file: str, request: Request):
    check_name(file)
    ext = Path(file).suffix.lower()
    if ext not in EXT:
        raise HTTPException(422, "board images are .svg, .png, .jpg or .webp")
    data = await read_capped(request)
    check_content(ext, data)
    folder = dirs(request)[1]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_bytes(data)
    return Response(status_code=204)


@router.delete("/pieces/{name}", status_code=204)
def delete_pieces(name: str, request: Request):
    check_name(name)
    folder = dirs(request)[0] / name
    if not folder.is_dir():
        raise HTTPException(404, "no such set")
    for f in folder.iterdir():
        if f.is_file():
            f.unlink()
    folder.rmdir()


@router.delete("/boards/{file}", status_code=204)
def delete_board(file: str, request: Request):
    check_name(file)
    p = dirs(request)[1] / file
    if not p.is_file():
        raise HTTPException(404, "no such board")
    p.unlink()
