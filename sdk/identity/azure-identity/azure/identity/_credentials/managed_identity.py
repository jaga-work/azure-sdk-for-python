# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
import logging
import os
from typing import Optional, TYPE_CHECKING, Any

from azure.core.credentials import AccessToken
from .. import CredentialUnavailableError
from .._constants import EnvironmentVariables
from .._internal.decorators import log_get_token

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_LOGGER = logging.getLogger(__name__)


class ManagedIdentityCredential:
    """Authenticates with an Azure managed identity in any hosting environment which supports managed identities.

    This credential defaults to using a system-assigned identity. To configure a user-assigned identity, use one of
    the keyword arguments. See `Microsoft Entra ID documentation
    <https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/overview>`_ for more
    information about configuring managed identity for applications.

    :keyword str client_id: a user-assigned identity's client ID or, when using Pod Identity, the client ID of an Azure
        AD app registration. This argument is supported in all hosting environments.
    :keyword identity_config: a mapping ``{parameter_name: value}`` specifying a user-assigned identity by its object
        or resource ID, for example ``{"object_id": "..."}``. Check the documentation for your hosting environment to
        learn what values it expects.
    :paramtype identity_config: Mapping[str, str]

    .. admonition:: Example:

        .. literalinclude:: ../samples/credential_creation_code_snippets.py
            :start-after: [START create_managed_identity_credential]
            :end-before: [END create_managed_identity_credential]
            :language: python
            :dedent: 4
            :caption: Create a ManagedIdentityCredential.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._credential = None  # type: Optional[TokenCredential]
        exclude_workload_identity = kwargs.pop("_exclude_workload_identity_credential", False)
        if os.environ.get(EnvironmentVariables.IDENTITY_ENDPOINT):
            if os.environ.get(EnvironmentVariables.IDENTITY_HEADER):
                if os.environ.get(EnvironmentVariables.IDENTITY_SERVER_THUMBPRINT):
                    _LOGGER.info("%s will use Service Fabric managed identity", self.__class__.__name__)
                    from .service_fabric import ServiceFabricCredential

                    self._credential = ServiceFabricCredential(**kwargs)
                else:
                    _LOGGER.info("%s will use App Service managed identity", self.__class__.__name__)
                    from .app_service import AppServiceCredential

                    self._credential = AppServiceCredential(**kwargs)
            elif os.environ.get(EnvironmentVariables.IMDS_ENDPOINT):
                _LOGGER.info("%s will use Azure Arc managed identity", self.__class__.__name__)
                from .azure_arc import AzureArcCredential

                self._credential = AzureArcCredential(**kwargs)
        elif os.environ.get(EnvironmentVariables.MSI_ENDPOINT):
            if os.environ.get(EnvironmentVariables.MSI_SECRET):
                _LOGGER.info("%s will use Azure ML managed identity", self.__class__.__name__)
                from .azure_ml import AzureMLCredential

                self._credential = AzureMLCredential(**kwargs)
            else:
                _LOGGER.info("%s will use Cloud Shell managed identity", self.__class__.__name__)
                from .cloud_shell import CloudShellCredential

                self._credential = CloudShellCredential(**kwargs)
        elif (
            all(os.environ.get(var) for var in EnvironmentVariables.WORKLOAD_IDENTITY_VARS)
            and not exclude_workload_identity
        ):
            _LOGGER.info("%s will use workload identity", self.__class__.__name__)
            from .workload_identity import WorkloadIdentityCredential

            client_id = kwargs.pop("client_id", None) or os.environ.get(EnvironmentVariables.AZURE_CLIENT_ID)
            if not client_id:
                raise ValueError('Configure the environment with a client ID or pass a value for "client_id" argument')

            self._credential = WorkloadIdentityCredential(
                tenant_id=os.environ[EnvironmentVariables.AZURE_TENANT_ID],
                client_id=client_id,
                file=os.environ[EnvironmentVariables.AZURE_FEDERATED_TOKEN_FILE],
                **kwargs
            )
        else:
            from .imds import ImdsCredential

            _LOGGER.info("%s will use IMDS", self.__class__.__name__)
            self._credential = ImdsCredential(**kwargs)

    def __enter__(self) -> "ManagedIdentityCredential":
        if self._credential:
            self._credential.__enter__()  # type: ignore
        return self

    def __exit__(self, *args: Any) -> None:
        if self._credential:
            self._credential.__exit__(*args)  # type: ignore

    def close(self) -> None:
        """Close the credential's transport session."""
        self.__exit__()

    @log_get_token("ManagedIdentityCredential")
    def get_token(
        self, *scopes: str, claims: Optional[str] = None, tenant_id: Optional[str] = None, **kwargs: Any
    ) -> AccessToken:
        """Request an access token for `scopes`.

        This method is called automatically by Azure SDK clients.

        :param str scopes: desired scope for the access token. This credential allows only one scope per request.
            For more information about scopes, see
            https://learn.microsoft.com/azure/active-directory/develop/scopes-oidc.

        :keyword str claims: not used by this credential; any value provided will be ignored.
        :keyword str tenant_id: not used by this credential; any value provided will be ignored.

        :return: An access token with the desired scopes.
        :rtype: ~azure.core.credentials.AccessToken
        :raises ~azure.identity.CredentialUnavailableError: managed identity isn't available in the hosting environment
        """

        if not self._credential:
            raise CredentialUnavailableError(
                message="No managed identity endpoint found. \n"
                "The Target Azure platform could not be determined from environment variables. \n"
                "Visit https://aka.ms/azsdk/python/identity/managedidentitycredential/troubleshoot to "
                "troubleshoot this issue."
            )
        return self._credential.get_token(*scopes, claims=claims, tenant_id=tenant_id, **kwargs)
