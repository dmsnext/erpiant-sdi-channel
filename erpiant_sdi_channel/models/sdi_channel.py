# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .erpiant_client import ErpiantSdiClient, ErpiantSdiError

_logger = logging.getLogger(__name__)

#: Lock-down esclusività fornitore (cfr. doc/ARCHITETTURA_erpiant_sdi_channel.md §7.7).
#: Disattivare questa guardia per consentire fornitori SDI diversi da Erpiant
#: richiede una MODIFICA DEL CODICE (e redeploy): non è esposta in UI né in
#: ``ir.config_parameter``. È la "leva" unica di sblocco a livello applicativo.
ERPIANT_SDI_LOCKDOWN = True
ERPIANT_ALLOWED_CHANNEL_TYPES = ("erpiant_aws",)

#: Mappa gli stati SdI restituiti da Invoicetronic (campo ``state``/``latest_state``)
#: sugli stati di ``fatturapa.attachment.out`` del framework OCA l10n_it_sdi_channel.
ERPIANT_STATE_MAP = {
    "Inviato": "sent",
    "Consegnato": "validated",
    "NonConsegnato": "recipient_error",
    "ImpossibilitaDiRecapito": "recipient_error",
    "Scartato": "sender_error",
    "AccettatoDalDestinatario": "accepted",
    "RifiutatoDalDestinatario": "rejected",
    "DecorrenzaTermini": "validated",
    "AttestazioneTrasmissioneFattura": "accepted",
}


class SdiChannel(models.Model):
    _inherit = "sdi.channel"

    channel_type = fields.Selection(
        selection_add=[("erpiant_aws", "Erpiant SDI (AWS)")],
        ondelete={"erpiant_aws": "cascade"},
    )
    erpiant_endpoint_url = fields.Char(
        string="Broker SDI URL",
        help="URL base del broker SDI di erpiant.com che inoltra a Invoicetronic, "
        "es. https://sdi.erpiant.com/sdi",
    )
    erpiant_auth_token = fields.Char(
        string="Token tenant",
        help="Token Bearer rilasciato da erpiant.com per questo tenant. "
        "La API Key Invoicetronic NON risiede nel tenant: vive solo nel broker.",
    )
    erpiant_environment = fields.Selection(
        selection=[("test", "Sandbox (test)"), ("live", "Produzione (live)")],
        string="Ambiente",
        default="test",
        required=True,
        help="In sviluppo usare sempre 'Sandbox (test)'. La chiave effettiva "
        "(ik_test_… / ik_live_…) è selezionata lato broker in base a questo valore.",
    )
    erpiant_signature = fields.Selection(
        selection=[
            ("Auto", "Automatica (consigliata)"),
            ("Force", "Forza sempre"),
            ("Apply", "Applica se non firmata"),
            ("None", "Nessuna firma"),
        ],
        string="Firma digitale",
        default="Auto",
        help="Modalità di firma CAdES (.p7m) richiesta al broker per l'invio allo "
        "SdI. Lo SdI accetta solo fatture firmate: 'Automatica' lascia decidere il "
        "servizio, 'Forza sempre' firma in ogni caso.",
    )

    # ------------------------------------------------------------------
    # Lock-down esclusività fornitore Erpiant
    # ------------------------------------------------------------------
    @api.constrains("channel_type")
    def _check_erpiant_lockdown(self):
        if not ERPIANT_SDI_LOCKDOWN:
            return
        for channel in self:
            if channel.channel_type not in ERPIANT_ALLOWED_CHANNEL_TYPES:
                raise ValidationError(
                    _(
                        "Questo tenant è configurato per la fatturazione elettronica "
                        "esclusivamente tramite il servizio Erpiant. Per utilizzare un "
                        "altro fornitore (PEC, SdICoop, …) è necessaria una modifica "
                        "del codice del modulo erpiant_sdi_channel."
                    )
                )

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------
    def _erpiant_get_client(self):
        self.ensure_one()
        auth_header = "Bearer %s" % (self.erpiant_auth_token or "")
        return ErpiantSdiClient(
            base_url=self.erpiant_endpoint_url,
            auth_header=auth_header,
            environment=self.erpiant_environment or "test",
        )

    # ------------------------------------------------------------------
    # Outbound: invio fatture attive
    # ------------------------------------------------------------------
    def send_via_erpiant_aws(self, attachment_out_ids):
        """Invia le fatture elettroniche al broker SDI Erpiant.

        Per ogni ``fatturapa.attachment.out`` invia l'XML via broker, salva
        l'identifier restituito e porta lo stato a ``sent``. Gli stati SdI
        successivi (consegna/scarto/…) sono raccolti dal cron ``_erpiant_pull``.
        """
        self.ensure_one()
        client = self._erpiant_get_client()
        for attachment in attachment_out_ids:
            xml_bytes = base64.b64decode(attachment.datas)
            try:
                result = client.send_xml(
                    xml_bytes, signature=self.erpiant_signature or None
                )
            except ErpiantSdiError as exc:
                _logger.exception("Erpiant SDI: invio %s fallito", attachment.name)
                attachment.write(
                    {
                        "state": "sender_error",
                        "last_sdi_response": _("Invio al broker Erpiant fallito: %s")
                        % exc,
                    }
                )
                continue
            identifier = (result or {}).get("identifier")
            send_id = (result or {}).get("id")
            latest_state = (result or {}).get("latest_state")
            new_state = ERPIANT_STATE_MAP.get(latest_state, "sent")
            attachment.write(
                {
                    "state": new_state,
                    "erpiant_identifier": identifier,
                    "erpiant_send_id": send_id,
                    "sending_date": fields.Datetime.now(),
                    "sending_user": self.env.user.id,
                    "last_sdi_response": _(
                        "Inviato via broker Erpiant. Identifier: %(identifier)s; "
                        "Stato SdI: %(state)s"
                    )
                    % {"identifier": identifier, "state": latest_state or "Inviato"},
                }
            )
        return True

    # ------------------------------------------------------------------
    # Pull: aggiornamenti di stato (notifiche SdI) + fatture passive
    # ------------------------------------------------------------------
    def _erpiant_pull_updates(self):
        """Recupera le notifiche di stato e aggiorna le fatture attive."""
        self.ensure_one()
        client = self._erpiant_get_client()
        attachment_model = self.env["fatturapa.attachment.out"]
        updates = client.get_updates(unread=True) or []
        for upd in updates:
            identifier = upd.get("identifier") or (upd.get("send") or {}).get(
                "identifier"
            )
            send_id = upd.get("send_id")
            attachment = attachment_model.browse()
            if identifier:
                attachment = attachment_model.search(
                    [("erpiant_identifier", "=", identifier)], limit=1
                )
            if not attachment and send_id:
                attachment = attachment_model.search(
                    [("erpiant_send_id", "=", send_id)], limit=1
                )
            if not attachment:
                continue
            state = ERPIANT_STATE_MAP.get(upd.get("state"))
            if not state:
                continue
            vals = {
                "state": state,
                "last_sdi_response": _(
                    "Stato SdI: %(state)s; Message ID: %(mid)s; %(descr)s"
                )
                % {
                    "state": upd.get("state"),
                    "mid": upd.get("message_id") or "",
                    "descr": upd.get("description") or "",
                },
            }
            if state == "validated":
                vals["delivered_date"] = fields.Datetime.now()
            attachment.write(vals)
        return True

    def _erpiant_pull_inbound(self):
        """Scarica le fatture passive recapitate dallo SdI via broker."""
        self.ensure_one()
        client = self._erpiant_get_client()
        incoming = client.get_receive_list(unread=True) or []
        for inv in incoming:
            file_name = inv.get("file_name")
            receive_id = inv.get("id")
            if not file_name or not receive_id:
                continue
            # Una passiva malformata non deve interrompere il ciclo: il broker
            # marca gli elementi come "letti" alla lettura, quindi un errore qui
            # non deve far perdere le altre notifiche/passive.
            try:
                resp = client.get_receive_payload(receive_id)
                # Il broker incapsula la risposta come {"id": .., "payload": <base64>};
                # Invoicetronic restituisce il file (p7m firmato) codificato base64.
                payload = resp.get("payload") if isinstance(resp, dict) else resp
                if payload is None:
                    continue
                if isinstance(payload, str):
                    payload = payload.encode("ascii")
                # receive_fe si aspetta i byte grezzi del file e li ri-codifica.
                try:
                    payload = base64.b64decode(payload, validate=True)
                except (ValueError, TypeError):
                    pass  # già in formato binario grezzo
                self.receive_fe(
                    {file_name: payload},
                    {},
                    company_id=self.company_id.id,
                )
            except Exception as exc:  # noqa: BLE001 - resilienza per-elemento
                _logger.exception(
                    "Erpiant SDI: import passiva %s (id %s) fallito: %s",
                    file_name,
                    receive_id,
                    exc,
                )
        return True

    @api.model
    def _cron_erpiant_pull(self):
        """Cron: per ogni canale Erpiant configurato, raccoglie stati e passive."""
        channels = self.search([("channel_type", "=", "erpiant_aws")])
        for channel in channels:
            if not (channel.erpiant_endpoint_url and channel.erpiant_auth_token):
                _logger.info(
                    "Erpiant SDI: canale %s non configurato, salto", channel.name
                )
                continue
            try:
                channel._erpiant_pull_updates()
                channel._erpiant_pull_inbound()
            except ErpiantSdiError as exc:
                _logger.warning("Erpiant SDI: pull canale %s: %s", channel.name, exc)
        return True

    def action_erpiant_pull_now(self):
        """Azione manuale: forza subito il pull (debug/diagnostica)."""
        for channel in self.filtered(lambda c: c.channel_type == "erpiant_aws"):
            if not (channel.erpiant_endpoint_url and channel.erpiant_auth_token):
                raise UserError(
                    _("Configurare URL broker e token prima di sincronizzare.")
                )
            channel._erpiant_pull_updates()
            channel._erpiant_pull_inbound()
        return True
