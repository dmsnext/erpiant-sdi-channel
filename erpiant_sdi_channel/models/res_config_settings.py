# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    erpiant_environment = fields.Selection(
        related="company_id.sdi_channel_id.erpiant_environment",
        string="Ambiente fatturazione elettronica Erpiant",
        readonly=True,
    )
    # --- Attivazione, esposta DOVE IL CLIENTE LA TROVA ------------------------
    # L'attivazione viveva solo nella vista del canale SDI, che il lock-down
    # riserva al gruppo tecnico (`group_sdi_developer`): un micro-imprenditore non
    # ci arriva mai. Qui la si porta in Impostazioni generali, che e' il posto
    # dove uno cerca "come attivo la fatturazione elettronica".
    erpiant_activation_state = fields.Selection(
        related="company_id.sdi_channel_id.erpiant_activation_state",
        string="Stato fatturazione elettronica",
        readonly=True,
    )
    erpiant_license_code = fields.Char(
        related="company_id.sdi_channel_id.erpiant_license_code",
        string="Numero di licenza",
        readonly=False,
    )
    erpiant_tenant_ref = fields.Char(
        related="company_id.sdi_channel_id.erpiant_tenant_ref",
        string="Riferimento assistenza",
        readonly=True,
    )

    def action_erpiant_activate(self):
        """Inoltra l'attivazione al canale, dalle Impostazioni generali.

        Le impostazioni sono un TransientModel: senza il salvataggio esplicito, il
        codice digitato resterebbe nel wizard e il canale riceverebbe il valore
        vecchio (tipicamente vuoto) -> "inserisci il numero di licenza" subito dopo
        averlo inserito.
        """
        self.ensure_one()
        channel = self.company_id.sdi_channel_id
        if not channel:
            raise UserError(_(
                "Nessun canale di fatturazione elettronica configurato per questa "
                "azienda. Contatta l'assistenza."
            ))
        self.set_values()
        return channel.action_erpiant_activate()
