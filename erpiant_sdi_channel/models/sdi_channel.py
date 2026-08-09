# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .erpiant_client import ErpiantSdiClient, ErpiantSdiError

_logger = logging.getLogger(__name__)

#: Sito che media l'attivazione. Sovrascrivibile con l'``ir.config_parameter``
#: ``erpiant_sdi_channel.site_url`` (utile in devel/staging), ma il default deve
#: funzionare senza configurazione: il cliente installa e attiva, punto.
DEFAULT_SITE_URL = "https://www.erpiant.com"

#: L'attivazione attraversa sito -> broker -> Invoicetronic (registrazione P.IVA):
#: la catena e' piu' lunga di una chiamata normale, per questo il timeout e' ampio.
ACTIVATION_TIMEOUT = 60

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
        readonly=True,
        copy=False,
        help="Token Bearer rilasciato da erpiant.com per questo tenant. "
        "La API Key Invoicetronic NON risiede nel tenant: vive solo nel broker.\n"
        "NON si compila a mano: lo si ottiene attivando la fatturazione elettronica "
        "con il numero di licenza del commercialista.",
    )
    # --- Attivazione tramite numero di licenza --------------------------------
    # Decisione utente (2026-08-09): nel tenant entra SOLO il numero di licenza.
    # I token — sia questa credenziale sia i prepagati — vivono su sito e broker, e
    # il cliente li consulta nella propria area riservata. Motivo concreto: un campo
    # token editabile permetteva di scavalcare licenza, wallet e tracciamento del
    # commercialista incollando dentro un valore qualsiasi.
    erpiant_license_code = fields.Char(
        string="Numero di licenza",
        copy=False,
        help="Codice fornito dal commercialista. Attivandolo, il tenant riceve "
        "automaticamente la credenziale per il broker: non serve (e non è "
        "possibile) inserire token a mano.",
    )
    erpiant_tenant_ref = fields.Char(
        string="Riferimento assistenza",
        readonly=True,
        copy=False,
        help="Identificativo del tenant presso erpiant.com. NON è un segreto: è "
        "l'unico riferimento citabile quando si chiede assistenza, perché il "
        "token non si può comunicare a nessuno.",
    )
    erpiant_activation_state = fields.Selection(
        selection=[("inactive", "Non attiva"), ("active", "Attiva")],
        string="Stato fatturazione elettronica",
        compute="_compute_erpiant_activation_state",
        store=True,
        help="Attiva quando il tenant ha ottenuto la credenziale dal sito "
        "tramite il numero di licenza.",
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
    # Attivazione
    # ------------------------------------------------------------------
    @api.depends("erpiant_auth_token", "erpiant_endpoint_url", "channel_type")
    def _compute_erpiant_activation_state(self):
        for channel in self:
            channel.erpiant_activation_state = (
                "active"
                if (
                    channel.channel_type == "erpiant_aws"
                    and channel.erpiant_endpoint_url
                    and channel.erpiant_auth_token
                )
                else "inactive"
            )

    def _erpiant_check_active(self):
        """Blocca l'operazione se la fatturazione elettronica non è attivata.

        Sostituisce l'errore tecnico che usciva prima («Token di autenticazione
        verso il broker non configurato»): per il cliente era un'applicazione
        rotta, non un servizio da attivare. Qui diciamo cosa fare e dove.
        """
        self.ensure_one()
        if self.erpiant_activation_state == "active":
            return
        raise UserError(
            _(
                "La fatturazione elettronica non è ancora attiva su questa "
                "installazione.\n\n"
                "Per attivarla serve il NUMERO DI LICENZA che ti fornisce il tuo "
                "commercialista. Inseriscilo in:\n"
                "Opzioni → Impostazioni generali → Fatturazione elettronica\n\n"
                "Il commercialista lo genera dopo aver attivato per te la "
                "conservazione a norma presso l'Agenzia delle Entrate: è gratuita "
                "e va fatta una sola volta."
            )
        )

    # ------------------------------------------------------------------
    # Attivazione con numero di licenza
    # ------------------------------------------------------------------
    def action_erpiant_activate(self):
        """Scambia il numero di licenza con la credenziale, tramite il SITO.

        Il tenant NON parla mai in privilegiato col broker: `/provisioning/tenant`
        e' admin-only e quel token vive in SSM per il solo task role del sito. Se
        il tenant avesse credenziali admin, chiunque riceva l'.exe potrebbe coniare
        token per P.IVA altrui. Quindi: tenant -> sito -> broker.

        Contratto concordato sulla board (Sito-Struttura `ec62995`, Broker
        `c3df29e`): POST {site}/sdi/activation con {license_code, vat} ->
        {token, endpoint_url, environment, tenant_id, rotated}.
        """
        self.ensure_one()
        code = (self.erpiant_license_code or "").strip()
        if not code:
            raise UserError(_(
                "Inserisci il numero di licenza che ti ha fornito il commercialista."
            ))

        company = self.company_id or self.env.company
        vat = (company.vat or "").strip()
        if not vat:
            raise UserError(_(
                "Prima di attivare la fatturazione elettronica devi indicare la "
                "partita IVA della tua azienda in:\n"
                "Opzioni → Impostazioni generali → Aziende."
            ))

        site_url = (
            self.env["ir.config_parameter"].sudo()
            .get_param("erpiant_sdi_channel.site_url", DEFAULT_SITE_URL)
            .rstrip("/")
        )
        try:
            response = requests.post(
                "%s/sdi/activation" % site_url,
                json={"license_code": code, "vat": vat},
                headers={"Accept": "application/json"},
                timeout=ACTIVATION_TIMEOUT,
            )
        except requests.RequestException as exc:
            _logger.warning("Erpiant SDI: attivazione irraggiungibile: %s", exc)
            raise UserError(_(
                "Non riesco a contattare erpiant.com per attivare la licenza.\n\n"
                "Verifica la connessione a internet e riprova. Se il problema "
                "persiste, il servizio potrebbe essere temporaneamente non "
                "disponibile: la licenza resta valida e puoi riprovare più tardi."
            )) from exc

        self._erpiant_raise_for_activation(response)

        data = response.json()
        token = (data or {}).get("token")
        if not token:
            raise UserError(_(
                "erpiant.com ha risposto senza la credenziale di attivazione. "
                "Riprova; se persiste, segnala il problema indicando il tuo numero "
                "di licenza."
            ))

        # Scrittura in sudo: i campi sono readonly proprio perche' nessun umano
        # deve poterli comporre a mano. Qui li scrive il flusso di attivazione.
        vals = {
            "erpiant_auth_token": token,
            "erpiant_endpoint_url": data.get("endpoint_url") or self.erpiant_endpoint_url,
        }
        if data.get("environment") in ("test", "live"):
            vals["erpiant_environment"] = data["environment"]
        if data.get("tenant_id"):
            vals["erpiant_tenant_ref"] = data["tenant_id"]
        self.sudo().write(vals)

        # `rotated` distingue reinstallazione da prima attivazione: senza, a chi
        # reinstalla diremmo "attivata!" come se fosse la prima volta, e non
        # capirebbe se il credito residuo e' ancora suo.
        if data.get("rotated"):
            message = _(
                "Fatturazione elettronica riattivata su questa installazione.\n\n"
                "Il tuo credito e lo storico degli invii sono stati mantenuti."
            )
        else:
            message = _("Fatturazione elettronica attivata.")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Attivazione"), "message": message,
                       "type": "success", "sticky": False},
        }

    @staticmethod
    def _erpiant_raise_for_activation(response):
        """Traduce la risposta HTTP in un messaggio utile a un micro-imprenditore.

        Ogni codice dice cosa fare, non cosa e' successo a noi: chi legge non sa
        (e non deve sapere) cosa sia un 403 o un gate Basic Auth.
        """
        if response.status_code == 200:
            return
        if response.status_code == 404:
            raise UserError(_(
                "Numero di licenza non riconosciuto.\n\n"
                "Controlla di averlo copiato per intero (ha la forma "
                "ERP-XXXX-XXXX-XXXX). Se il problema persiste, chiedi al tuo "
                "commercialista di verificarlo."
            ))
        if response.status_code == 403:
            raise UserError(_(
                "Il numero di licenza non corrisponde alla partita IVA di questa "
                "azienda.\n\n"
                "Verifica la partita IVA in Opzioni → Impostazioni generali → "
                "Aziende. Se è corretta, la licenza è stata emessa per un'altra "
                "azienda: chiedi al tuo commercialista."
            ))
        if response.status_code == 401:
            # Il sito è dietro il gate Basic Auth di Traefik fino al go-live e
            # `/sdi/activation` va esentato (segnalato dal Broker, in coda infra).
            # Fino ad allora QUESTO è l'errore che si vede: senza un messaggio
            # dedicato sembrerebbe una licenza sbagliata, e si perderebbe tempo
            # a cercare il problema dalla parte opposta.
            raise UserError(_(
                "Il servizio di attivazione non è ancora aperto al pubblico.\n\n"
                "Non è un problema della tua licenza. Riprova più tardi o "
                "contatta l'assistenza."
            ))
        if response.status_code in (502, 503, 504):
            raise UserError(_(
                "Il servizio di attivazione è momentaneamente non disponibile.\n\n"
                "La tua licenza resta valida: riprova fra qualche minuto."
            ))
        _logger.warning(
            "Erpiant SDI: attivazione HTTP %s: %s",
            response.status_code, (response.text or "")[:300],
        )
        raise UserError(_(
            "Attivazione non riuscita (codice %s).\n\n"
            "Riprova; se persiste, segnala il problema indicando il tuo numero "
            "di licenza."
        ) % response.status_code)

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
        self._erpiant_check_active()
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
            channel._erpiant_check_active()
            channel._erpiant_pull_updates()
            channel._erpiant_pull_inbound()
        return True
