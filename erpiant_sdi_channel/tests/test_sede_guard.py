# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Test della guardia sull'indirizzo in ``account.move.preventive_checks()``.

Il punto da proteggere non è il calcolo ma il **silenzio**: senza guardia una
fattura con anagrafica incompleta passa `preventive_checks()` senza un
avvertimento e lo scarto arriva dallo SdI a documento già emesso. Qui si verifica
che il blocco scatti *prima*, che dica cosa manca, e soprattutto che **non**
scatti nei casi legittimi (cliente non soggetto a fattura elettronica, anagrafica
completa, cliente estero senza provincia).
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSedeGuard(TransactionCase):
    """⚠️ NON ereditare da ``AccountTestInvoicingCommon``: su un database
    installato ``--without-demo=all`` quella classe **si auto-salta** con
    "Accounting Tests skipped because the user's company has no chart of
    accounts", e un test saltato in silenzio è un verde finto.

    Qui serve solo un **giornale di vendita** per poter creare una bozza di
    fattura (``account.move.create`` fallisce con "No journal could be found"):
    lo si crea a mano, senza piano dei conti. Le fatture di questi test non
    vengono mai confermate, quindi i conti non servono.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Vendite (test guardia Sede)",
                "type": "sale",
                "code": "SDIGU",
                "company_id": cls.company.id,
            }
        )
        cls.it = cls.env.ref("base.it")
        cls.mo = cls.env["res.country.state"].search(
            [("country_id", "=", cls.it.id), ("code", "=", "MO")], limit=1
        )
        # Azienda italiana con sede completa: il caso "tutto a posto" di partenza.
        # La nazione va scritta prima della P.IVA, che `base_vat` valida rispetto
        # al paese del partner.
        cls.company.partner_id.write(
            {
                "street": "Via Giardini 100",
                "city": "Modena",
                "zip": "41124",
                "state_id": cls.mo.id,
                "country_id": cls.it.id,
            }
        )
        cls.company.vat = "IT06363391001"
        # La P.IVA è obbligatoria: `l10n_it` rifiuta un partner italiano soggetto
        # a fattura elettronica che non abbia P.IVA né codice fiscale.
        # ⚠️ Deve essere valida per `stdnum`, che oltre al checksum verifica il
        # "codice ufficio" (cifre 8-10): `02345678904` ha checksum corretto ma
        # ufficio `890`, fuori dagli intervalli ammessi, e viene rifiutata.
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Panificio Aurora S.r.l.",
                "is_company": True,
                "vat": "IT02345670018",
                "street": "Via Emilia Est 148",
                "city": "Modena",
                "zip": "41122",
                "state_id": cls.mo.id,
                "country_id": cls.it.id,
                "electronic_invoice_subjected": True,
            }
        )

    def _invoice(self, partner=None):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": (partner or self.customer).id,
                "company_id": self.company.id,
                "journal_id": self.journal.id,
            }
        )

    # ------------------------------------------------------------------
    # Non deve bloccare: sono i falsi positivi a rendere inutile una guardia
    # ------------------------------------------------------------------
    def test_complete_data_passes(self):
        """Anagrafiche complete da entrambi i lati: nessun blocco."""
        self._invoice().preventive_checks()

    def test_customer_not_subjected_is_skipped(self):
        """Senza fattura elettronica non si genera XML: non bloccare."""
        partner = self.customer.copy(
            {
                "street": False,
                "city": False,
                "country_id": False,
                "electronic_invoice_subjected": False,
            }
        )
        self._invoice(partner).preventive_checks()

    def test_foreign_customer_without_state_passes(self):
        """<Provincia> esce solo per l'Italia: su un estero non va preteso."""
        partner = self.customer.copy(
            {
                "state_id": False,
                "country_id": self.env.ref("base.de").id,
                # Una P.IVA italiana su un partner tedesco non passerebbe
                # `base_vat`: qui interessa solo l'assenza di provincia.
                "vat": False,
            }
        )
        self._invoice(partner).preventive_checks()

    # ------------------------------------------------------------------
    # Deve bloccare, e dire cosa manca
    # ------------------------------------------------------------------
    def test_customer_street_and_city_are_covered_upstream(self):
        """Divisione del lavoro: su via e città NON duplichiamo il controllo.

        ``l10n_it_fatturapa._check_ftpa_partner_data`` le pretende già al
        salvataggio dell'anagrafica del cliente — tanto che un partner del genere
        non è nemmeno costruibile. Se un domani quel vincolo sparisse, questo test
        diventerebbe rosso e ci direbbe di estendere la guardia.
        """
        for field in ("street", "city"):
            with self.assertRaises(
                ValidationError, msg="atteso il vincolo di monte su %s" % field
            ):
                self.customer.copy({field: False})

    def test_italian_customer_without_state_is_blocked(self):
        """In Italia la provincia è obbligatoria e non ha ripiego nel template."""
        partner = self.customer.copy({"state_id": False})
        with self.assertRaises(UserError) as err:
            self._invoice(partner).preventive_checks()
        self.assertIn("provincia", str(err.exception))

    def test_company_without_address_is_blocked(self):
        """Il caso del micro-imprenditore appena registrato: manca la SUA sede."""
        self.company.partner_id.write({"street": False, "city": False})
        with self.assertRaises(UserError) as err:
            self._invoice().preventive_checks()
        message = str(err.exception)
        self.assertIn(self.company.partner_id.display_name, message)
        self.assertIn("città", message)

    def test_message_lists_both_sides_at_once(self):
        """Un solo errore che elenca tutto: non far scoprire i problemi a uno a uno."""
        self.company.partner_id.street = False
        partner = self.customer.copy({"state_id": False})
        with self.assertRaises(UserError) as err:
            self._invoice(partner).preventive_checks()
        message = str(err.exception)
        self.assertIn(self.company.partner_id.display_name, message)
        self.assertIn(partner.display_name, message)

    def test_guard_runs_before_xml_generation(self):
        """La guardia sta in preventive_checks, cioè prima dell'export."""
        partner = self.customer.copy({"state_id": False})
        invoice = self._invoice(partner)
        with self.assertRaises(UserError):
            invoice.preventive_checks()
        self.assertFalse(invoice.fatturapa_attachment_out_id)
