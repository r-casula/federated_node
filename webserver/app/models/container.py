from sqlalchemy import ForeignKey, Integer, String, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.helpers.base_model import BaseModel
from app.models.registry import Registry


class Container(BaseModel):  # pylint: disable=missing-class-docstring
    __tablename__ = "containers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    tag: Mapped[str] = mapped_column(String(256), nullable=True)
    sha: Mapped[str] = mapped_column(String(256), nullable=True)

    registry_id: Mapped[int] = mapped_column(Integer, ForeignKey(Registry.id, ondelete="CASCADE"))
    registry: Mapped["Registry"] = relationship("Registry", back_populates="containers")

    def full_image_name(self) -> str:
        """Composes the registry/image name:tag or sha"""
        if self.sha:
            return f"{self.registry.url}/{self.name}@{self.sha}"

        return f"{self.registry.url}/{self.name}:{self.tag}"

    @classmethod
    async def validate_image_whitelisted(cls, session: AsyncSession, docker_image: str) -> bool:
        """
        Validate that the image is whitelisted in the database based on the following criteria:
        - Image-only: Neither tag nor SHA specified in DB (allows all versions).
        - Tag-only: Tag specified but no SHA in DB (allows matching tag).
        - SHA-restricted: SHA specified (and optionally tag) in DB (allows matching SHA/tag).

        If not immediately whitelisted, it resolves tags to SHAs remotely to check against
        SHA-restricted entries.
        """
        registry, name, tag, sha = await Registry.extract_image_parts(session, docker_image)
        base_filters = [Container.name == name, Container.registry_id == registry.id]

        # Static whitelist checks (no registry call needed)
        checks = [and_(Container.tag.is_(None), Container.sha.is_(None))]
        if sha:
            checks.append(
                and_(Container.sha == sha, or_(Container.tag.is_(None), Container.tag == tag))
            )
        elif tag:
            checks.append(and_(Container.tag == tag, Container.sha.is_(None)))

        static_q = select(Container).where(*base_filters).where(or_(*checks))
        if (await session.execute(static_q)).scalars().first():
            return True

        # Resolve tag to SHA if SHA-restricted entries exist for this image
        if tag and not sha:
            sha_restricted_q = select(Container).where(*base_filters).where(Container.sha.is_not(None))
            if (await session.execute(sha_restricted_q)).scalars().first():
                registry_client = await registry.get_registry_class()
                remote_sha = registry_client.get_tag_sha(name, tag)
                if remote_sha:
                    resolved_q = (
                        select(Container)
                        .where(*base_filters)
                        .where(
                            Container.sha == remote_sha,
                            or_(Container.tag.is_(None), Container.tag == tag),
                        )
                    )
                    if (await session.execute(resolved_q)).scalars().first():
                        return True

        return False
