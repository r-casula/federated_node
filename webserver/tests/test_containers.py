from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
from pytest import mark, raises
from pytest_asyncio import fixture
from sqlalchemy import select, update

from app.helpers.exceptions import ContainerRegistryException, InvalidRequest
from app.models.container import Container
from app.models.registry import Registry
from app.schemas.containers import ContainerCreate
from app.services.containers import ContainerService
from tests.base_test_class import BaseTest
from tests.fixtures.azure_cr_fixtures import *


@fixture(scope='function')
def container_body(registry):
    return deepcopy({
        "name": "",
        "registry": registry.url,
        "tag": "1.2.3"
    })


class ContainersMixin(BaseTest):
    def get_container_as_response(self, container: Container):
        return {
            "id": container.id,
            "name": container.name,
            "tag": container.tag,
            "sha": container.sha,
            "registry_id": container.registry_id
        }


class TestContainerFormat(ContainersMixin):
    @mark.asyncio
    async def test_docker_image_regex(
        self,
        container_body,
        registry_client,
        mocker,
        client
    ):
        """
        Tests that the docker image is in an expected format
            <namespace?/image>:<tag>
        """
        valid_image_formats = [
            {"name": "image", "tag": "3.21"},
            {"name": "image", "sha": "sha256:1234ab15ad48"},
            {"name": "namespace/image", "tag": "3.21"},
            {"name": "namespace/image", "tag": "3.21-alpha"}
        ]
        invalid_image_formats = [
            {"name": "not_valid/"},
            {"name": "/not-valid", "tag": ""},
            {"name": "/not-valid"},
            {"name": "image", "tag": ""},
            {"name": "namespace//image"},
            {"name": "not_valid/"}
        ]
        mocker.patch(
            'app.models.task.Keycloak.create',
            return_value=AsyncMock()
        )
        for im_format in valid_image_formats:
            container_body.update(im_format)
            ContainerCreate(**container_body)

        for im_format in invalid_image_formats:
            container_body["name"] = im_format
            with raises(InvalidRequest):
                ContainerCreate(**container_body)


@mark.parametrize("enable_image_whitelist", [True, False])
class TestContainers(ContainersMixin):
    """
    The container endpoints are only available when image whitelisting is
    enabled. Each test is parametrized over the flag being on/off, and the
    autouse fixture patches the ``settings`` value accordingly.
    """

    @fixture(autouse=True)
    def setup_validation(self, mocker, enable_image_whitelist):
        mocker.patch(
            "app.helpers.settings.settings.enable_image_whitelist", enable_image_whitelist
        )

    @mark.asyncio
    async def test_get_all_containers(
        self,
        client,
        container,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test for returning a correct response body on GET /containers
        """
        resp = await client.get("/containers", headers=post_json_admin_header)
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 200
        assert resp.json()["items"] == [self.get_container_as_response(container)]

    @mark.asyncio
    async def test_get_all_containers_non_auth(
        self,
        client,
        container,
        enable_image_whitelist,
        simple_user_header,
        mock_kc_client_wrapper,
        base_kc_mock_args
    ):
        """
        Basic test to make sure only admin users can use the endpoint.
        Both the gate (disabled) and the auth wrapper (enabled) return 403.
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.get("/containers", headers=simple_user_header)
        assert resp.status_code == 403

    @mark.asyncio
    async def test_get_container_by_id(
        self,
        client,
        container,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test to make sure the response body has the expected format
        """
        resp = await client.get(
            f"/containers/{container.id}",
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 200
        assert resp.json() == self.get_container_as_response(container)

    @mark.asyncio
    async def test_get_container_by_id_404(
        self,
        client,
        container,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Requesting a non existing container returns a 404
        """
        resp = await client.get(
            f"/containers/{container.id + 1}",
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 404
        assert resp.json()["error"] == f'Container with id {container.id + 1} does not exist'

    @mark.asyncio
    async def test_get_container_by_id_non_auth(
        self,
        client,
        container,
        enable_image_whitelist,
        simple_user_header,
        mock_kc_client_wrapper,
        base_kc_mock_args
    ):
        """
        Basic test to make sure only admin users can use the endpoint
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.get(
            f"/containers/{container.id}",
            headers=simple_user_header
        )
        assert resp.status_code == 403

    @mark.asyncio
    async def test_delete_container(
        self,
        client,
        container,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Basic test for DELETE /containers/<image_id>
        """
        resp = await client.delete(
            f"/containers/{container.id}",
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 200
        assert await self.run_query(
            select(Container).where(Container.id == container.id), "one_or_none"
        ) is None

    @mark.asyncio
    async def test_delete_container_404(
        self,
        client,
        container,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        DELETE /containers/<image_id> with a non-existent id returns 404
        """
        resp = await client.delete(
            f"/containers/{container.id + 1}",
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 404

    @mark.asyncio
    async def test_delete_container_non_auth(
        self,
        client,
        container,
        enable_image_whitelist,
        simple_user_header,
        mock_kc_client_wrapper,
        base_kc_mock_args
    ):
        """
        DELETE /containers/<image_id> with a non-admin user returns 403
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.delete(
            f"/containers/{container.id}",
            headers=simple_user_header
        )
        assert resp.status_code == 403

    @mark.asyncio
    async def test_add_new_container(
        self,
        client,
        registry,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST body is what we expect
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url,
                "tag": "1.0.25"
            },
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 201, resp.json()
        assert await self.run_query(select(Container).where(
            Container.name == "testimage", Container.tag == "1.0.25"
        ), "one_or_none") is not None

    @mark.asyncio
    async def test_add_new_container_by_sha(
        self,
        client,
        registry,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST body is what we expect when a sha is provided
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url,
                "sha": "sha256:123123123"
            },
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 201
        assert await self.run_query(select(Container).where(
            Container.name == "testimage", Container.sha == "sha256:123123123"
        ), "one_or_none") is not None

    @mark.asyncio
    async def test_add_duplicate_container(
        self,
        client,
        registry,
        container,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST request returns a 409 with a duplicate container entry
        """
        data = self.get_container_as_response(container)
        data["registry"] = registry.url
        resp = await client.post(
            "/containers",
            json=data,
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 409
        assert resp.json()["error"] == \
            f'Image {container.name} with {container.tag} already exists in the registry'

    @mark.asyncio
    async def test_add_new_container_missing_field(
        self,
        client,
        registry,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST body is processed and returns an error if a required
        field is missing
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": registry.url
            },
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 400
        assert resp.json()["error"] == 'Make sure `tag` or `sha` are provided'

    @mark.asyncio
    async def test_add_new_container_invalid_registry(
        self,
        client,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Checks the POST request fails if the registry needed is not on record
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "testimage",
                "registry": "notreal",
                "tag": "0.0.1"
            },
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 500
        assert resp.json()["error"] == 'Registry notreal could not be found'

    @mark.asyncio
    async def test_container_name_invalid_format(
        self,
        client,
        registry,
        enable_image_whitelist,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        If a tag is in an non supported format, return an error.
        Most of the model validations are done in a previous test;
        here we verify the API returns the correct message.
        """
        resp = await client.post(
            "/containers",
            json={
                "name": "/testimage",
                "registry": registry.url,
                "tag": "0.1.1"
            },
            headers=post_json_admin_header
        )
        if not enable_image_whitelist:
            assert resp.status_code == 403
            return
        assert resp.status_code == 400
        assert resp.json()["error"] == '/testimage:0.1.1 does not have a tag or is malformed. Please provide one in the format <registry>/<image>:<tag> or <registry>/<image>@sha256..'


class TestContainerModelValidation(BaseTest):
    @mark.asyncio
    async def test_container_validate_missing_registry(self, client):
        """Adding a container whose registry doesn't exist raises"""
        with raises(ContainerRegistryException) as exc:
            await ContainerService.add(
                self.db_session,
                ContainerCreate(name="test", registry="non-existent.io", tag="latest")
            )
        assert "Registry non-existent.io could not be found" in str(exc.value)

    @mark.asyncio
    async def test_whitelist_image_only_matches_any_version(self, registry):
        """Whitelisting an image without tag or SHA allows any version of that image"""
        img = Container(name="img1", registry=registry, tag=None, sha=None)
        await img.add(self.db_session)
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img1:any-tag"
        ) is True
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img1@sha256:{"a" * 64}"
        ) is True

    @mark.asyncio
    async def test_whitelist_image_and_tag_matches_specific_tag(self, registry):
        """Whitelisting an image and tag allows only that tag"""
        img = Container(name="img2", registry=registry, tag="v1", sha=None)
        await img.add(self.db_session)
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img2:v1"
        ) is True
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img2:v2"
        ) is False

    @mark.asyncio
    async def test_whitelist_image_tag_and_sha_matches_direct_sha_request(self, registry):
        """Whitelisting image, tag, and SHA allows requests matching both tag and SHA"""
        s1 = "sha256:" + "1" * 64
        img = Container(name="img3", registry=registry, tag="v1", sha=s1)
        await img.add(self.db_session)

        # Full match: Tag + SHA
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img3:v1@{s1}"
        ) is True
        # Tag matches, SHA doesn't
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img3:v1@sha256:different"
        ) is False
        # SHA matches, Tag doesn't (whitelisting is tag-restricted)
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img3:v2@{s1}"
        ) is False
        # Only SHA provided (whitelisting is tag-restricted)
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img3@{s1}"
        ) is False

    @mark.asyncio
    async def test_whitelist_image_tag_and_sha_matches_remote_resolution(self, registry, mocker):
        """Whitelisting image, tag, and SHA allows tag-only requests if remote SHA matches"""
        s1 = "sha256:" + "1" * 64
        img = Container(name="img3", registry=registry, tag="v1", sha=s1)
        await img.add(self.db_session)

        mock_client = mocker.Mock()
        mocker.patch.object(
            Registry, "get_registry_class", new=AsyncMock(return_value=mock_client)
        )
        # Tag matches, remote SHA matches
        mock_client.get_tag_sha.return_value = s1
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img3:v1"
        ) is True
        # Tag matches, remote SHA doesn't match
        mock_client.get_tag_sha.return_value = "sha256:different"
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img3:v1"
        ) is False

    @mark.asyncio
    async def test_whitelist_image_and_sha_matches_direct_sha_request(self, registry):
        """Whitelisting image and SHA (without tag) allows any tag matching that SHA"""
        s4 = "sha256:" + "4" * 64
        img = Container(name="img4", registry=registry, tag=None, sha=s4)
        await img.add(self.db_session)
        # Match by SHA directly
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img4@{s4}"
        ) is True
        # Match by Tag + SHA
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img4:any-tag@{s4}"
        ) is True

    @mark.asyncio
    async def test_whitelist_image_and_sha_matches_remote_resolution(self, registry, mocker):
        """Whitelisting image and SHA (without tag) allows tag-only requests if remote SHA matches"""
        s4 = "sha256:" + "4" * 64
        img = Container(name="img4", registry=registry, tag=None, sha=s4)
        await img.add(self.db_session)

        mock_client = mocker.Mock()
        mocker.patch.object(
            Registry, "get_registry_class", new=AsyncMock(return_value=mock_client)
        )
        # Remote SHA matches
        mock_client.get_tag_sha.return_value = s4
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img4:any-tag"
        ) is True
        # Remote SHA doesn't match
        mock_client.get_tag_sha.return_value = "sha256:different"
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img4:any-tag"
        ) is False

    @mark.asyncio
    async def test_whitelist_ignores_remote_existence_check(self, registry, mocker):
        """Whitelisting succeeds if the image is in the DB, regardless of remote existence"""
        img = Container(name="img-exists", registry=registry, tag="v1", sha=None)
        await img.add(self.db_session)

        mock_client = mocker.Mock()
        mocker.patch.object(
            Registry, "get_registry_class", new=AsyncMock(return_value=mock_client)
        )
        # Whitelisted in DB, but doesn't exist remotely
        mock_client.get_tag_sha.return_value = None
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img-exists:v1"
        ) is True

        # Whitelisted by SHA, but doesn't exist remotely
        s1 = "sha256:" + "s" * 64
        img_sha = Container(name="img-sha", registry=registry, tag=None, sha=s1)
        await img_sha.add(self.db_session)
        assert await Container.validate_image_whitelisted(
            self.db_session, f"{registry.url}/img-sha@{s1}"
        ) is True


class TestSync(BaseTest):
    @mark.asyncio
    async def test_sync_200(
        self,
        client,
        post_json_admin_header,
        v1_registry_mock,
        tags_request,
        registry,
        expected_image_names,
        expected_tags_list,
        expected_digest_list,
        mock_kc_client_wrapper
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry
        """
        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )
        expected_resp = [
            'acr.azurecr.io/testimage:1.2.3',
            'acr.azurecr.io/testimage:dev',
            'acr.azurecr.io/testimage:latest',
            'acr.azurecr.io/example:1.2.3',
            'acr.azurecr.io/example:dev',
            # 'acr.azurecr.io/example:latest', This is already present and not synched
            'acr.azurecr.io/testimage@sha256:caed983c5ba866aaa9a15cc31781f0c5fd9a73bee25dae2d9b35ee8fa6255a6c',
            'acr.azurecr.io/example@sha256:caed983c5ba866aaa9a15cc31781f0c5fd9a73bee25dae2d9b35ee8fa6255a6c'
        ]
        assert resp.status_code == 201
        assert sorted(resp.json()["images"]) == sorted(expected_resp)

    @mark.asyncio
    async def test_sync_failure(
        self,
        client,
        post_json_admin_header,
        v1_registry_mock,
        cr_name,
        respx_mock,
        registry,
        mock_kc_client_wrapper
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry. Check that upon failure
        during the process no images are synched up
        """
        respx_mock.get(
            f"https://{cr_name}/oauth2/token",
            params={
                "service": cr_name,
                "scope": "registry:catalog:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"error": "Credentials not valid"},
                status_code=401
            )
        )
        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "Could not authenticate against the registry"

    @mark.asyncio
    async def test_sync_no_action(
        self,
        client,
        post_json_admin_header,
        v1_registry_mock,
        registry,
        container,
        container_with_sha,
        azure_login_request,
        cr_name,
        mock_kc_client_wrapper,
        respx_mock
    ):
        """
        Basic test that adds couple of missing images
        from the tracked registry. Check that no duplicate
        is added.
        """
        respx_mock.get(
            f"https://{cr_name}/oauth2/token",
            params={
                "service": cr_name,
                "scope": f"repository:{container.name}:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "12345asdf"},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/{container.name}/tags/list"
        ).mock(
            return_value=httpx.Response(
                json={"tags": [container.tag]},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/{container.name}/manifests/{container.tag}",
        ).mock(
            return_value=httpx.Response(
                json={"config": {"digest": container_with_sha.sha}},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/_catalog"
        ).mock(
            return_value=httpx.Response(
                json={"repositories": [container.name]},
                status_code=200
            )
        )
        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 201, resp.json()
        assert resp.json()["images"] == []

    @mark.asyncio
    async def test_sync_no_action_inactive_registry(
        self,
        client,
        post_json_admin_header,
        registry,
        mock_kc_client_wrapper
    ):
        """
        Basic test that makes sure that if a registry is inactive
        nothing is done.
        """
        await self.db_session.execute(update(Registry).where(Registry.id == registry.id).values({"active": False}))

        resp = await client.post(
            "/containers/sync",
            headers=post_json_admin_header
        )

        assert resp.status_code == 201
        assert resp.json()["images"] == []
        assert await self.run_query(select(Container)) == []
