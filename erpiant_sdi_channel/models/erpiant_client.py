# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""HTTP client verso il broker SDI di erpiant.com.

Il broker (architettura AWS, repo ``erpiant-aws``) ri-espone la stessa
superficie di risorse del fornitore Invoicetronic (``/send``, ``/update``,
``/receive`` …) iniettando lato server la API Key del fornitore: per questo
la chiave Invoicetronic **non transita né è memorizzata nel tenant**.

La classe è volutamente indipendente da Odoo (nessun import ORM) così da
poter essere riutilizzata anche lato broker.
"""

import logging

import requests

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class ErpiantSdiError(Exception):
    """Errore di comunicazione/elaborazione col broker SDI Erpiant."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ErpiantSdiClient:
    """Client minimale del broker SDI Erpiant.

    :param base_url: URL base del broker, es. ``https://sdi.erpiant.com/sdi``.
    :param auth_header: valore dell'header ``Authorization`` (es. ``Bearer <token>``).
    :param environment: ``test`` | ``live`` (inoltrato al broker come hint).
    :param timeout: timeout HTTP in secondi.
    """

    def __init__(self, base_url, auth_header, environment="test", timeout=DEFAULT_TIMEOUT):
        if not base_url:
            raise ErpiantSdiError("URL del broker SDI Erpiant non configurato.")
        if not auth_header:
            raise ErpiantSdiError("Token di autenticazione verso il broker non configurato.")
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.environment = environment
        self.timeout = timeout

    # -- helpers ---------------------------------------------------------
    def _headers(self, content_type=None):
        headers = {
            "Authorization": self.auth_header,
            "Accept": "application/json",
            "X-Erpiant-Environment": self.environment,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(self, method, path, **kwargs):
        url = "%s/%s" % (self.base_url, path.lstrip("/"))
        try:
            resp = requests.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ErpiantSdiError(
                "Comunicazione col broker SDI Erpiant fallita: %s" % exc
            ) from exc
        if resp.status_code >= 400:
            raise ErpiantSdiError(
                "Broker SDI Erpiant ha risposto %s su %s %s: %s"
                % (resp.status_code, method, path, resp.text[:500]),
                status_code=resp.status_code,
                payload=resp.text,
            )
        if not resp.content:
            return None
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            return resp.json()
        return resp.content

    # -- outbound (fatture attive) --------------------------------------
    def send_xml(self, xml_bytes, signature=None):
        """Invia una FatturaPA (XML FPR12). Ritorna l'oggetto Send.

        :param signature: modalità di firma CAdES richiesta al broker
            (``None`` | ``Apply`` | ``Force`` | ``Auto``). Se ``None`` non si
            passa nulla e vale il default del broker/fornitore.
        """
        params = {"signature": signature} if signature else None
        return self._request(
            "POST",
            "/send/xml",
            headers=self._headers(content_type="application/xml"),
            data=xml_bytes,
            params=params,
        )

    def validate_xml(self, xml_bytes):
        """Pre-flight validation di una FatturaPA. Ritorna l'esito."""
        return self._request(
            "POST",
            "/send/validate/xml",
            headers=self._headers(content_type="application/xml"),
            data=xml_bytes,
        )

    def get_updates(self, unread=True, **params):
        """Elenca le notifiche/aggiornamenti di stato SdI (oggetti Update)."""
        if unread:
            params["unread"] = "true"
        return self._request(
            "GET", "/update", headers=self._headers(), params=params
        )

    # -- inbound (fatture passive) --------------------------------------
    def get_receive_list(self, unread=True, **params):
        """Elenca le fatture passive recapitate (oggetti Receive)."""
        if unread:
            params["unread"] = "true"
        return self._request(
            "GET", "/receive", headers=self._headers(), params=params
        )

    def get_receive_payload(self, receive_id):
        """Scarica il contenuto (XML/p7m) di una fattura passiva."""
        return self._request(
            "GET",
            "/receive/%s/payload" % receive_id,
            headers=self._headers(),
        )
