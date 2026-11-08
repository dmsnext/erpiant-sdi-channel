# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Ripiego MP05/TP02 dei dati fiscali di pagamento.

Senza condizioni di pagamento ``l10n_it_fatturapa_out`` lascia vuoti metodo e
termine fiscale, e ``preventive_checks()`` ferma l'export appena la fattura ha una
scadenza, cioè sempre.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPaymentData(TransactionCase):
    """Come ``TestSedeGuard``: niente ``AccountTestInvoicingCommon``, che su un DB
    senza dati demo si auto-salta; basta un giornale di vendita."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env["account.journal"].create(
            {"name": "Vendite (test dati di pagamento)", "type": "sale", "code": "SDIPD",
             "company_id": cls.company.id}
        )
        cls.customer = cls.env["res.partner"].create({"name": "Cliente dati di pagamento"})
        cls.mp05 = cls.env.ref("l10n_it_fiscal_payment_term.fatturapa_mp05")
        cls.tp02 = cls.env.ref("l10n_it_fiscal_payment_term.fatturapa_tp02")

    def _move(self, move_type="out_invoice", **vals):
        return self.env["account.move"].create(
            dict({"move_type": move_type, "partner_id": self.customer.id,
                  "company_id": self.company.id, "journal_id": self.journal.id}, **vals)
        )

    def test_senza_condizioni_mp05_tp02(self):
        invoice = self._move()
        self.assertEqual(invoice.fatturapa_payment_method_id, self.mp05)
        self.assertEqual(invoice.fatturapa_payment_term_id, self.tp02)

    def test_le_condizioni_di_pagamento_vincono(self):
        mp01 = self.env.ref("l10n_it_fiscal_payment_term.fatturapa_mp01")
        tp01 = self.env.ref("l10n_it_fiscal_payment_term.fatturapa_TP01")
        payment_term = self.env["account.payment.term"].create(
            {"name": "Contanti a rate (test)", "fatturapa_pm_id": mp01.id, "fatturapa_pt_id": tp01.id}
        )
        invoice = self._move(invoice_payment_term_id=payment_term.id)
        self.assertEqual(invoice.fatturapa_payment_method_id, mp01)
        self.assertEqual(invoice.fatturapa_payment_term_id, tp01)

    def test_scelta_dell_utente_resta(self):
        mp01 = self.env.ref("l10n_it_fiscal_payment_term.fatturapa_mp01")
        invoice = self._move()
        invoice.fatturapa_payment_method_id = mp01
        self.assertEqual(invoice.fatturapa_payment_method_id, mp01)

    def test_fatture_fornitore_non_toccate(self):
        purchase_journal = self.env["account.journal"].create(
            {"name": "Acquisti (test dati di pagamento)", "type": "purchase", "code": "SDIPA",
             "company_id": self.company.id}
        )
        bill = self._move("in_invoice", journal_id=purchase_journal.id)
        self.assertFalse(bill.fatturapa_payment_method_id)
        self.assertFalse(bill.fatturapa_payment_term_id)

    def test_autofattura_reverse_charge_non_toccata(self):
        if "rc_purchase_invoice_id" not in self.env["account.move"]._fields:
            self.skipTest("l10n_it_reverse_charge non installato")
        purchase_journal = self.env["account.journal"].create(
            {"name": "Acquisti RC (test dati di pagamento)", "type": "purchase", "code": "SDIPR",
             "company_id": self.company.id}
        )
        bill = self._move("in_invoice", journal_id=purchase_journal.id)
        self_invoice = self._move(rc_purchase_invoice_id=bill.id)
        self.assertFalse(self_invoice.fatturapa_payment_method_id)
        self.assertFalse(self_invoice.fatturapa_payment_term_id)
