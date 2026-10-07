# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Chi fattura deve poter inviare allo SdI in un passaggio solo.

A monte ``l10n_it_sdi_channel.res_groups_validate_send`` è un gruppo **vuoto**:
nessun utente ce l'ha, nemmeno l'amministratore, quindi il bottone "Validate,
export and send to SdI" sulla fattura in bozza è invisibile a tutti e resta solo
la via lunga (Export → allegato → Send to SdI). Qui si verifica che
l'implicazione aggiunta dal modulo lo renda effettivamente disponibile, e che il
gruppo tecnico dei canali resti invece **chiuso**.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestValidateSendGroup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.validate_send = cls.env.ref(
            "l10n_it_sdi_channel.res_groups_validate_send"
        )
        cls.billing = cls.env.ref("account.group_account_invoice")

    def _user_with(self, group):
        return self.env["res.users"].create(
            {
                "name": "Utente di prova",
                "login": "prova-%s" % group.id,
                "groups_id": [(6, 0, [group.id])],
            }
        )

    def test_billing_implies_validate_send(self):
        """L'implicazione è dichiarata sul gruppo Fatturazione."""
        self.assertIn(self.validate_send, self.billing.implied_ids)

    def test_billing_user_can_use_one_click_send(self):
        """Il caso reale: l'utente che fattura vede il bottone a un click."""
        user = self._user_with(self.billing)
        self.assertIn(self.validate_send, user.groups_id)

    def test_accountant_inherits_it_too(self):
        """Contabile e Amministratore stanno sopra Fatturazione: lo ereditano."""
        accountant = self.env.ref("account.group_account_user")
        user = self._user_with(accountant)
        self.assertIn(self.validate_send, user.groups_id)

    def test_channel_group_stays_closed(self):
        """Il gruppo tecnico dei canali NON deve essere stato aperto per sbaglio."""
        developer = self.env.ref("erpiant_sdi_channel.group_sdi_developer")
        self.assertNotIn(developer, self.billing.implied_ids)
        self.assertFalse(
            developer.users,
            "group_sdi_developer deve restare senza utenti: i canali si "
            "gestiscono solo via post_init_hook (lock-down §7.7).",
        )
