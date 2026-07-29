# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    erpiant_environment = fields.Selection(
        related="company_id.sdi_channel_id.erpiant_environment",
        string="Ambiente fatturazione elettronica Erpiant",
        readonly=True,
    )
