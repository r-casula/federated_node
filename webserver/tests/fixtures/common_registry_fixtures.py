import re
from  pytest_asyncio import fixture
from unittest.mock import Mock
from kubernetes_asyncio.client import V1Secret


@fixture
def registry_secret_mock(dockerconfigjson_mock, cr_name):
    secret_return = Mock(spec=V1Secret)
    secret_return.metadata.name = re.sub(r'[\W_]+', '-', cr_name)
    # Also carries the dataset-credentials keys so a single mocked
    # `read_namespaced_secret` serves both registry-cred and dataset-cred
    # reads regardless of which `KubernetesClient.create` patch wins.
    secret_return.data = {
        "PGUSER": "YWJjMTIz",
        "PGPASSWORD": "YWJjMTIz",
        "USER": "YWJjMTIz",
        "TOKEN": "YWJjMTIz",
        **dockerconfigjson_mock,
    }
    return secret_return
