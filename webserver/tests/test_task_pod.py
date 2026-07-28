from pytest import mark

from app.helpers.settings import settings
from app.helpers.task_pod import TaskPod


class TestTaskPod:
    @mark.asyncio
    async def test_task_pod_pv_mount_options(self, mocker, pod_dict):
        """
        Test that mount options are correctly applied to the PV spec
        """
        mocker.patch("app.helpers.settings.settings.mount_options", "idsfromsid,modefromsid")
        task_pod = TaskPod(**pod_dict)
        task_pod.create_storage_specs()
        assert task_pod.pv.spec.mount_options == ["idsfromsid", "modefromsid"]

    @mark.asyncio
    async def test_task_pod_pv_no_mount_options(self, mocker, pod_dict):
        """
        Test that no mount options are applied when the env var is not set
        """
        mocker.patch("app.helpers.settings.settings.mount_options", None)
        task_pod = TaskPod(**pod_dict)
        task_pod.create_storage_specs()
        assert task_pod.pv.spec.mount_options is None

    @mark.asyncio
    async def test_task_pod_pv_empty_mount_options(self, mocker, pod_dict):
        """
        Test that no mount options are applied when the env var is empty
        """
        mocker.patch("app.helpers.settings.settings.mount_options", "")
        task_pod = TaskPod(**pod_dict)
        task_pod.create_storage_specs()
        assert task_pod.pv.spec.mount_options is None

    @mark.asyncio
    async def test_task_pod_pv_default_mount_options(self, pod_dict):
        """
        Test that the unset default carries no mount options. Guards against the
        default being a truthy string, which would apply it as a real option.
        """
        assert settings.mount_options is None
        task_pod = TaskPod(**pod_dict)
        task_pod.create_storage_specs()
        assert task_pod.pv.spec.mount_options is None
