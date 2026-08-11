# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Test del flusso di attivazione: numero di licenza -> credenziale.

Il sito (`ec62995`, @Sito-Struttura) e il broker (`c3df29e`, @Broker SDI) sono
fuori dal perimetro del tenant: qui si mocka la sola chiamata HTTP
``POST {site}/sdi/activation``, che e' il contratto concordato sulla board.
L'obiettivo non e' testare la rete ma il contratto lato tenant: cosa scrive,
cosa mostra, e cosa NON scrive quando qualcosa va storto.
"""

from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

VALID_VAT = "IT06363391001"
LICENSE_CODE = "ERP-TEST-0000-0001"
POST_TARGET = "odoo.addons.erpiant_sdi_channel.models.sdi_channel.requests.post"


class _FakeResponse:
    """Sostituto minimale di ``requests.Response`` per i test."""

    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _get_or_create_erpiant_channel(env, company):
    """Stesso criterio di ``hooks.post_init_hook``: un canale ``erpiant_aws``
    per azienda. Robusto a prescindere dall'ordine di installazione/demo.
    """
    channel = company.sdi_channel_id
    if channel and channel.channel_type == "erpiant_aws":
        return channel
    channel = env["sdi.channel"].create(
        {
            "name": "Erpiant SDI",
            "channel_type": "erpiant_aws",
            "company_id": company.id,
        }
    )
    company.sdi_channel_id = channel.id
    return channel


@tagged("post_install", "-at_install")
class TestErpiantChannelActivation(TransactionCase):
    """``sdi.channel.action_erpiant_activate`` — il pezzo che parla col sito."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = VALID_VAT
        cls.channel = _get_or_create_erpiant_channel(cls.env, cls.company)

    def setUp(self):
        super().setUp()
        # Ogni test riparte da un canale non attivato: l'attivazione precedente
        # (di un altro test) non deve trapelare.
        self.channel.write(
            {
                "erpiant_license_code": False,
                "erpiant_auth_token": False,
                "erpiant_endpoint_url": False,
                "erpiant_tenant_ref": False,
            }
        )

    # ------------------------------------------------------------------
    # Validazioni locali: non devono nemmeno uscire in rete
    # ------------------------------------------------------------------
    def test_requires_license_code(self):
        self.channel.erpiant_license_code = False
        with patch(POST_TARGET) as post:
            with self.assertRaises(UserError):
                self.channel.action_erpiant_activate()
        post.assert_not_called()

    def test_requires_company_vat(self):
        self.channel.erpiant_license_code = LICENSE_CODE
        self.company.vat = False
        with patch(POST_TARGET) as post:
            with self.assertRaises(UserError):
                self.channel.action_erpiant_activate()
        post.assert_not_called()

    # ------------------------------------------------------------------
    # Esito positivo
    # ------------------------------------------------------------------
    def test_activation_success_first_time(self):
        self.channel.erpiant_license_code = LICENSE_CODE
        payload = {
            "token": "tok-123",
            "endpoint_url": "https://sdi.erpiant.com/sdi",
            "environment": "test",
            "tenant_id": "tnt-abc",
            "rotated": False,
        }
        with patch(POST_TARGET, return_value=_FakeResponse(200, payload)) as post:
            result = self.channel.action_erpiant_activate()

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://www.erpiant.com/sdi/activation")
        self.assertEqual(
            kwargs["json"], {"license_code": LICENSE_CODE, "vat": VALID_VAT}
        )
        self.assertEqual(self.channel.erpiant_auth_token, "tok-123")
        self.assertEqual(
            self.channel.erpiant_endpoint_url, "https://sdi.erpiant.com/sdi"
        )
        self.assertEqual(self.channel.erpiant_environment, "test")
        self.assertEqual(self.channel.erpiant_tenant_ref, "tnt-abc")
        self.assertEqual(self.channel.erpiant_activation_state, "active")
        self.assertEqual(
            result["params"]["message"], "Fatturazione elettronica attivata."
        )

    def test_activation_success_reinstall_says_credit_kept(self):
        """`rotated=True` deve produrre un messaggio DIVERSO dalla prima
        attivazione: senza, chi reinstalla non saprebbe se il credito residuo
        e' ancora suo (cfr. board, 2026-08-10)."""
        self.channel.erpiant_license_code = LICENSE_CODE
        payload = {
            "token": "tok-456",
            "endpoint_url": "https://sdi.erpiant.com/sdi",
            "environment": "live",
            "tenant_id": "tnt-abc",
            "rotated": True,
        }
        with patch(POST_TARGET, return_value=_FakeResponse(200, payload)):
            result = self.channel.action_erpiant_activate()

        self.assertIn("mantenuti", result["params"]["message"])
        self.assertEqual(self.channel.erpiant_environment, "live")

    def test_activation_missing_token_does_not_write_partial_state(self):
        self.channel.erpiant_license_code = LICENSE_CODE
        with patch(POST_TARGET, return_value=_FakeResponse(200, {})):
            with self.assertRaises(UserError):
                self.channel.action_erpiant_activate()
        self.assertFalse(self.channel.erpiant_auth_token)
        self.assertEqual(self.channel.erpiant_activation_state, "inactive")

    # ------------------------------------------------------------------
    # Errori di rete/HTTP: ogni codice deve dire cosa FARE, non cosa e'
    # successo a noi (cfr. `_erpiant_raise_for_activation`), e nessuno di
    # questi deve lasciare credenziali scritte a meta'.
    # ------------------------------------------------------------------
    def test_network_unreachable(self):
        self.channel.erpiant_license_code = LICENSE_CODE
        with patch(POST_TARGET, side_effect=requests.ConnectionError("boom")):
            with self.assertRaises(UserError) as cm:
                self.channel.action_erpiant_activate()
        self.assertIn("Non riesco a contattare", str(cm.exception))
        self.assertFalse(self.channel.erpiant_auth_token)

    def test_http_404_license_not_recognized(self):
        self._assert_http_error_message(404, "non riconosciuto")

    def test_http_403_vat_mismatch(self):
        self._assert_http_error_message(403, "non corrisponde alla partita IVA")

    def test_http_401_preview_gate_not_a_license_problem(self):
        self._assert_http_error_message(401, "non è ancora aperto al pubblico")

    def test_http_502_broker_down_license_stays_valid(self):
        self._assert_http_error_message(502, "momentaneamente non disponibile")

    def test_http_other_generic_error_reports_code(self):
        self._assert_http_error_message(418, "codice 418")

    def _assert_http_error_message(self, status_code, expected_snippet):
        self.channel.erpiant_license_code = LICENSE_CODE
        with patch(
            POST_TARGET, return_value=_FakeResponse(status_code, {}, text="err")
        ):
            with self.assertRaises(UserError) as cm:
                self.channel.action_erpiant_activate()
        self.assertIn(expected_snippet, str(cm.exception))
        self.assertFalse(self.channel.erpiant_auth_token)
        self.assertEqual(self.channel.erpiant_activation_state, "inactive")


@tagged("post_install", "-at_install")
class TestErpiantSettingsActivation(TransactionCase):
    """``res.config.settings.action_erpiant_activate`` — il ponte da
    Impostazioni generali (dove il cliente arriva) al canale.

    Copre in particolare la regressione chiusa il 2026-08-10: senza
    ``set_values()`` esplicito prima di inoltrare, il codice appena digitato
    nel wizard NON arriva al canale (i campi ``res.config.settings`` sono
    ``related`` non-``store``, e il generico `write-through` verso
    ``company_id`` scatta solo dentro ``set_values()``, non ad ogni
    assegnazione sul TransientModel).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = VALID_VAT
        cls.channel = _get_or_create_erpiant_channel(cls.env, cls.company)

    def setUp(self):
        super().setUp()
        self.channel.write({"erpiant_license_code": False, "erpiant_auth_token": False})

    def test_freshly_typed_code_reaches_the_channel(self):
        settings = self.env["res.config.settings"].create(
            {"erpiant_license_code": LICENSE_CODE}
        )
        payload = {
            "token": "tok-789",
            "endpoint_url": "https://sdi.erpiant.com/sdi",
            "environment": "test",
            "tenant_id": "tnt-xyz",
            "rotated": False,
        }
        with patch(POST_TARGET, return_value=_FakeResponse(200, payload)) as post:
            settings.action_erpiant_activate()

        # Prova diretta della regressione: il canale (non il wizard) e' stato
        # letto/scritto col codice appena digitato, non con un valore vecchio.
        self.assertEqual(self.channel.erpiant_license_code, LICENSE_CODE)
        self.assertEqual(
            post.call_args.kwargs["json"]["license_code"], LICENSE_CODE
        )
        self.assertEqual(self.channel.erpiant_auth_token, "tok-789")
        self.assertEqual(self.channel.erpiant_activation_state, "active")

    def test_no_channel_configured_gives_actionable_error(self):
        self.company.sdi_channel_id = False
        settings = self.env["res.config.settings"].create(
            {"erpiant_license_code": LICENSE_CODE}
        )
        with patch(POST_TARGET) as post:
            with self.assertRaises(UserError):
                settings.action_erpiant_activate()
        post.assert_not_called()
