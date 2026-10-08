# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Precompilazione dell'anagrafica azienda dai dati restituiti dall'attivazione.

Il contratto è quello concordato sulla board il 2026-10-08 e implementato
lato sito in `erpiant_sdi_licensing` (`0ee3df3`): la risposta di
``POST /sdi/activation`` porta un blocco ``company`` **annidato**, con
``state_code``/``country_code`` come **codici** e **senza chiavi vuote**.

Qui si verificano le due regole ferme che ho promesso in cambio: **non
sovrascrivere mai un campo già valorizzato** e **non far mai fallire
l'attivazione** per un dato anagrafico.
"""

from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from .test_activation import (
    LICENSE_CODE,
    POST_TARGET,
    VALID_VAT,
    _FakeResponse,
    _get_or_create_erpiant_channel,
)

COMPANY_BLOCK = {
    "name": "Panificio Aurora S.r.l.",
    "vat": "IT02345670018",
    "street": "Via Emilia Est 148",
    "zip": "41122",
    "city": "Modena",
    "state_code": "MO",
    "country_code": "IT",
    "email": "info@panificioaurora.example",
    "phone": "059123456",
}


def _ok(company=None):
    payload = {
        "token": "tok-abc",
        "endpoint_url": "https://sdi.erpiant.com/sdi",
        "environment": "test",
        "tenant_id": "tnt-1",
        "rotated": False,
    }
    if company is not None:
        payload["company"] = company
    return _FakeResponse(200, payload)


@tagged("post_install", "-at_install")
class TestCompanyPrefill(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = VALID_VAT
        cls.channel = _get_or_create_erpiant_channel(cls.env, cls.company)

    def setUp(self):
        super().setUp()
        self.channel.write({"erpiant_license_code": LICENSE_CODE})
        # Si parte da un'anagrafica azienda vuota: è lo stato reale del database
        # precostruito dell'installer (`My Company`, senza P.IVA e senza sede).
        self.partner = self.company.partner_id
        self.partner.write(
            {
                "street": False,
                "zip": False,
                "city": False,
                "state_id": False,
                "country_id": False,
                "email": False,
                "phone": False,
            }
        )

    def _activate(self, company=None):
        with patch(POST_TARGET, return_value=_ok(company)):
            return self.channel.action_erpiant_activate()

    # ------------------------------------------------------------------
    # Il caso che giustifica tutto: l'utente non ridigita i propri dati
    # ------------------------------------------------------------------
    def test_empty_company_gets_prefilled(self):
        self._activate(COMPANY_BLOCK)
        self.assertEqual(self.partner.street, "Via Emilia Est 148")
        self.assertEqual(self.partner.zip, "41122")
        self.assertEqual(self.partner.city, "Modena")
        self.assertEqual(self.partner.email, "info@panificioaurora.example")

    def test_codes_are_resolved_to_records(self):
        """`MO` e `IT` sono codici: vanno risolti, non scritti come testo."""
        self._activate(COMPANY_BLOCK)
        self.assertEqual(self.partner.country_id.code, "IT")
        self.assertEqual(self.partner.state_id.code, "MO")
        self.assertEqual(self.partner.state_id.country_id.code, "IT")

    def test_user_is_told_what_was_prefilled(self):
        """Precompilare sì, applicare in silenzio no: è l'intestazione legale."""
        action = self._activate(COMPANY_BLOCK)
        message = action["params"]["message"]
        self.assertIn("precompilato", message)
        self.assertIn("indirizzo", message)
        self.assertIn("Aziende", message)

    # ------------------------------------------------------------------
    # La regola che protegge l'utente: comanda lui
    # ------------------------------------------------------------------
    def test_existing_values_are_never_overwritten(self):
        self.partner.write({"street": "Via Giardini 100", "city": "Carpi"})
        self._activate(COMPANY_BLOCK)
        self.assertEqual(self.partner.street, "Via Giardini 100")
        self.assertEqual(self.partner.city, "Carpi")
        # I campi che erano vuoti vengono comunque riempiti: si completa, non si
        # sostituisce.
        self.assertEqual(self.partner.zip, "41122")

    def test_prefill_does_not_mention_untouched_fields(self):
        self.partner.street = "Via Giardini 100"
        action = self._activate(COMPANY_BLOCK)
        message = action["params"]["message"]
        self.assertIn("CAP", message)
        self.assertNotIn("indirizzo", message)

    # ------------------------------------------------------------------
    # La regola che protegge l'attivazione: non deve mai fallire per un dato
    # ------------------------------------------------------------------
    def test_activation_works_without_company_block(self):
        """Le build precedenti ignorano il blocco: la risposta senza non rompe."""
        self._activate(None)
        self.assertEqual(self.channel.erpiant_auth_token, "tok-abc")
        self.assertFalse(self.partner.street)

    def test_partial_block_is_accepted(self):
        self._activate({"city": "Modena"})
        self.assertEqual(self.partner.city, "Modena")
        self.assertEqual(self.channel.erpiant_auth_token, "tok-abc")

    def test_unknown_codes_are_skipped_not_fatal(self):
        block = dict(COMPANY_BLOCK, country_code="ZZ", state_code="QQ")
        self._activate(block)
        self.assertFalse(self.partner.country_id)
        self.assertFalse(self.partner.state_id)
        # Il resto dell'indirizzo arriva lo stesso.
        self.assertEqual(self.partner.street, "Via Emilia Est 148")

    def test_vat_is_deliberately_not_prefilled(self):
        """La P.IVA nel payload NON si consuma, ed è una scelta.

        ``action_erpiant_activate`` pretende la partita IVA dell'azienda **prima**
        di chiamare il sito (senza, si ferma con un messaggio dedicato): a questo
        punto del flusso non è mai vuota, quindi precompilarla sarebbe codice
        morto. Il sito continua a mandarla ed è innocua. Questo test esiste per
        spiegare il perché a chi fosse tentato di rimetterla.
        """
        original = self.partner.vat
        self.assertTrue(original, "l'attivazione non parte senza P.IVA aziendale")
        action = self._activate(dict(COMPANY_BLOCK, vat="IT02345670018"))
        self.assertEqual(self.partner.vat, original, "la P.IVA non va toccata")
        self.assertNotIn("partita IVA", action["params"]["message"])

    def test_garbage_block_is_ignored(self):
        """Un blocco non-dict non deve nemmeno arrivare a scrivere."""
        self._activate("non-un-oggetto")
        self.assertEqual(self.channel.erpiant_auth_token, "tok-abc")
        self.assertFalse(self.partner.street)
