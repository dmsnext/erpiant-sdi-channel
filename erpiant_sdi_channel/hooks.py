# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    """Auto-provisioning del canale SDI Erpiant per ogni azienda.

    Garantisce l'esclusività del fornitore (cfr. §7.7 del piano architetturale):
    crea un unico canale ``erpiant_aws`` per azienda e lo associa, senza che
    l'utente debba (o possa) scegliere un fornitore. Eseguito in ``sudo`` perché
    la creazione dei canali è riservata al gruppo tecnico (ACL di lock-down).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    SdiChannel = env["sdi.channel"]
    companies = env["res.company"].search([])
    for company in companies:
        channel = SdiChannel.search(
            [
                ("company_id", "=", company.id),
                ("channel_type", "=", "erpiant_aws"),
            ],
            limit=1,
        )
        if not channel:
            channel = SdiChannel.create(
                {
                    "name": "Erpiant SDI",
                    "channel_type": "erpiant_aws",
                    "company_id": company.id,
                    "erpiant_environment": "test",
                }
            )
            _logger.info(
                "Erpiant SDI: creato canale per azienda %s", company.display_name
            )
        if company.sdi_channel_id != channel:
            company.sdi_channel_id = channel.id
