# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class FatturaPAAttachmentOut(models.Model):
    _inherit = "fatturapa.attachment.out"

    erpiant_identifier = fields.Char(
        string="Erpiant SDI Identifier",
        readonly=True,
        copy=False,
        help="Identificativo della transazione restituito dal broker SDI Erpiant "
        "(corrisponde all'identifier Invoicetronic).",
    )
    erpiant_send_id = fields.Integer(
        string="Erpiant Send ID",
        readonly=True,
        copy=False,
    )
