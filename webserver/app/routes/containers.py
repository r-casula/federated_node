"""
containers endpoints:
- GET /containers
- POST /containers
- GET /containers/<id>
- PATCH /containers/<id>
- POST /registries
"""

import logging
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession as DBSession

from app.helpers.base_model import get_db
from app.helpers.exceptions import UnauthorizedError
from app.helpers.query_filters import apply_filters
from app.helpers.settings import settings
from app.helpers.wrappers import Auth, audit
from app.models.container import Container
from app.models.registry import Registry
from app.schemas.containers import (
    ContainerCreate,
    ContainerFilters,
    ContainerRead,
)
from app.schemas.pagination import PageResponse
from app.services.containers import ContainerService

logger = logging.getLogger("containers_api")
logger.setLevel(logging.INFO)

router = APIRouter(tags=["containers"], prefix="/containers")


def require_image_whitelist() -> None:
    """
    Gate the container endpoints: when image whitelisting is disabled the
    container catalogue is not in use, so the endpoints are not available.
    Mirrors the upstream ``before_request`` hook and runs before auth.
    """
    if not settings.image_whitelist_enabled:
        raise UnauthorizedError("Container validation is disabled")


@router.get(
    "", dependencies=[Depends(require_image_whitelist), Depends(Auth("can_do_admin"))]
)
@audit
async def get_all_containers(
    request: Request,
    params: Annotated[ContainerFilters, Query()],
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    GET /containers endpoint.
        Returns the list of allowed containers
    """
    pagination = await apply_filters(session, Container, params)
    return PageResponse[ContainerRead].model_validate(pagination).model_dump()


@router.post(
    "",
    dependencies=[Depends(require_image_whitelist), Depends(Auth("can_do_admin"))],
    status_code=HTTPStatus.CREATED,
)
@audit
async def add_image(
    request: Request, body: ContainerCreate, session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    POST /containers endpoint.
    """
    # Make sure it doesn't exist already
    image: Container = await ContainerService.add(session, data=body)
    return ContainerRead.model_validate(image).model_dump()


@router.get(
    "/{image_id}", dependencies=[Depends(require_image_whitelist), Depends(Auth("can_do_admin"))]
)
@audit
async def get_image_by_id(
    request: Request, image_id: int, session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /containers/<image_id>
    """
    image: Container = await Container.get_by_id_or_raise(session, image_id)
    return ContainerRead.model_validate(image).model_dump()


@router.delete(
    "/{image_id}", dependencies=[Depends(require_image_whitelist), Depends(Auth("can_do_admin"))]
)
@audit
async def delete_image(
    request: Request, image_id: int, session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    DELETE /containers/<image_id>
    """
    image: Container = await Container.get_by_id_or_raise(session, image_id)
    await image.delete(session)
    return {"message": f"Image {image_id} deleted successfully"}


@router.post("/sync", dependencies=[Depends(Auth("can_do_admin"))], status_code=HTTPStatus.CREATED)
@audit
async def sync(request: Request, session: DBSession = Depends(get_db)) -> dict[str, Any]:
    """
    POST /containers/sync
        syncs up the list of available containers from the
        available registries and adds them to the DB table,
        making them part of the allowed image whitelist.
    """
    synched: list[Container] = []
    registry_query = await session.execute(select(Registry).where(Registry.active))
    for registry in registry_query.scalars().all():
        available_images = await registry.fetch_image_list()
        for image in available_images:
            for key in ["tag", "sha"]:
                for tag_or_sha in image[key]:
                    images_query = await session.execute(
                        select(Container).where(
                            Container.name == image["name"],
                            getattr(Container, key) == tag_or_sha,
                            Container.registry_id == registry.id,
                        )
                    )
                    if images_query.scalars().one_or_none():
                        logger.info("Image %s already synched", image["name"])
                        continue

                    container_data = {"name": image["name"], "registry": registry.url}
                    if key == "tag":
                        container_data["tag"] = tag_or_sha
                    else:
                        container_data["sha"] = tag_or_sha

                    cont: Container = await ContainerService.add(
                        session, ContainerCreate(**container_data), dry_run=True
                    )

                    synched.append(cont)

    session.add_all(synched)
    await session.commit()
    return {
        "info": "The sync considers only the latest 100 tag per image. If an older one is needed,"
        " add it manually via the POST /images endpoint",
        "images": [syn.full_image_name() for syn in synched],
    }
