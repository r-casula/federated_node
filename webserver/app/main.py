"""
Entrypoint for the webserver.
All general configs are taken care in here:
    - Exception handlers
    - Blueprint used
    - pre and post request handlers
"""
import logging
import traceback
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import exc
from werkzeug.exceptions import HTTPException

from app.helpers.exceptions import LogAndException
from app.helpers.base_model import get_db
from app.routes import (
    general, admin, users, datasets, containers, tasks, registries
)



logging.basicConfig(level=logging.WARN)
logger = logging.getLogger('main')
logger.setLevel(logging.INFO)


app = FastAPI()

async def exception_handler(_request, e:Exception) -> JSONResponse:
    """Exception wrapper for customs, and HTTPException so the format is consistent"""
    error_response = {"error": getattr(e, "description", str(e))}
    extra_fields = getattr(e, "extra_fields", None)
    if extra_fields:
        error_response["details"] = extra_fields
    return JSONResponse(error_response, status_code=getattr(e, 'code', 500))

app.add_exception_handler(LogAndException, exception_handler)
app.add_exception_handler(HTTPException, exception_handler)

# Need to register the exception handler this way as we need access
# to the db session
@app.exception_handler(exc.IntegrityError)
async def handle_db_exceptions(_request, excp:exc.IntegrityError) -> JSONResponse:
    """
    Exception wrapper for DB exceptions so the format is consistent, and session is rolledback
    """
    logging.error(excp)
    with get_db() as db:
        db.rollback()
    return JSONResponse({"error": "Record already exists"}, status_code=500)

@app.exception_handler(RequestValidationError)
# Special case, just so we won't return stacktraces
async def pydandic_validation_handler(_request, e:RequestValidationError) -> JSONResponse:
    """Wrapper for error messages on pydantic validation errors"""
    list_of_messages = []
    for err in e.errors():
        list_of_messages.append({
            "type": err["type"],
            "field": err["loc"],
            "message": err["msg"]
        })
    return JSONResponse({"error": list_of_messages}, status_code=400)

@app.exception_handler(Exception)
# Special case, just so we won't return stacktraces
async def unknown_exception_handler(_request, e:Exception) -> JSONResponse:
    """Any other exception is handled here"""
    logger.error("\n".join(traceback.format_exception(e)))
    with get_db() as db:
        db.rollback()
    return JSONResponse({"error": "Internal Error"}, status_code=500)

app.include_router(admin.router)
app.include_router(containers.router)
app.include_router(datasets.router)
app.include_router(general.router)
app.include_router(registries.router)
app.include_router(tasks.router)
app.include_router(users.router)
